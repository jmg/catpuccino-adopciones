import random
from django.shortcuts import get_object_or_404, render
from django.views.generic import TemplateView
from catus.forms import CatusUserForm
from catus.models import Animal, CatusUser
from django.http import HttpResponse
from catus.utils import get_context_columns, send_html_email
from django.conf import settings
import requests
from .base import BaseView


class AnimalesView(BaseView):

    url = r"^usuario/(?P<user_id>.+)/animales/$"

    def render_to_response(self, context):

        if "user_id" in context:
            catus_user = get_object_or_404(CatusUser, id=context["user_id"])
        else:
            catus_user = get_object_or_404(CatusUser, handle=context["handle"])

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


class SaveView(BaseView):

    def post(self, *args, **kwargs):

        catus_user_form = CatusUserForm(self.request.POST, instance=self.request.user)

        if catus_user_form.is_valid():
            catus_user_form.save()
            self.request.session["usuario_save_success"] = True
        else:
            self.request.session["usuario_save_error"] = str(catus_user_form.errors)

        return self.redirect(settings.LOGIN_REDIRECT_URL)
