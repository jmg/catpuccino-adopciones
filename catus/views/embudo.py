from django.http import HttpResponse, HttpResponseNotAllowed

from catus.services import embudo, throttle
from catus.views.base import BaseView

#Un navegador manda a lo sumo cinco pasos por especie y pestaña; más que esto desde una
#misma conexión es alguien inflando los números.
PASOS_MAX_POR_HORA = 120


class PasoFormularioView(BaseView):
    """Recibe un paso del formulario de pre-adopción (services/embudo.py). Contesta 204
    siempre: al navegador no le importa, y no hay nada que mostrarle."""

    url = r"^pre-adopcion/paso/$"

    def get(self, *args, **kwargs):
        return HttpResponseNotAllowed(["POST"])

    def post(self, *args, **kwargs):
        paso = self.request.POST.get("paso")
        especie = self.request.POST.get("especie")
        if paso in embudo.PASOS_DEL_NAVEGADOR and especie in ("G", "P"):
            quien = throttle.client_ip(self.request)
            if not quien or throttle.hit("paso-formulario", quien, 60 * 60) <= PASOS_MAX_POR_HORA:
                embudo.contar(especie, paso)
        return HttpResponse(status=204)


class EmbudoView(BaseView):
    """/tools/embudo/: cuántos abren el formulario de pre-adopción y hasta dónde llegan."""

    url = r"^tools/embudo/$"
    template_name = "tools/embudo.html"

    def get(self, *args, **kwargs):
        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")
        try:
            dias = min(max(int(self.request.GET.get("dias", 30)), 1), 365)
        except ValueError:
            dias = 30
        return self.render_to_response({"especies": embudo.resumen(dias), "dias": dias})
