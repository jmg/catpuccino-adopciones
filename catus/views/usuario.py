import random
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, render
from django.views.generic import TemplateView
from catus.forms import CatusUserForm
from catus.models import Animal, CatusUser
from django.http import Http404, HttpResponse
from catus.utils import get_context_columns, send_html_email
from django.conf import settings
import requests
from django.contrib.auth.mixins import LoginRequiredMixin
from .base import BaseView, SoloPostMixin


def get_user_por_handle(handle):
    """La cuenta que se muestra en /<handle>/, aunque haya varias con ese handle.

    Antes de que se validara el handle quedaron cuentas que lo comparten, y con
    get_object_or_404 esa URL daba 500 para todas ellas. Sin tocar los datos, mostramos
    siempre la misma, la que más probablemente busca quien entra por ese link:

      1. la que tiene más animales en adopción (aprobados y en estado D), que es lo
         que muestra la página y lo que busca quien llega desde el mail de aprobación;
      2. la que más animales cargó en total: una cuenta con historia, no una vacía
         que quedó de registrarse dos veces;
      3. la que entró más recientemente (las que nunca entraron, al final);
      4. la más vieja (menor id): los repetidos salieron de registros posteriores que
         no rechequeaban el handle, así que la primera es la que lo tenía.

    Se compara con handle= igual que ValidationService.esta_libre, que es lo que
    decide si un handle está ocupado. En MySQL, con las collations *_ci que trae
    utf8mb4 por defecto, eso no distingue mayúsculas: /Refugio/ y /refugio/ son el
    mismo perfil y entran en el mismo desempate; en sqlite sí las distingue. Con un
    solo resultado es la misma cuenta que devolvía el get(); sin ninguno, 404 como antes.
    """

    catus_user = CatusUser.objects.filter(handle=handle).annotate(
        animales_en_adopcion=Count("animal", filter=Q(animal__aprobado=True, animal__estado="D")),
        animales_cargados=Count("animal"),
    ).order_by(
        "-animales_en_adopcion", "-animales_cargados", F("last_login").desc(nulls_last=True), "id",
    ).first()

    if catus_user is None:
        raise Http404("No hay ninguna cuenta con ese handle.")

    return catus_user


class AnimalesView(BaseView):

    #solo números: con .+ un id de texto llegaba a get_object_or_404 y daba 500
    url = r"^usuario/(?P<user_id>\d+)/animales/$"

    def render_to_response(self, context):

        if "user_id" in context:
            catus_user = get_object_or_404(CatusUser, id=context["user_id"])
        else:
            catus_user = get_user_por_handle(context["handle"])

        context["animals"] = Animal.get_all_for_adoption(destacado=True, extra_filters={"cargado_por": catus_user}, sort="-fecha_ingreso")

        context["cols"] = get_context_columns(context["animals"])
        context["user"] = catus_user
        context["is_user"] = True
        context["perros_en_adopcion"] = bool([animal for animal in context["animals"] if animal.tipo == "P"])
        context["SSL_HOST"] = settings.SSL_HOST

        return BaseView.render_to_response(self, context)


class ProfileView(AnimalesView):

    url = [r"^(?P<handle>\w+)/$", r"^(?P<handle>\w+)$"]
    template_name = "usuario/animales.html"


class SaveView(SoloPostMixin, LoginRequiredMixin, BaseView):

    #Solo recibe un POST, y de alguien logueado. Sin SoloPostMixin un GET (alguien que
    #recarga o abre el link) buscaba usuario/save.html, que no existe, y daba 500; sin el
    #login, un POST anónimo armaba el form con AnonymousUser y también daba 500.
    #Sin "next": volver acá después del login es un GET, que da 405; mejor al perfil.
    redirect_field_name = None

    def post(self, *args, **kwargs):

        catus_user_form = CatusUserForm(self.request.POST, instance=self.request.user)

        if catus_user_form.is_valid():
            catus_user_form.save()
            self.request.session["usuario_save_success"] = True
        else:
            self.request.session["usuario_save_error"] = str(catus_user_form.errors)

        return self.redirect(settings.LOGIN_REDIRECT_URL)
