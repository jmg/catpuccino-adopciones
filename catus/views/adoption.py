import hashlib
import json
import logging
import random
import uuid
from forms_builder.forms.forms import FormForForm
from forms_builder.forms.models import Form, Field, FieldEntry

from catus.models import Animal, CatusUser, EstadoFormulario
from catus.utils import send_html_email
from catus.services.adoption import AdoptionService
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
        context["honeypot_field"] = HONEYPOT_FIELD
        context["form_max_bytes"] = FORM_MAX_BYTES
        context["form_max_mb"] = FORM_MAX_BYTES // (1024 * 1024)

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
            return BaseView.render_to_response(self, {"form": form, "is_post": True, "success": True})

        rejected = self._rejected()
        if rejected:
            return BaseView.render_to_response(self, {"form": form, "is_post": True, "success": False, "errors": rejected})

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
            return BaseView.render_to_response(self, response_context)

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

        self.send_email(form_entry, form_for_form, animal_name, estado)
        response_context["success"] = True
        return BaseView.render_to_response(self, response_context)

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

