from datetime import datetime
import random
from django.db.models import Count, Max, Q
from django.shortcuts import render
from django.templatetags.static import static
from django.utils import timezone
from django.utils.encoding import iri_to_uri
from django.views.generic import TemplateView
from catus.models import Animal, CatusUser, EstadoFormulario
from django.http import HttpResponse
from catus.services import ficha
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

        #lo que dice la portada en Google y al compartirla: cuántos buscan familia hoy
        perros = len([animal for animal in animals if animal.tipo == "P"])
        context["descripcion_portada"] = ficha.descripcion_de_la_portada(len(animals) - perros, perros)
        context["url_canonica"] = settings.SSL_HOST + "/"
        context["imagen_para_compartir"] = settings.SSL_HOST + static("compartir.png")

        context["cols"] = get_context_columns(context["animals"])
        context["year"] = datetime.now().year

        zones = set([animal.zona.strip() for animal in context["animals"] if animal.zona])
        context["zones"] = "||".join(sorted(zones))

        if self.request.user.is_authenticated:
            context["forms_counts"] = EstadoFormulario.objects.filter(
                gato__cargado_por=self.request.user,
                gato__estado="D",
            ).exclude(estado="B").count()

        return BaseView.render_to_response(self, context)


class FAQView(TemplateView):

    url = r"^como-funciona/$"
    template_name = "home/faq.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["year"] = datetime.now().year
        return context


class NotFoundView(TemplateView):

    url = r"^404$"
    template_name = "404.html"


class ErrorView(TemplateView):

    url = r"^500$"
    template_name = "500.html"


class PrivacyView(TemplateView):

    template_name = "home/policy.html"
    url = r"^privacidad/$"
    extra_context = {"legal_page": "privacidad"}

    def get_context_data(self, **kwargs):
        from catus.services.buenadoptante import BuenAdoptanteService

        context = super().get_context_data(**kwargs)
        #la política dice lo que pasa: BuenAdoptante aparece cuando los formularios se le mandan
        context["buenadoptante_activo"] = BuenAdoptanteService().activo()
        return context


class TermsView(TemplateView):

    template_name = "home/terms.html"
    url = r"^terminos/$"
    extra_context = {"legal_page": "terminos"}


def _dia(fecha):
    """La fecha de un lastmod (AAAA-MM-DD, en la hora de Buenos Aires), o None."""

    if fecha is None:
        return None

    if timezone.is_aware(fecha):
        fecha = timezone.localtime(fecha)
    return fecha.date().isoformat()


class SitemapView(BaseView):
    """Lo que el sitio le pide a los buscadores que indexen.

    Era un archivo fijo, con el login y el registro adentro y ni un animal. Ahora lista la
    portada, los formularios públicos, las páginas de ayuda y legales, el perfil de cada
    rescatista que tiene animales en adopción y la ficha de cada animal en adopción. El
    lastmod de un animal es su fecha_ingreso, que se renueva al republicarlo: updated_at no
    se escribe en cada save. Las páginas fijas van sin lastmod, porque no hay una fecha
    cierta que darles.
    """

    template_name = "sitemap.xml"
    url = r"^sitemap.xml$"

    def render_to_response(self, context):

        context["urls"] = self.urls()
        response = HttpResponse(content_type="application/xml; charset=utf-8")
        response.write(self.render(self.template_name, context))
        return response

    def urls(self):

        def entrada(ruta, lastmod=None, changefreq="weekly", priority="0.60"):
            return {
                "loc": settings.SSL_HOST + iri_to_uri(ruta), "lastmod": _dia(lastmod),
                "changefreq": changefreq, "priority": priority,
            }

        animales = list(
            Animal.objects.filter(aprobado=True, estado="D")
            .only("id", "nombre", "tipo", "fecha_ingreso")
            .order_by("-fecha_ingreso", "-id")
        )

        def ultimo(tipo=None):
            fechas = [a.fecha_ingreso for a in animales if a.fecha_ingreso and (tipo is None or a.tipo == tipo)]
            return max(fechas) if fechas else None

        urls = [
            entrada("/", ultimo(), "daily", "1.00"),
            entrada("/pre-adopcion/", ultimo("G"), "daily", "0.80"),
            entrada("/pre-adopcion/perros/", ultimo("P"), "daily", "0.80"),
            entrada("/como-funciona/", None, "monthly", "0.50"),
            entrada("/terminos/", None, "yearly", "0.30"),
            entrada("/privacidad/", None, "yearly", "0.30"),
        ]

        #las cuentas que comparten handle se listan por id: /<handle>/ muestra una sola
        repetidos = {
            handle.lower() for handle in CatusUser.objects.exclude(handle__isnull=True).exclude(handle="")
            .values("handle").annotate(cuantas=Count("id")).filter(cuantas__gt=1).values_list("handle", flat=True)
        }

        #sin only(): CatusUser.__init__ lee el banner y el logo, y diferidos eran dos
        #consultas más por cada rescatista
        rescatistas = (
            CatusUser.objects.filter(animal__aprobado=True, animal__estado="D")
            .annotate(ultimo=Max("animal__fecha_ingreso"))
            .order_by("id")
        )
        for rescatista in rescatistas:
            urls.append(entrada(ficha.url_del_perfil(rescatista, repetidos), rescatista.ultimo))

        for animal in animales:
            urls.append(entrada(animal.get_ficha_url(), animal.fecha_ingreso, "weekly", "0.70"))

        return urls


class RobotsView(BaseView):
    """/robots.txt, que daba 404. No nombra la URL del admin: es secreta, y robots.txt lo
    lee cualquiera."""

    url = r"^robots\.txt$"

    #lo que no tiene sentido en un buscador: el panel, las herramientas del equipo, los
    #formularios y contratos de cada adopción, el link privado para postularse
    NO_INDEXAR = [
        "/accounts/", "/tools/", "/formularios/", "/formulario/", "/contrato/",
        "/contrato_adopcion/", "/postularme/",
    ]

    def get(self, request, *args, **kwargs):

        lineas = ["User-agent: *"]
        lineas += ["Disallow: {}".format(ruta) for ruta in self.NO_INDEXAR]
        lineas += ["", "Sitemap: {}/sitemap.xml".format(settings.SSL_HOST), ""]
        return HttpResponse("\n".join(lineas), content_type="text/plain; charset=utf-8")