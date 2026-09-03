from catus.models import EstadoFormulario
from catus.forms import EstadoFormularioForm
from catus.utils import *
from catus.services.adoption import AdoptionService

from django.shortcuts import get_object_or_404
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

        datos = self.request.POST.copy()

        #'gato' es opcional en el form: si el POST no lo trae (por ejemplo cuando solo
        #se manda el select de estado), guardar lo dejaba en None y el formulario perdía
        #el vínculo con el animal, en silencio
        if "gato" not in datos:
            datos["gato"] = estado_form.gato_id or ""

        estado_form_form = EstadoFormularioForm(datos, instance=estado_form)

        #save() sin is_valid() levanta ValueError con cualquier dato raro: 500 en vez
        #de un mensaje
        if not estado_form_form.is_valid():
            return self.json_response({"status": "error", "errores": estado_form_form.errors})

        estado_form_form.save()

        #el estado del candidato arrastra al del animal: si alguien lo reservó o lo adoptó,
        #tiene que dejar de figurar en adopción en el sitio público
        estados_del_animal = {"R": "R", "A": "A"}

        nuevo_estado = estados_del_animal.get(estado_form.estado)
        gato = estado_form.gato

        if nuevo_estado and gato and gato.get_estado() != nuevo_estado:
            gato.set_estado(nuevo_estado)
            gato.save()

        return self.json_response({"status": "ok", "estado": estado_form.estado})



