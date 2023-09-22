import json
import uuid
import os.path
from django.views.generic import TemplateView
from django.http import HttpResponse

from catus.models import Contrato, Animal, EstadoFormulario, ContratoPersona
from catus.forms import ContratoPersonaForm
from catus.services.adoption import AdoptionService
from catus.services.contrato import *
from catus.utils import send_html_email

from django.conf import settings
from django.utils import timezone
from django.contrib.auth.mixins import LoginRequiredMixin
from threading import Thread

from catus.forms import ContratoForm


class EditView(TemplateView):

    url = [r"^formulario/(?P<estado_id>(\d*))/contrato/$"]
    is_persona = False

    def req(self, is_post=False, **kwargs):

        context = {}
        context["is_persona"] = self.is_persona
        gato = None

        if not self.is_persona:
            estado_form = EstadoFormulario.objects.get(id=self.kwargs.get("estado_id"))
            try:
                contrato = Contrato.objects.get(estado_formulario=estado_form)
            except:
                contrato = None
        else:
            contrato = Contrato.objects.get(hash=self.kwargs.get("contrato_hash"))
            estado_form = contrato.estado_formulario

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
                    #enviar mail al adoptante

                    email = self.request.POST.get("email")
                    subject = self.request.POST.get("subject")
                    content = self.request.POST.get("content")

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

    url = [r"^contrato_adopcion/(?P<contrato_id>(\d*))/download/$"]

    def get(self, *args, **kwargs):

        contrato = Contrato.objects.get(id=self.kwargs.get("contrato_id"))
        contrato_file = os.path.join(
            settings.STATICFILES_DIRS[0],
            "contrato",
            contrato.hash,
            "contrato_adopcion_responsable_felis_catus_completado.pdf"
        )

        with open(contrato_file, "rb") as f:
            response = HttpResponse(f, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename=contrato_adopcion_responsable_felis_catus_vacio.pdf'

        return response


class DatosView(LoginRequiredMixin, TemplateView):

    url = [r"^formulario/(?P<estado_id>(\d*))/datos/$"]

    def _format_date(self, date):

        if date:
            return date.strftime("%d/%m/%Y")

        return ""

    def get(self, *args, **kwargs):

        estado_form = EstadoFormulario.objects.get(id=self.kwargs.get("estado_id"))
        contrato = Contrato.objects.get(estado_formulario=estado_form)
        gato = estado_form.gato

        data_attrs = AdoptionService().get_form_attrs(estado_form.form_entry, ["Nombre y Apellido", "Edad", "Profesión",
            "Celular", "Email", "Partido", "Localidad", "Facebook", "Instagram"], exact=True, convert_to_str=True)

        data_attrs = dict(data_attrs)
        data_attrs["DNI"] = contrato.adoptante.persona_dni
        #data_attrs["Ocupacion"] = contrato.adoptante.persona_ocupacion

        cat_attrs = {
            "Nombre": gato.nombre,
            "Color": contrato.gato_color,
            "Sexo": gato.get_sexo_display(),
            "Fecha nacimiento": self._format_date(contrato.gato_fecha_nacimiento),
            "Fecha ingreso a las web de FC": self._format_date(gato.created_at),
            "Fecha adopción": self._format_date(contrato.contrato_fecha),
            "Fecha castración": self._format_date(contrato.gato_castrado_fecha) if contrato.gato_castrado else "NO",
            "Fecha vacunacion triple 1era dosis": self._format_date(contrato.gato_vacunacion_triple_1_dosis_fecha) if contrato.gato_vacunacion_triple_1_dosis else "NO",
            "Fecha vacunacion triple 2nda dosis": self._format_date(contrato.gato_vacunacion_triple_2_dosis_fecha) if contrato.gato_vacunacion_triple_2_dosis else "NO",
            "Fecha desparasitación": self._format_date(contrato.gato_desparasitado_fecha) if contrato.gato_desparasitado else "NO",
            "Fecha desparasitación 2nda dosis": self._format_date(contrato.gato_desparasitado_fecha_2) if contrato.gato_desparasitado_2 else "NO",
            "Fecha pipeta antipulgas": self._format_date(contrato.gato_pipeta_antipulgas_fecha) if contrato.gato_pipeta_antipulgas else "NO",
            "Alimento": contrato.gato_alimento,
            "Cuidados especiales": contrato.gato_cuidados_especiales,
        }

        link_contrato = "/contrato_adopcion/{}/download/".format(contrato.id)

        data = {
            "contrato": contrato,
            "estado_form": estado_form,
            "gato": gato,
            "data_attrs": data_attrs,
            "cat_attrs": cat_attrs,
            "miembro": contrato.miembro_felis_catus_nombre,
            "link_contrato": link_contrato
        }

        return self.render_to_response(data)
