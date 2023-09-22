from catus.services.base import BaseService

from catus.models import EstadoFormulario
from catus.forms import EstadoFormularioForm
from catus.utils import *
from catus.services.adoption import AdoptionService

from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from catus.views.home import BaseView


class FormView(BaseView):

    url = r"^formularios/(?P<form_hash>.+)/$"

    def get(self, *args, **kwargs):

        form_hash = kwargs.get("form_hash")
        estado_form = get_object_or_404(EstadoFormulario, hash=form_hash)

        estado_form_form = EstadoFormularioForm(instance=estado_form)
        persona_nombre = AdoptionService().get_form_attr(estado_form.form_entry, "Nombre y Apellido")
        gato_nombre = AdoptionService().get_animal(estado_form.form_entry)
        animal = AdoptionService().get_animal_obj(estado_form.form_entry)

        data_attrs = AdoptionService().get_form_attrs(estado_form.form_entry, ["Nombre y Apellido", "Edad", "Profesión",
            "Celular", "Email", "Direccion", "Partido", "Localidad", "Facebook", "Instagram"], exact=True, convert_to_str=True)

        form_fields = []
        if estado_form.form_entry is not None:
            if estado_form.tipo in ["A", "AP"]:
                form_fields = estado_form.form_entry.fields.all()[1:]
            else:
                form_fields = estado_form.form_entry.fields.all()

        form_attrs = AdoptionService().get_formatted_fields(form_fields, photos_html=True)
        if animal:
            extra_forms = EstadoFormulario.objects.filter(gato=animal).exclude(id=estado_form.id)
        else:
            extra_forms = []

        return self.render_to_response({
            "estado_form_form": estado_form_form,
            "estado_form": estado_form,
            "estado_formulario": estado_form,
            "persona_nombre": persona_nombre,
            "gato_nombre": gato_nombre,
            "data_attrs": data_attrs,
            "form_attrs": form_attrs,
            "form_hash": form_hash,
            #"extra_forms": extra_forms,
        })

    def post(self, *args, **kwargs):

        form_hash = kwargs.get("form_hash")
        estado_form = get_object_or_404(EstadoFormulario, hash=form_hash)

        estado_form_form = EstadoFormularioForm(self.request.POST, instance=estado_form)
        estado_form_form.save()

        if estado_form.estado == "R":
            gato = estado_form.gato
            if gato and not gato.reservado:
                gato.reservado = True
                gato.save()

        elif estado_form.estado == "A":
            gato = estado_form.gato
            if gato and gato.fecha_adopcion is None:
                gato.fecha_adopcion = timezone.now()
                gato.save()

        return self.json_response({"status": "ok", "estado": estado_form.estado})


class FormsView(LoginRequiredMixin, BaseView):

    url = [r"^formularios/$", r"^formularios$"]

    def get(self, *args, **kwargs):

        forms = EstadoFormulario.objects.order_by("-fecha_ingreso")

        return self.render_to_response({
            "forms": forms,
            "is_forms_page": True,
        })


class ListView(BaseView):

    url = [r"^formslist/$", r"^formslist$"]

    def get(self, *args, **kwargs):

        def get_actions(estado_form):

            actions = ""
            if estado_form.estado == "R" or estado_form.estado == "A":
                actions = "<a href='/formulario/{}/contrato/'><i class='fa fa-id-badge'></i> Contrato Adopción</a>".format(estado_form.id)

            if estado_form.estado == "A":
                actions += "<hr><a href='/formulario/{}/datos/'><i class='fa fa-file'></i> Datos Adopción</a>".format(estado_form.id)

            return actions

        def get_gato(estado_form):

            gato = estado_form.get_gato()
            return gato.nombre if gato else ""

        columnIndexNameMap = {
            0: 'id',
            1: lambda estado_form: estado_form.get_fecha_ingreso(),
            2: lambda estado_form: "<a href='/formularios/{}/'>{}</a>".format(estado_form.hash, estado_form.get_persona()),
            3: get_gato,
            4: lambda estado_form: estado_form.miembro.nombre if estado_form.miembro else "",
            5: lambda estado_form: "<span class='badge badge-{}'>{}</span>".format(estado_form.get_estado_badge(), estado_form.get_estado_display()),
            6: lambda estado_form: estado_form.get_tipo_display(),
            7: lambda estado_form: estado_form.render_comments(),
            8: lambda estado_form: self.render("forms/puntaje.html", {"estado_form": estado_form }),
            9: lambda estado_form: "<a href='/formularios/{}/'><i class='fa fa-search'></i> Ver</a>".format(estado_form.hash),
            10: get_actions,
        }
        sortIndexNameMap = {
            0: 'id',
            1: 'fecha_ingreso',
            2: 'persona_nombre',
            3: 'gato__nombre',
            4: 'miembro__nombre',
            5: 'estado',
            6: 'tipo',
            7: None,
            8: None,
            9: None,
            10: None,
        }

        tipo = self.request.GET.get("type")
        querySet = None

        if tipo and tipo != "-":
            querySet = EstadoFormulario.objects.filter(tipo=tipo.upper())

        return BaseService().open_search(self.request, columnIndexNameMap, sortIndexNameMap, model=EstadoFormulario, querySet=querySet)


