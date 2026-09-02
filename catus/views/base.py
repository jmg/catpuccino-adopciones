import json
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib.auth.mixins import UserPassesTestMixin
from catus.models import Animal
from django.http import HttpResponse
from catus.services.utils.render import render
from catus.services.base import BaseService


def puede_editar_animal(user, animal):
    """Un animal lo maneja quien lo cargó, o alguien del equipo de Catpuccino."""

    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return animal is not None and animal.cargado_por_id == user.id


class SuperuserRequiredMixin(UserPassesTestMixin):
    """Para acciones del equipo: aprobar animales, comentar, publicar en redes."""

    def test_func(self):

        return self.request.user.is_authenticated and self.request.user.is_superuser


class BaseView(TemplateView):

    def render_to_response(self, context):

        return TemplateView.render_to_response(self, context)

    def json_response(self, data):

        return HttpResponse(json.dumps(data))

    def render(self, template, data):

        return render(template, data)

    def response(self, text):

        return HttpResponse(text)

    def redirect(self, url):

        return redirect(url)

    def render(self, template, context):

        return BaseService().render(template, context)

    def get_current_user(self):

        return self.request.user



class LoginRequiredView(BaseView):

    login_exempt = False