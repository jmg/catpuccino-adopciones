from catus.models import EstadoFormulario
from catus.forms import EstadoFormularioForm
from catus.utils import *
from catus.services.adoption import AdoptionService

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from catus.views.home import BaseView
from catus.views.base import puede_editar_animal


class FormView(LoginRequiredMixin, BaseView):
    """Un formulario de pre-adopción: celular, email, dirección y respuestas del candidato.

    El link con el hash lo reciben por mail el equipo y quien cargó el animal (el
    adoptante no lo recibe nunca: su mail de "Formulario Recibido" no lo trae), y es el
    mismo que abre el listado de /accounts/profile/. Así que es del equipo y del
    rescatista, los dos con cuenta: estaba abierto a cualquiera que tuviera el hash, y
    /formslist/ los entregaba todos.
    """

    url = r"^formularios/(?P<form_hash>.+)/$"

    def get_estado_form(self, form_hash):

        estado_form = get_object_or_404(EstadoFormulario, hash=form_hash)

        #el registro es abierto: con solo tener cuenta no alcanza, es de quien cargó el
        #animal (o del equipo), con el mismo criterio que el contrato
        if not puede_editar_animal(self.request.user, estado_form.gato):
            raise PermissionDenied("Este formulario es de otra persona.")

        return estado_form

    def get(self, *args, **kwargs):

        form_hash = kwargs.get("form_hash")
        estado_form = self.get_estado_form(form_hash)

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
        estado_form = self.get_estado_form(form_hash)

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
        #el formulario al animal de otra persona. Acá se mira antes de guardar nada.
        gato_destino = estado_form_form.cleaned_data.get("gato")

        if gato_destino is not None and gato_destino.id != gato_original_id:
            if not puede_editar_animal(self.request.user, gato_destino):
                return self.json_response({
                    "status": "error",
                    "error": "Ese animal lo cargó otra persona: no podés mover el formulario a su publicación.",
                })

        estado_form_form.save()

        #el estado del candidato arrastra al del animal: si alguien lo reservó o lo adoptó,
        #tiene que dejar de figurar en adopción en el sitio público. Antes se leía
        #animal.reservado, un campo que no existe, y marcar "Reservado" era un 500.
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


#FormsView (/formularios/) y ListView (/formslist/) se sacaron, como en master: nunca
#funcionaron (ListView llama a get_gato(), miembro y render_comments(), que este modelo
#no tiene, y FormsView no tiene template) y nada las enlaza; el listado real es
#/accounts/profile/#forms. Pero /formslist/ no pedía login, y aunque las filas daban
#500, con length=0 devolvía el total y su búsqueda filtraba por nombres de campo que
#manda el navegador: se podía adivinar cualquier dato de la base de a una letra.
