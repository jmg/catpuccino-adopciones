import logging

from django.shortcuts import redirect

from catus.services import postulacion, throttle
from catus.services.buenadoptante import BuenAdoptanteService
#el módulo y no sus clases: django-conventions registra como vista toda clase que
#encuentra en cada módulo de views/, también las importadas
from catus.views import adoption
from catus.views.home import BaseView

logger = logging.getLogger(__name__)


class PostularseView(BaseView):
    """Postularse a otro animal con las respuestas de un formulario ya enviado.

    Abierta, sin cuenta: la abre quien tiene el link privado que recibió al mandar su
    formulario (services/postulacion.py explica el token). Por eso la página no muestra nada
    de lo que la persona contestó, ni su mail ni su celular: solo su nombre de pila y a qué
    animales se postuló. Un link reenviado o filtrado no entrega el formulario.

    Va en dos pasos, sin JS: elegir un animal de la lista (?id=) y confirmar. Postularse le
    manda los datos de la persona a otro rescatista, y eso no se deshace.
    """

    url = r"^postularme/(?P<token>[^/]+)/$"
    template_name = "postulacion/postularse.html"

    def render_to_response(self, context):

        return self.pagina(context.get("token"))

    def post(self, request, *args, **kwargs):

        token = kwargs.get("token")
        original = postulacion.formulario_del_token(token)
        if original is None:
            return self.pagina(token)

        #el mismo tope por conexión que el formulario público: esto también crea uno
        quien = throttle.client_ip(request)
        if quien and throttle.hit("adoption-form", quien, 60 * 60) > adoption.FORM_MAX_PER_HOUR:
            return self.pagina(token, error="Recibimos demasiados formularios desde tu conexión. Probá de nuevo en una hora.")

        try:
            nuevo = postulacion.postular(original, request.POST.get("animal_id"))
        except postulacion.NoSePuede as motivo:
            return self.pagina(token, error=str(motivo))

        #desde acá, lo mismo que con un formulario recién completado (PreAdoptionView.post):
        #BuenAdoptante antes de que le llegue a nadie, y después los mails
        vista = adoption.PreAdoptionPerrosView() if nuevo.tipo == "AP" else adoption.PreAdoptionView()
        vista.request = request

        servicio = BuenAdoptanteService()
        actividad = servicio.registrar_solicitud(nuevo)
        if actividad is not None and actividad.bloqueo:
            nuevo.estado = "B"
            nuevo.save(update_fields=["estado"])
            vista.avisar_bloqueo(nuevo, actividad, nuevo.gato)
            #el link deja de servir (formulario_del_token): no se dice por qué
            return self.pagina(token)
        servicio.avisar_coincidencia(actividad)

        vista.send_email(nuevo.form_entry, None, nuevo.gato, nuevo)

        #redirigir: recargar la página no vuelve a postular
        return redirect("/postularme/{}/?ok={}".format(token, nuevo.gato_id))

    def pagina(self, token, error=None):

        original = postulacion.formulario_del_token(token)
        if original is None:
            respuesta = BaseView.render_to_response(self, {"vencido": True, "vigencia_dias": postulacion.VIGENCIA_DIAS})
            respuesta.status_code = 404
            return respuesta

        anteriores = [p for p in postulacion.postulaciones(original) if p.gato is not None]
        disponibles = list(postulacion.animales_disponibles(original))
        cupo = postulacion.cupo(original)

        #sexo · edad · zona, sin lo que no se sabe
        for animal in disponibles:
            sexo = animal.get_sexo_display() if animal.sexo != "D" else ""
            animal.datos_cortos = " · ".join(dato for dato in (sexo, animal.edad, animal.zona) if dato)

        def numero(nombre):
            try:
                return int(self.request.GET.get(nombre))
            except (TypeError, ValueError):
                return None

        #?id=: el animal que eligió de la lista (o el de la ficha desde la que llegó)
        elegido_id = numero("id")
        elegido = next((animal for animal in disponibles if animal.id == elegido_id), None)
        ya_postulado = next((p.gato for p in anteriores if p.gato_id == elegido_id), None) if elegido is None else None

        #?ok=: a quién se acaba de postular
        recien = next((p.gato for p in anteriores if p.gato_id == numero("ok") and p.copiado_de_id), None)

        return BaseView.render_to_response(self, {
            "token": token,
            "nombre": (original.persona_nombre or "").split(" ")[0],
            "especie": "perro" if original.tipo == "AP" else "gato",
            "anteriores": anteriores,
            "animales": [animal for animal in disponibles if animal is not elegido],
            "elegido": elegido,
            "ya_postulado": ya_postulado,
            "recien": recien,
            "cupo": cupo,
            "maximo": postulacion.MAX_POR_DIA,
            "error": error,
        })
