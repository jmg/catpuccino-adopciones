import hashlib
import html
import json
import logging
import random
import re
import uuid
from forms_builder.forms.forms import FormForForm
from forms_builder.forms.models import Form, Field, FieldEntry

from catus.models import Animal, CatusUser, EstadoFormulario
from catus.utils import send_html_email
from catus.services.adoption import AdoptionService
from catus.services.buenadoptante import CALIFICACIONES, BuenAdoptanteService
from catus.services.images import shrink_uploads
from catus.services import throttle
from catus.views.contrato import mail_del_adoptante

from django.template import Context
from django.conf import settings
from django.utils import timezone
from catus.views.home import BaseView

# Anyone can post these forms, without an account or a captcha. The heaviest asks
# for six photos (the dogs' form; the cats' for three), and a phone photo weighs
# several MB; the view shrinks them only after they arrive. nginx.conf (catpuccino
# repo) cuts at a little more than this, so this is what a real visitor reads.
FORM_MAX_BYTES = 40 * 1024 * 1024
FORM_MAX_PER_HOUR = 10          # per address: someone can apply for several animals
RECEIPTS_MAX_PER_DAY = 5        # per mailbox: the receipt goes to whatever was typed
HONEYPOT_FIELD = "sitio_web"    # hidden from people, see preadoption.html
logger = logging.getLogger(__name__)

#BuenAdoptante rechaza la consulta entera si el nombre es una sola palabra, un mail o un
#teléfono (full_name_required): ese formulario no se revisaba ni se registraba. Pasaba en 1
#de cada 25. preadoption.html hace el mismo control antes de enviar (esNombreYApellido).
MENSAJE_NOMBRE = "Poné tu nombre y apellido, por ejemplo: Ana Pérez."


def es_nombre_y_apellido(texto):
    """Al menos dos palabras con letras, y que no sea un mail."""

    texto = texto or ""
    palabras = [p for p in texto.split() if re.search(r"[^\W\d_]", p)]
    return len(palabras) >= 2 and "@" not in texto


class ListView(BaseView):

    url = r"^adopciones/$"

    def render_to_response(self, context):

        context["animals"] = Animal.get_all_for_adoption(sort="{}nombre".format(random.choice(["", "-"])))
        context["perros_en_adopcion"] = bool([animal for animal in context["animals"] if animal.tipo == "P"])

        return BaseView.render_to_response(self, context)


class PreAdoptionView(BaseView):

    url = r"^pre-adopcion/$"
    form_type = "preadoption"
    animal_type = "gato"

    #Buscar el formulario por posición (Form.objects.all()[0]) depende del orden en
    #que se hayan creado: borrar uno desplaza al resto y esta página puede terminar
    #mostrando otro formulario, o directamente caerse. El slug es estable.
    form_slug = "formulario-de-pre-adopcion"
    form_index = 0

    def render_to_response(self, context):

        animals = []
        tipo = "P" if self.animal_type == "perro" else "G"

        user_id = self.request.GET.get("user_id")
        extra_filters = {}
        if user_id:
            try:
                extra_filters["cargado_por"] = CatusUser.objects.get(id=user_id)
            except:
                pass

        animals_objs = Animal.get_all_for_adoption(sort="nombre", tipo=tipo, extra_filters=extra_filters)
        for animal in animals_objs:
            animals.append({"name": str(animal), "id": animal.id})

        animals = json.dumps(animals)
        context["animals"] = animals
        context.update(self._script_context())

        form = self._get_form()
        animal_id = self.request.GET.get("id")

        context["form_for_form"] = FormForForm(form, Context(context), None, None)
        context["form"] = form
        context["is_post"] = False

        context["hidden_terms_cookie"] = "hidden-terms-{}".format(self.form_type)
        context["accepted_terms_cookie"] = "accepted-terms-{}-{}".format(self.form_type, self.animal_type)
        context["form_type"] = self.form_type
        context["animal_type"] = self.animal_type
        context["is_user"] = True if user_id else False
        #la persona tiene que saber, antes de mandarlo, que el formulario se comparte
        context["comparte_con_buenadoptante"] = self.form_type == "preadoption" and BuenAdoptanteService().activo()
        #prepareSubmit controla el nombre antes de enviar, para no perder las fotos adjuntas
        context["campo_nombre"] = self._campo_nombre(context["form_for_form"])
        context["mensaje_nombre"] = MENSAJE_NOMBRE

        if self.form_type == "preadoption":

            if self.animal_type == "gato":
                context["post_url"] = "/pre-adopcion/"
            elif self.animal_type == "perro":
                context["post_url"] = "/pre-adopcion/perros/"

        elif self.form_type == "transit":

            if self.animal_type == "gato":
                context["post_url"] = "/transito/"
            elif self.animal_type == "perro":
                context["post_url"] = "/transito/perros/"

        if animal_id:
            try:
                animal = Animal.objects.filter(id=animal_id)
                context["animal"] = animal[0]
            except:
                pass

        return BaseView.render_to_response(self, context)

    def _script_context(self):
        """Lo que el <script> de preadoption.html escribe tal cual dentro del JS.

        Tiene que estar en todas las respuestas, también en las del envío ("formulario
        enviado" y las de error): ahí faltaba form_max_bytes, el script quedaba como
        "if (total > )" y el navegador lo descartaba entero. Con él se perdía el
        clearForm(), y las respuestas del adoptante (datos personales) seguían en el
        localStorage y volvían a llenar el formulario en la próxima visita.
        """

        return {
            "honeypot_field": HONEYPOT_FIELD,
            "form_max_bytes": FORM_MAX_BYTES,
            "form_max_mb": FORM_MAX_BYTES // (1024 * 1024),
        }

    def _post_response(self, context):

        context.update(self._script_context())
        return BaseView.render_to_response(self, context)

    def _get_form(self):

        form = Form.objects.filter(slug=self.form_slug).first()
        if form is not None:
            return form

        #si el slug cambió en el admin no dejamos la página pública sin formulario:
        #caemos al comportamiento de antes y avisamos por el log
        logger.error(
            "No hay ningún formulario con slug '%s'; usando el de la posición %s.",
            self.form_slug, self.form_index,
        )

        forms = Form.objects.all()[self.form_index:self.form_index + 1]
        return forms[0] if forms else None

    def _campo_nombre(self, form_for_form):
        """La clave de "Nombre y Apellido" en el formulario de pre-adopción, o None. Se busca
        por etiqueta, como la busca BuenAdoptanteService: si la cambian en el admin, no se
        controla (y tampoco se manda)."""

        if self.form_type != "preadoption" or form_for_form is None:
            return None
        for clave, campo in form_for_form.fields.items():
            if "nombre y apellido" in (campo.label or "").lower():
                return clave
        return None

    def _rejected(self):
        """Why this post is not even read, or None. The size comes first, so that a
        file that is too big does not use up the visitor's attempts."""
        files = self.request.FILES
        if sum(upload.size for key in files for upload in files.getlist(key)) > FORM_MAX_BYTES:
            return "Los archivos adjuntos pesan demasiado: el máximo es de {} MB en total. Probá con menos fotos o con fotos más livianas.".format(FORM_MAX_BYTES // (1024 * 1024))

        who = throttle.client_ip(self.request)
        if who and throttle.hit("adoption-form", who, 60 * 60) > FORM_MAX_PER_HOUR:
            return "Recibimos demasiados formularios desde tu conexión. Por favor probá de nuevo en una hora."

        return None

    def post(self, *a, **k):

        form = self._get_form()

        # To a bot it looks like any other submission: nothing is stored or mailed.
        if self.request.POST.get(HONEYPOT_FIELD):
            return self._post_response({"form": form, "is_post": True, "success": True})

        rejected = self._rejected()
        if rejected:
            return self._post_response({"form": form, "is_post": True, "success": False, "errors": rejected})

        post = getattr(self.request, "POST", None)
        # Phone photos are shrunk before they are stored; see shrink_uploads.
        files = shrink_uploads(getattr(self.request, "FILES", None))

        animal_id = self.request.GET.get("id")

        context = {"request": self.request }

        form_for_form = FormForForm(form, Context(context), post, files)

        response_context = {}
        response_context["form_for_form"] = form_for_form
        response_context["form"] = form
        response_context["is_post"] = True

        if form_for_form.errors:
            response_context["errors"] = form_for_form.errors
            response_context["success"] = False
            return self._post_response(response_context)

        #lo mismo que controla el navegador; esto es para quien llega sin ese JS
        campo_nombre = self._campo_nombre(form_for_form)
        if campo_nombre and not es_nombre_y_apellido(form_for_form.cleaned_data.get(campo_nombre)):
            response_context["errors"] = MENSAJE_NOMBRE
            response_context["success"] = False
            return self._post_response(response_context)

        form_entry = form_for_form.save()

        if self.form_type == "preadoption":
            animal = AdoptionService().get_animal_obj(form_entry)
            animal_name = AdoptionService().get_animal(form_entry)
        else:
            animal = None
            animal_name = None

        try:
            persona_nombre = AdoptionService().get_form_attr(form_entry, "Nombre y Apellido")
        except:
            persona_nombre = None

        if self.form_type == "preadoption":
            if self.animal_type == "perro":
                tipo = "AP"
            else:
                tipo = "A"
        else:
            if self.animal_type == "perro":
                tipo = "TP"
            else:
                tipo = "T"

        estado = EstadoFormulario(
            form_entry=form_entry,
            persona_nombre=persona_nombre,
            hash=str(uuid.uuid4()),
            gato=animal,
            tipo=tipo,
            fecha_ingreso=timezone.now(),
        )
        estado.save()

        #BuenAdoptante, antes de que el formulario le llegue a nadie: con 1★ o 2★ se frena.
        #Si no contesta, el formulario pasa como siempre y el cron lo manda después.
        if self.form_type == "preadoption":
            actividad = BuenAdoptanteService().registrar_solicitud(estado)
            if actividad is not None and actividad.bloqueo:
                estado.estado = "B"
                estado.save(update_fields=["estado"])
                self.avisar_bloqueo(estado, actividad, animal_name)
                response_context["success"] = False
                response_context["bloqueado"] = True
                return self._post_response(response_context)

        self.send_email(form_entry, form_for_form, animal_name, estado)
        response_context["success"] = True
        return self._post_response(response_context)

    def avisar_bloqueo(self, estado, actividad, animal_name):
        """Al equipo, no al rescatista: el formulario frenado lo revisa el equipo."""

        #get_animal devuelve el Animal o, si no lo encuentra, el nombre que se escribió
        animal_name = str(animal_name) if animal_name else "sin animal"
        calificacion = CALIFICACIONES.get(actividad.nivel, "sin dato")
        subject = "Formulario frenado por BuenAdoptante ({}): {}".format(calificacion, animal_name)
        content = (
            "<p>Un formulario de pre-adopción para <b>{animal}</b> no se le mandó al rescatista: "
            "BuenAdoptante califica a la persona como <b>{calificacion}</b>.</p>"
            "<p>Formulario: <a href='https://{host}/formularios/{hash}/'>https://{host}/formularios/{hash}/</a><br>"
            "Perfil en BuenAdoptante: <a href='{perfil}'>{perfil}</a></p>"
            "<p>Si te parece un error: en el formulario pasalo a \"No asignado\" (así aparece en el panel del "
            "rescatista) y mandale el link.</p>"
        ).format(
            animal=html.escape(animal_name), calificacion=calificacion, host=settings.HOST,
            hash=estado.hash, perfil=html.escape(actividad.perfil_url or "-"),
        )
        try:
            send_html_email(subject, content, settings.SEND_MAIL, [settings.SEND_MAIL])
        except Exception as e:
            logger.warning("No se pudo avisar del formulario frenado %s: %s", estado.id, type(e).__name__)

    def find_form_same_person(self, form_entry, persona_nombre, tipo):

        same_person = FieldEntry.objects.filter(value=persona_nombre)
        if same_person:
            same_person = same_person[0]
            estado = EstadoFormulario.objects.filter(form_entry=same_person.entry, tipo=tipo)
            if estado:
                return estado[0]

    def _get_form_fields(self, form_entry):

        return [x for x in form_entry.fields.all()[1:]]

    def _get_email_template(self):

        return "email/form.html"

    def set_animal_name_otro(self, form_entry, value):

        for form_field in form_entry.fields.all():

            try:
                field = Field.objects.get(id=form_field.field_id)
            except:
                continue

            if "Nombre del gato a adoptar" in field.label:
                form_field.value = value
                form_field.save()

    def send_email(self, form_entry, form_for_form, animal, estado):

        if self.form_type == "preadoption":

            subject = "Nuevo formulario de pre-adopción para: {}".format(animal)
            self.set_animal_name_otro(form_entry, str(animal))

        elif self.form_type == "transit":

            if self.animal_type == "perro":
                subject = "Nuevo formulario de tránsito - Perros"
            else:
                subject = "Nuevo formulario de tránsito - Gatos"

        form_fields = self._get_form_fields(form_entry)
        fields = AdoptionService().get_formatted_fields(form_fields)

        email_context = {"animal": animal, "fields": fields, "form_hash": estado.hash, "settings": settings}
        content = self.render(self._get_email_template(), email_context)

        to_emails = ["catpuccino.ok@gmail.com"]

        #"animal" no siempre es un Animal: con la opción "otro" es el nombre que la
        #persona escribió a mano, y hay animales viejos sin rescatista asociado
        rescatista = getattr(animal, "cargado_por", None)
        if rescatista is not None and rescatista.email:
            to_emails.append(rescatista.email)

        #el formulario ya quedó guardado: si el mail falla, avisamos por el log pero
        #no le mostramos un error a quien acaba de completarlo (volvería a mandarlo)
        try:
            send_html_email(subject, content, settings.SEND_MAIL, list(set(to_emails)))
        except Exception:
            logger.exception("No se pudo avisar del formulario %s", estado.hash)

        # The receipt goes to the one address the candidate gave, if it is an address:
        # on the cats' form that field is free text. And since nothing proves it is
        # theirs, one mailbox gets only a few, or this would mail anyone on demand.
        email = mail_del_adoptante(estado)

        if not email:
            return

        mailbox = hashlib.sha256(email.lower().encode()).hexdigest()
        if throttle.hit("adoption-receipt", mailbox, 24 * 60 * 60) > RECEIPTS_MAX_PER_DAY:
            return

        email_context = {
            "animal": animal,
            "tipo": self.form_type,
        }

        subject = "Catpuccino Adopciones - Formulario Recibido"
        content = self.render("email/received.html", email_context)

        try:
            send_html_email(subject, content, settings.SEND_MAIL, email)
        except Exception:
            logger.exception("No se pudo confirmarle el formulario %s a %s", estado.hash, email)


class PreAdoptionPerrosView(PreAdoptionView):

    url = r"^pre-adopcion/perros/$"
    form_type = "preadoption"
    animal_type = "perro"
    template_name = "adoption/preadoption.html"

    form_slug = "formulario-de-pre-adopcion-para-perros"
    form_index = 3

