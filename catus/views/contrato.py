import html
import json
import uuid
import os.path
from django.views.generic import TemplateView
from django.core import signing
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect

from catus.models import Contrato, Animal, EstadoFormulario, ContratoPersona
from catus.forms import ContratoPersonaForm
from catus.services.adoption import AdoptionService
from catus.services.contrato import *
from catus.utils import send_html_email

from django.conf import settings
from django.utils import timezone
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email

from catus.views.base import puede_editar_animal
from threading import Thread

from catus.forms import ContratoForm


def mail_del_adoptante(estado_form):
    """El mail que el candidato dejó en su formulario (el que también arranca el
    contrato), o None si no hay uno válido."""
    if estado_form is None:
        return None

    respuestas = AdoptionService().get_form_attrs(estado_form.form_entry, ["Email"], exact=True) or []
    for _label, email in respuestas:
        email = (email or "").strip()
        try:
            validate_email(email)
        except ValidationError:
            continue
        return email

    return None


def contrato_pdf_response(contrato):

    path = contrato_pdf_path(contrato)
    if path is None:
        raise Http404("El adoptante todavía no completó este contrato.")

    with open(path, "rb") as f:
        response = HttpResponse(f.read(), content_type='application/pdf')

    response['Content-Disposition'] = 'attachment; filename={}'.format(CONTRATO_PDF)
    response['Cache-Control'] = 'private, no-store'

    return response


class EditView(TemplateView):

    url = [r"^formulario/(?P<estado_id>(\d+))/contrato/$"]
    is_persona = False

    def requiere_login(self):
        """La pantalla por id es del equipo y muestra los datos personales del adoptante.

        La versión por hash (EditPersonaView) la usa el adoptante, que no tiene cuenta.
        """

        return not self.is_persona

    def dispatch(self, request, *args, **kwargs):

        if self.requiere_login() and not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        return super().dispatch(request, *args, **kwargs)

    def puede_ver(self, estado_form):
        """El equipo ve todos los contratos; cada rescatista, los de sus animales.

        Sin esto alcanzaba con estar registrado (y el registro es abierto) para
        recorrer los contratos de toda la organización con los datos personales
        de cada adoptante.
        """

        if self.is_persona:
            return True

        return puede_editar_animal(self.request.user, estado_form.gato)

    def req(self, is_post=False, **kwargs):

        context = {}
        context["is_persona"] = self.is_persona
        gato = None

        if not self.is_persona:
            estado_form = get_object_or_404(EstadoFormulario, id=self.kwargs.get("estado_id"))
            try:
                contrato = Contrato.objects.get(estado_formulario=estado_form)
            except:
                contrato = None
        else:
            contrato = get_object_or_404(Contrato, hash=self.kwargs.get("contrato_hash"))
            estado_form = contrato.estado_formulario

        if not self.puede_ver(estado_form):
            raise PermissionDenied("Este formulario es de otra persona.")

        gato = estado_form.gato

        if not contrato:

            data_attrs = AdoptionService().get_form_attrs(estado_form.form_entry, ["Nombre y Apellido", "Edad", "Profesión",
            "Celular", "Email", "Partido", "Localidad", "Facebook", "Instagram"], exact=True)
            data_attrs = dict(data_attrs)

            adoptante = ContratoPersona(
                persona_nombre=data_attrs.get("Nombre y Apellido"),
                persona_ocupacion=data_attrs.get("Profesión"),
                persona_celular=data_attrs.get("Celular"),
                persona_localidad=data_attrs.get("Localidad"),
                persona_facebook=data_attrs.get("Facebook"),
                persona_instagram=data_attrs.get("Instagram"),
                persona_email=data_attrs.get("Email"),
            )
            adoptante.save()

            contrato = Contrato(
                hash=str(uuid.uuid4()),
                gato=gato if isinstance(gato, Animal) else None,
                gato_nombre=gato.nombre if gato else None,
                gato_edad=gato.edad if gato else None,
                gato_sexo=gato.sexo if gato else "D",
                miembro_adopcion_nombre="",
                adoptante=adoptante,
                estado_formulario=estado_form,
            )
            contrato.save()

        if not is_post:

            if not self.is_persona:
                contrato_form = ContratoForm(instance=contrato)
            else:
                contrato_form = ContratoPersonaForm(instance=contrato.adoptante)
                gato_form = ContratoForm(instance=contrato)
                gato_data = {}

                for key in gato_form.fields.keys():

                    if gato.tipo == "P":
                        if key in ["gato_vacunacion_triple_1_dosis", "gato_vacunacion_triple_1_dosis_fecha", "gato_vacunacion_triple_1_dosis_notas", "gato_vacunacion_triple_2_dosis", "gato_vacunacion_triple_2_dosis_fecha", "gato_vacunacion_triple_2_dosis_notas"]:
                            continue

                    elif gato.tipo == "G":
                        if key in ["perro_vacunacion_quintuple_1_dosis", "perro_vacunacion_quintuple_1_dosis_fecha", "perro_vacunacion_quintuple_1_dosis_notas", "perro_vacunacion_quintuple_2_dosis", "perro_vacunacion_quintuple_2_dosis_fecha", "perro_vacunacion_quintuple_2_dosis_notas", "perro_vacunacion_sextuple_1_dosis", "perro_vacunacion_sextuple_1_dosis_fecha", "perro_vacunacion_sextuple_1_dosis_notas"]:
                            continue

                    if key == "gato_sexo":
                        gato_data[gato_form.fields[key].label] = contrato.get_gato_sexo_display()
                    elif gato_form.fields[key].__class__.__name__ == "BooleanField":
                        gato_data[gato_form.fields[key].label] = "Si" if getattr(contrato, key) else "No"
                    elif gato_form.fields[key].__class__.__name__ == "DateField":
                        date = getattr(contrato, key)
                        gato_data[gato_form.fields[key].label.replace("(dd/mm/yyyy)", "").strip()] = date.strftime("%d/%m/%Y") if date else ""
                    else:
                        value = getattr(contrato, key)
                        label = gato_form.fields[key].label.replace("(Opcional)", "").strip()
                        gato_data[label] = value if value else ""

                context["gato_data"] = gato_data
                context["gato_form"] = gato_form

            context["form"] = contrato_form
            context["contrato"] = contrato
            context["gato"] = gato
            context["settings"] = settings
            context["estado_form"] = estado_form

            return self.render_to_response(context)

        else:
            post_context = {}
            if not self.is_persona:
                contrato_form = ContratoForm(self.request.POST, instance=contrato)
            else:
                contrato_form = ContratoPersonaForm(self.request.POST, instance=contrato.adoptante)

            if contrato_form.is_valid():
                contrato_form.save()
                post_context["status"] = "success"

                if not self.is_persona and self.request.POST.get("send_email") == "1":
                    #enviar mail al adoptante. Solo al de este formulario, al mail que dejó
                    #al postularse, y el texto como texto: el destinatario, el asunto y el
                    #HTML salían del POST, y cualquier cuenta (el registro es abierto) mandaba
                    #lo que quisiera a quien quisiera desde la casilla del sitio.
                    email = mail_del_adoptante(estado_form)
                    if not email:
                        post_context["status"] = "fail"
                        post_context["errors"] = "El contrato se guardó, pero el formulario no tiene un mail válido del adoptante: no se envió nada."
                        return HttpResponse(json.dumps(post_context))

                    subject = " ".join((self.request.POST.get("subject") or "").split())[:200] \
                        or "Catpuccino Adopciones - Contrato de adopción responsable"
                    content = html.escape(self.request.POST.get("content") or "").replace("\n", "<br>")

                    consejos_file = os.path.join(settings.STATICFILES_DIRS[0], "contrato", "consejos.pdf")
                    with open(consejos_file, "rb") as f:
                        file_content = f.read()

                    file2 = {
                        "name": "Consejos para el Adoptante.pdf",
                        "content": file_content,
                        "content_type": "application/pdf",
                    }

                    def _send_email():
                        send_html_email(subject, content, settings.SEND_MAIL, email, file=file2)

                    t = Thread(target=_send_email)
                    t.start()

                    contrato.email_enviado = True
                    contrato.save()

                if self.is_persona:

                    post_context["contrato_url"], pdf_file, pdf_name = generate_contrato_pdf(contrato)

                    #Email para el encargado de la adopción
                    subject = "Contrato de adopción responsable completado para: {}".format(gato)
                    content = "{} ha completado el contrato de adopción responsable usando la web de Catpuccino Adopciones.".format(contrato.adoptante.persona_nombre)

                    file = {
                        "name": pdf_name,
                        "content": pdf_file,
                        "content_type": "application/pdf",
                    }

                    contrato.contrato_aceptado = True
                    contrato.save()

                    def _send_email():
                        send_html_email(subject, content, settings.SEND_MAIL, [gato.cargado_por.email, settings.SEND_MAIL], file=file)

                    t = Thread(target=_send_email)
                    t.start()

                    #Email para el adoptante
                    if contrato.get_tipo() == "P":
                        content = "En este mail encontrarás el contrato de adopción responsable."
                        subject = "Catpuccino Adopciones - Contrato de adopción responsable"
                    else:
                        content = "En este mail encontrarás el contrato de adopción responsable."
                        subject = "Catpuccino Adopciones - Contrato de adopción responsable"

                    if contrato.get_tipo() == "P":

                        def _send_persona_email():
                            send_html_email(subject, content, settings.SEND_MAIL, [contrato.adoptante.persona_email], file=[file])

                    else:
                        #consejos_file = os.path.join(settings.STATICFILES_DIRS[0], "contrato", "consejos.pdf")
                        #with open(consejos_file, "rb") as f:
                        #    file_content = f.read()

                        #file2 = {
                        #    "name": "Consejos para el Adoptante.pdf",
                        #    "content": file_content,
                        #    "content_type": "application/pdf",
                        #}

                        def _send_persona_email():
                            send_html_email(subject, content, settings.SEND_MAIL, [contrato.adoptante.persona_email], file=[file]) #file2])

                    t = Thread(target=_send_persona_email)
                    t.start()

                    if gato:
                        if not gato.fecha_adopcion:
                            gato.fecha_adopcion = timezone.now()

                        gato.estado = "A"
                        gato.save()

                        if not gato.estado_formulario:
                            gato.estado_formulario = estado_form
                            gato.adoptante = contrato.adoptante.persona_nombre
                            gato.save()

                    estado_form.estado = "A"
                    estado_form.save()
            else:
                post_context["errors"] = "{}".format(contrato_form.errors)
                post_context["status"] = "fail"

            return HttpResponse(json.dumps(post_context))

    def get(self, *args, **kwargs):

        return self.req(**kwargs)

    def post(self, *args, **kwargs):

        return self.req(is_post=True, **kwargs)


class EditPersonaView(EditView):

    url = r"^contrato/(?P<contrato_hash>.+)/$"
    template_name = "contrato/edit.html"
    is_persona = True


class DownloadView(TemplateView):

    url = r"^contrato_adopcion/download/$"

    def get(self, *args, **kwargs):

        contrato_file = os.path.join(settings.STATICFILES_DIRS[0], "contrato", "contrato.pdf")
        with open(contrato_file, "rb") as f:
            response = HttpResponse(f, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename=contrato_adopcion_responsable_felis_catus_vacio.pdf'

        return response


class DownloadContractView(LoginRequiredMixin, TemplateView):

    url = [r"^contrato_adopcion/(?P<contrato_id>(\d+))/download/$"]

    def get(self, *args, **kwargs):

        contrato = Contrato.objects.filter(id=self.kwargs.get("contrato_id")).first()
        if contrato is None:
            return HttpResponse("No se encontró el contrato.")

        #el PDF tiene nombre, DNI, dirección y teléfono del adoptante: solo el equipo
        #y el rescatista del animal. Los ids son correlativos.
        if not puede_editar_animal(self.request.user, contrato.gato):
            raise PermissionDenied("Este contrato es de otra persona.")

        return contrato_pdf_response(contrato)


class ContratoPdfView(TemplateView):

    url = r"^contrato_adopcion/pdf/(?P<token>[^/]+)/$"

    def get(self, *args, **kwargs):

        try:
            contrato_hash = contrato_hash_del_link(self.kwargs.get("token"))
        except signing.BadSignature:
            raise Http404("Este link no es válido o ya venció.")

        return contrato_pdf_response(get_object_or_404(Contrato, hash=contrato_hash))


class DatosView(LoginRequiredMixin, TemplateView):
    """La vieja pantalla de "Datos Adopción": ahora manda a la del contrato.

    Nunca tuvo template en el repo (contrato/datos.html no está ni en el commit inicial),
    así que abrirla daba siempre 500 TemplateDoesNotExist. El único link a esta URL salía
    de /formslist/, que tampoco funcionaba y se borró. Lo que juntaba está todo en la
    pantalla del contrato: los datos del animal en su formulario y los del adoptante en el
    PDF que se descarga desde ahí. Un link viejo lleva ahí en vez de a un error.
    """

    url = [r"^formulario/(?P<estado_id>(\d+))/datos/$"]

    def get(self, *args, **kwargs):

        estado_form = get_object_or_404(EstadoFormulario, id=self.kwargs.get("estado_id"))

        #el mismo chequeo que el contrato, antes de mandar ahí: con ids correlativos, a
        #quien no es el rescatista ni del equipo se le corta acá, no del otro lado
        if not puede_editar_animal(self.request.user, estado_form.gato):
            raise PermissionDenied("Este formulario es de otra persona.")

        return redirect("/formulario/{}/contrato/".format(estado_form.id))
