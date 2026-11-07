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

    def handle_no_permission(self):
        """A quien ya está logueado le contestamos, no lo mandamos al login.

        En Django 2.0 AccessMixin siempre redirige (lo de tirar PermissionDenied al
        usuario autenticado recién llega en 2.1), así que alguien con cuenta que
        abriera el link "Aprobar!" del mail entraba en un ida y vuelta al login sin
        ningún mensaje. Mismo texto que usan las vistas de /tools/.
        """

        if self.request.user.is_authenticated:
            return HttpResponse("No tenes permisos para esto.", status=403)

        return super().handle_no_permission()


class SoloPostMixin:
    """Para las vistas que solo reciben el POST de un botón, un form o un fetch.

    Sin esto un GET (el link abierto en el navegador, un bot) caía en el get() de
    TemplateView, que busca el template que django_conventions deriva del nombre de la
    vista. Casi ninguna lo tiene, así que contestaba 500 TemplateDoesNotExist y dejaba un
    error en Jentry. Las que sí tienen uno, porque post() lo usa para armar su respuesta,
    contestaban 200 con un pedazo de pantalla vacío: /tools/sendpreguntaremail/ decía "Ya
    se envió un mail a este usuario" sin haber mandado nada.

    El 405 sale antes que los mixins de permisos y es igual para todos: no corre nada de
    la vista y a un anónimo no le dice más que la redirección al login. Por eso va primero
    entre las clases base; detrás de un mixin de login el GET igual se corta, pero recién
    después del chequeo de permisos y con otra respuesta para cada uno.
    """

    http_method_names = ["post"]

    def dispatch(self, request, *args, **kwargs):

        if request.method.lower() not in self.http_method_names:
            return self.http_method_not_allowed(request, *args, **kwargs)

        return super().dispatch(request, *args, **kwargs)


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