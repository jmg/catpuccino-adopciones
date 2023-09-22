from datetime import datetime
import random
from django.shortcuts import render
from django.views.generic import TemplateView
from catus.models import Animal, EstadoFormulario
from django.http import HttpResponse
from catus.services.cache import CacheService
from catus.utils import get_context_columns, send_html_email
from django.conf import settings
from datetime import datetime
from .base import BaseView


class IndexView(BaseView):

    url = r"^$"

    def render_to_response(self, context):

        context["main"] = True

        #sort_direction = random.choice(["-", ""])
        #animals = CacheService().get("animals-for-adoption")
        #if not animals:
        #    animals = Animal.get_all_for_adoption(destacado=True, sort="-fecha_ingreso")
        #    CacheService().set("animals-for-adoption", animals)

        animals = Animal.get_all_for_adoption(destacado=True, sort="-fecha_ingreso")
        context["animals"] = animals
        context["perros_en_adopcion"] = bool([animal for animal in context["animals"] if animal.tipo == "P"])

        context["cols"] = get_context_columns(context["animals"])
        context["year"] = datetime.now().year

        zones = set([animal.zona.strip() for animal in context["animals"] if animal.zona])
        context["zones"] = "||".join(sorted(zones))

        if self.request.user.is_authenticated:
            context["forms_counts"] = EstadoFormulario.objects.filter(
                gato__cargado_por=self.request.user,
                gato__estado="D",
            ).count()

        return BaseView.render_to_response(self, context)


class FAQView(TemplateView):

    url = r"^como-funciona/$"


class NotFoundView(TemplateView):

    url = r"^404$"
    template_name = "404.html"


class ErrorView(TemplateView):

    url = r"^500$"
    template_name = "500.html"


class PrivacyView(TemplateView):

    template_name = "home/policy.html"
    url = r"^privacidad/$"


class SitemapView(BaseView):

    template_name = "sitemap.xml"
    url = r"^sitemap.xml$"

    def render_to_response(self, context):

        response = HttpResponse(content_type="text/xml")
        response.write(self.render(self.template_name, context))
        return response