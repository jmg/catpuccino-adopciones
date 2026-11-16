from catus.models import ActividadBuenAdoptante, EstadoFormulario
from catus.services import aviso_candidatos, estados
from catus.services.buenadoptante import CALIFICACIONES, BuenAdoptanteService, descripcion_alerta, descripcion_marca
from catus.forms import EstadoFormularioForm
from catus.utils import *
from catus.services.adoption import AdoptionService
from catus.services.contacto import contacto
from catus.services.historial import adopciones_anteriores

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from catus.views.home import BaseView
from catus.views.base import puede_editar_animal


#Lo que el rescatista puede elegir para un candidato (B y U son del equipo).
ESTADOS_DEL_RESCATISTA = ("N", "P", "R", "A", "D", "T")


def botones_de_estado(estado_form, usuario):
    """Los botones de "¿En qué quedó?" de /formularios/<hash>/: (estado, texto, primario,
    confirmación). El mail al rescatista prometía "desde el sitio podés cambiarle el
    estado" y la página no tenía cómo: el 99,8% de los formularios quedaba "No asignado".
    """

    actual = estado_form.estado
    animal = estado_form.gato
    nombre = animal.nombre if animal else "el animal"

    if actual == "B":
        if usuario.is_superuser:
            return [("N", "Liberarlo: pasarlo a «No asignado»", True, "")]
        return []

    if estado_form.tipo in ("T", "TP"):
        opciones = [
            ("P", "Ya lo contacté", False, ""),
            ("T", "Está transitando", True, ""),
            ("D", "Descartar", False, ""),
        ]
    else:
        opciones = [
            ("P", "Ya lo contacté", False, ""),
            ("R", "Reservar para esta persona", False,
             "{} va a dejar de verse en el sitio como disponible.".format(nombre) if animal else ""),
            #"Adoptó" no manda nada: lleva al paso de confirmación (?confirmar=adopcion), que
            #pregunta si avisarles a los demás que se postularon
            ("A", "Adoptó", True, ""),
            ("D", "Descartar", False, ""),
        ]

    botones = [boton for boton in opciones if boton[0] != actual]
    #deshacer un "Ya lo contacté" o un "Descartar" tocado sin querer
    if actual in ("P", "D"):
        botones.append(("N", "Volver a «No asignado»", False, ""))
    return botones


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

        #frenado por BuenAdoptante: lo revisa el equipo, que si lo libera lo pasa de estado
        if estado_form.estado == "B" and not self.request.user.is_superuser:
            raise PermissionDenied("Este formulario lo está revisando el equipo.")

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
            "botones_estado": botones_de_estado(estado_form, self.request.user),
            "estado_cambiado": self.request.GET.get("hecho"),
            "confirmar_adopcion": self.confirmar_adopcion(estado_form),
            "estado_form_form": estado_form_form,
            "estado_form": estado_form,
            "estado_formulario": estado_form,
            "persona_nombre": persona_nombre,
            "gato_nombre": gato_nombre,
            "data_attrs": data_attrs,
            "form_attrs": form_attrs,
            "form_hash": form_hash,
            "contacto": self.contacto(data_attrs),
            "buenadoptante": self.buenadoptante(estado_form),
            "adopciones_anteriores": adopciones_anteriores(estado_form),
            #"extra_forms": extra_forms,
        })

    def contacto(self, data_attrs):
        """Los links de WhatsApp, llamada y mail del candidato, para los botones de arriba
        del formulario: el celular y el mail estaban perdidos entre cuarenta respuestas y
        había que copiarlos a mano."""

        respuestas = {}
        for label, value in data_attrs or []:
            respuestas.setdefault(str(label).strip().lower(), value)

        return contacto(respuestas.get("celular"), respuestas.get("email"))

    def buenadoptante(self, estado_form):
        """Lo que dijo BuenAdoptante de esta persona, para el recuadro del formulario, o None.

        Solo cuando hay algo que mirar: una calificación, o una alerta aunque nadie la haya
        calificado. "Sin calificar", "todavía no contestó" o "no se pudo consultar" no le dicen
        nada al rescatista, así que no se muestra el recuadro (pedido del equipo).
        """

        actividad = ActividadBuenAdoptante.objects.filter(estado_formulario=estado_form, tipo="adoption_request").first()
        if actividad is None or actividad.estado != "OK":
            return None

        alertas = [descripcion_alerta(a) for a in actividad.get_alertas()]
        if not actividad.nivel and not alertas:
            return None

        return {
            "nivel": actividad.nivel,
            "calificacion": CALIFICACIONES.get(actividad.nivel, "Sin dato"),
            "mala": BuenAdoptanteService().bloquea(actividad.nivel),
            "alertas": alertas,
            "marcas": [descripcion_marca(m) for m in actividad.get_marcas()],
            "perfil_url": actividad.perfil_url,
        }

    def confirmar_adopcion(self, estado_form):
        """El paso de "Adoptó": a quién y a cuántos más se les avisaría, o None si no se pidió.

        Marcar "Adoptado" puede terminar en mails a los demás que se postularon
        (services/aviso_candidatos.py): el rescatista lo ve antes y elige, con la casilla
        marcada de entrada. Si nadie más se postuló, no hay casilla."""

        if self.request.GET.get("confirmar") != "adopcion" or estado_form.estado == "A":
            return None
        if not any(boton[0] == "A" for boton in botones_de_estado(estado_form, self.request.user)):
            return None

        animal = estado_form.gato
        return {
            "nombre": animal.nombre if animal else "el animal",
            "otros": aviso_candidatos.candidatos(animal, sin=estado_form.id) if animal else 0,
            "especie": "perros" if animal is not None and animal.tipo == "P" else "gatos",
        }

    def post(self, *args, **kwargs):

        form_hash = kwargs.get("form_hash")
        estado_form = self.get_estado_form(form_hash)

        datos = self.request.POST.copy()

        #los botones de "¿En qué quedó?" mandan un formulario común (anda sin JS): a esos
        #se les contesta volviendo a la página, al resto (AJAX) con JSON como siempre
        self._volver_a = "/formularios/{}/".format(estado_form.hash) if datos.get("volver") else None

        #"Bloqueado por BuenAdoptante" y "Duplicado" son del equipo: un rescatista que se
        #bloqueaba un formulario a sí mismo dejaba de poder abrirlo
        permitidos = set(ESTADOS_DEL_RESCATISTA) | ({"B", "U"} if self.request.user.is_superuser else set())
        if "estado" in datos and datos.get("estado") not in permitidos:
            return self.json_response({"status": "error", "error": "Ese estado no se puede elegir."})

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

            #por el mismo camino que el panel y la edición (services/estados.py)
            if nuevo_estado == "R":
                estados.reservar(gato)
            elif gato.estado_formulario_id:
                estados.marcar_adoptado(gato, avisar=self.avisar())
            else:
                #este formulario es el de quien lo adoptó: queda vinculado y va a BuenAdoptante
                estados.marcar_adoptado(gato, formulario=estado_form, avisar=self.avisar())
                return self.json_response({"status": "ok", "estado": estado_form.estado})

        #el rescatista dice que esta persona adoptó: el animal queda vinculado a su
        #formulario y la adopción va a BuenAdoptante (la manda el cron)
        if estado_form.estado == "A" and gato and gato.get_estado() == "A" and puede_editar_animal(self.request.user, gato):
            if not gato.estado_formulario_id:
                gato.estado_formulario = estado_form
                gato.adoptante = (estado_form.get_persona() or "")[:255] or None
                gato.save(update_fields=["estado_formulario", "adoptante"])
            #ya estaba adoptado (desde la edición, o el mail de expiración) y ahora pasó por el
            #paso de "Adoptó": vale lo que eligió en la casilla
            if self.request.POST.get("confirmo_adopcion") == "1":
                gato.avisar_candidatos = self.avisar()
                gato.save(update_fields=["avisar_candidatos"])
            BuenAdoptanteService().registrar_adopcion(estado_form, gato)

        return self.json_response({"status": "ok", "estado": estado_form.estado})

    def avisar(self):
        """La casilla del paso de "Adoptó": True si la dejó marcada. Un POST sin ese paso (el
        AJAX de antes, una pestaña vieja) no avisa a nadie."""

        return self.request.POST.get("avisar_candidatos") == "1"

    def json_response(self, data):
        """JSON para los pedidos AJAX; para los botones de la página, volver a ella con un
        aviso de cómo salió (?hecho=<estado> o ?hecho=error)."""

        volver_a = getattr(self, "_volver_a", None)
        if volver_a:
            hecho = data.get("estado") if data.get("status") == "ok" else "error"
            return self.redirect("{}?hecho={}".format(volver_a, hecho))
        return super().json_response(data)


#FormsView (/formularios/) y ListView (/formslist/) se sacaron, como en master: nunca
#funcionaron (ListView llama a get_gato(), miembro y render_comments(), que este modelo
#no tiene, y FormsView no tiene template) y nada las enlaza; el listado real es
#/accounts/profile/#forms. Pero /formslist/ no pedía login, y aunque las filas daban
#500, con length=0 devolvía el total y su búsqueda filtraba por nombres de campo que
#manda el navegador: se podía adivinar cualquier dato de la base de a una letra.
