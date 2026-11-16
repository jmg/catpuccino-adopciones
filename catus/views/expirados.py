from datetime import timedelta

from django.shortcuts import redirect
from django.utils import timezone

from catus.services import estados, expiracion
from catus.views.base import BaseView


class RespuestaView(BaseView):
    """Los botones del mail "¿Siguen en adopción?" (services/expiracion.py).

    Abierta, sin cuenta: el permiso es el token firmado del link, que lleva el animal, su
    rescatista y la expiración. Con GET solo muestra el animal y los dos botones, porque los
    escáneres de links de los correos (Gmail, los antivirus) abren cada link del mail: si el
    GET republicara, el animal volvería al sitio sin que nadie lo pidiera. La acción es un
    POST, con services/estados.py, igual que en el panel.

    No muestra nada de los formularios ni de los candidatos: el link puede terminar
    reenviado. Después de "Ya se adoptó" ofrece entrar al panel para decir quién lo adoptó.
    """

    url = r"^sigue-en-adopcion/(?P<token>[^/]+)/$"
    template_name = "expirados/respuesta.html"

    def render_to_response(self, context):

        return self.pagina(context.get("token"))

    def post(self, request, *args, **kwargs):

        token = kwargs.get("token")
        link = expiracion.leer(token)
        respuesta = request.POST.get("respuesta")

        #vencido, ya contestado o una respuesta que no existe: la página dice cómo quedó
        if link is None or not link.vigente or respuesta not in expiracion.RESPUESTAS:
            return self.pagina(token)

        if respuesta == expiracion.SIGUE:
            estados.republicar(link.animal)
        else:
            #la casilla "avisarles a quienes se postularon": sin marcar (o sin casilla) no se avisa
            estados.marcar_adoptado(link.animal, avisar=request.POST.get("avisar_candidatos") == "1")

        #redirigir: recargar la página no vuelve a mandar el POST
        return redirect("/sigue-en-adopcion/{}/?hecho={}".format(token, respuesta))

    def pagina(self, token):

        link = expiracion.leer(token)
        if link is None:
            respuesta = BaseView.render_to_response(self, {"invalido": True, "vigencia_dias": expiracion.VIGENCIA_DIAS})
            respuesta.status_code = 404
            return respuesta

        animal = link.animal
        foto = animal.get_images().first()
        hembra = animal.sexo == "H"

        #el botón que tocó en el mail va primero
        primero = self.request.GET.get("r")
        if primero not in expiracion.RESPUESTAS:
            primero = expiracion.SIGUE

        hecho = self.request.GET.get("hecho")

        return BaseView.render_to_response(self, {
            "token": token,
            "animal": animal,
            "foto": foto.image if foto is not None and foto.image else None,
            "vigente": link.vigente,
            "primero": primero,
            "recien_republicado": hecho == expiracion.SIGUE and animal.estado == estados.EN_ADOPCION,
            "recien_adoptado": hecho == expiracion.ADOPTADO and animal.estado == estados.ADOPTADO,
            "lo": "la" if hembra else "lo",
            "o": "a" if hembra else "o",
            #hasta cuándo se ve: si lo republica ahora, o desde que se republicó
            "visible_hasta": (timezone.now() if link.vigente else animal.fecha_ingreso or timezone.now())
            + timedelta(days=expiracion.DIAS_PUBLICADO),
        })
