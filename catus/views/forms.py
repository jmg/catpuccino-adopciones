from catus.models import EstadoFormulario
from catus.forms import EstadoFormularioForm
from catus.utils import *
from catus.services.adoption import AdoptionService

from django.shortcuts import get_object_or_404
from catus.views.home import BaseView
from catus.views.base import puede_editar_animal


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

        #a qué animal apuntaba ANTES de que el form toque la instancia: is_valid() corre
        #_post_clean, que ya le escribe encima los valores del POST, así que después de
        #esa línea estado_form.gato ya es el que mandó el atacante y no queda con qué
        #comparar
        gato_original_id = estado_form.gato_id

        estado_form_form = EstadoFormularioForm(datos, instance=estado_form)

        #save() sin is_valid() levanta ValueError con cualquier dato raro: 500 en vez
        #de un mensaje
        if not estado_form_form.is_valid():
            return self.json_response({"status": "error", "errores": estado_form_form.errors})

        #El form expone 'gato' sobre TODOS los animales, así que el POST puede reapuntar
        #el formulario al animal de otra persona. El chequeo estaba más abajo, cuidando
        #la escritura del estado, y para entonces el save() ya había dejado el formulario
        #colgado del animal ajeno: no le cambiaba el estado, pero la postulación quedaba
        #pegada ahí, y desde ahí sigue el contrato. Acá se mira antes de guardar nada.
        gato_destino = estado_form_form.cleaned_data.get("gato")

        if gato_destino is not None and gato_destino.id != gato_original_id:
            if not puede_editar_animal(self.request.user, gato_destino):
                return self.json_response({
                    "status": "error",
                    "error": "Ese animal lo cargó otra persona: no podés mover el formulario a su publicación.",
                })

        estado_form_form.save()

        #el estado del candidato arrastra al del animal: si alguien lo reservó o lo adoptó,
        #tiene que dejar de figurar en adopción en el sitio público
        estados_del_animal = {"R": "R", "A": "A"}

        nuevo_estado = estados_del_animal.get(estado_form.estado)
        gato = estado_form.gato

        if nuevo_estado and gato and gato.get_estado() != nuevo_estado:

            #acá se entra con solo conocer el hash, y un hash se consigue solo: te registrás,
            #cargás un animal y completás el formulario público de tu propio animal. Con eso
            #se marcaba "adoptado" cualquier animal del sitio, que es como se lo saca del
            #listado público. El animal lo toca su rescatista o el equipo, nadie más.
            if not puede_editar_animal(self.request.user, gato):
                return self.json_response({
                    "status": "error",
                    "error": "Este animal lo cargó otra persona: no podés cambiarle el estado.",
                })

            gato.set_estado(nuevo_estado)
            gato.save()

        return self.json_response({"status": "ok", "estado": estado_form.estado})



