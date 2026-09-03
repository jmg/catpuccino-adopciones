"""Tests de las respuestas del formulario público como contenido no confiable.

Las escribe cualquiera desde internet y después las lee el equipo en el navegador
y en el mail, así que no pueden llegar como HTML.
"""
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import RequestFactory, TestCase

from forms_builder.forms.models import Field, FieldEntry, Form, FormEntry

from catus.models import FacebookAccount
from catus.services.adoption import AdoptionService
from catus.tests.factories import make_animal, make_user


class RespuestasNoConfiablesTest(TestCase):

    def setUp(self):
        self.service = AdoptionService()
        self.form = Form.objects.create(title="Pre Adopción")
        self.entry = FormEntry.objects.create(form=self.form)

    def responder(self, label, value, field_type=1):

        field = Field.objects.create(label=label, field_type=field_type)
        FieldEntry.objects.create(entry=self.entry, field_id=field.id, value=value)

    def render(self, plantilla, contexto):

        return Template(plantilla).render(Context(contexto))

    def test_una_respuesta_de_texto_no_llega_como_html(self):
        """Antes el template la imprimía con |safe y el script corría en el navegador del admin."""

        self.responder("Nombre y Apellido", 'Ana <img src=x onerror="alert(1)">')

        _, value = self.service.get_formatted_fields(self.entry.fields.all())[0]
        salida = self.render("{{ value }}", {"value": value})

        self.assertNotIn("<img", salida)
        self.assertIn("&lt;img", salida)

    def test_una_respuesta_larga_tampoco(self):

        self.responder("Motivo", "<script>fetch('/robar')</script>")

        _, value = self.service.get_formatted_fields(self.entry.fields.all())[0]
        salida = self.render("{{ value }}", {"value": value})

        self.assertNotIn("<script>", salida)

    def test_la_foto_que_arma_el_servicio_si_es_html(self):
        """El <img> lo construimos nosotros, así que tiene que renderizar."""

        self.responder("Foto del hogar", "gallery/casa.jpg", field_type=9)

        _, value = self.service.get_formatted_fields(self.entry.fields.all(), photos_html=True)[0]
        salida = self.render("{{ value }}", {"value": value})

        self.assertIn("<img", salida)

    def test_el_nombre_del_archivo_no_escapa_del_atributo(self):

        self.responder("Foto", "gallery/a' onerror='alert(1).jpg", field_type=9)

        _, value = self.service.get_formatted_fields(self.entry.fields.all(), photos_html=True)[0]

        self.assertNotIn("onerror='alert(1)", value)


class FacebookLoginTest(TestCase):
    """Vincular la cuenta de Instagram desde la que publica el sitio."""

    def setUp(self):
        self.factory = RequestFactory()

    def conectar(self, user):

        from catus.views.facebook import LoginView

        request = self.factory.post("/facebook/login/", {"access_token": "token-de-un-tercero"})
        request.user = user
        return LoginView.as_view()(request)

    def test_un_anonimo_no_puede_cambiar_la_cuenta(self):

        self.conectar(AnonymousUser())

        self.assertEqual(FacebookAccount.objects.count(), 0, "un anónimo tocó la cuenta del sitio")

    def test_un_usuario_comun_tampoco(self):

        self.conectar(make_user(email="cualquiera@ejemplo.test"))

        self.assertEqual(FacebookAccount.objects.count(), 0)


class DescripcionesEnPaginasPublicasTest(TestCase):
    """La descripción del animal y la del perfil las escribe cualquiera que se registre.

    Se muestran con formato (son campos de texto enriquecido) en páginas públicas
    sin login, así que tienen que conservar negritas y links pero no ejecutar nada.
    """

    def render_card(self, datos):

        from django.template.loader import render_to_string

        animal = make_animal(nombre="Willy", datos=datos, aprobado=True)
        return render_to_string("adoption/card.html", {"animal": animal, "cols": 4})

    def test_la_descripcion_conserva_el_formato(self):

        html = self.render_card("<p>Willy es <strong>muy</strong> compañero</p>")

        self.assertIn("<strong>", html)

    def test_la_descripcion_no_puede_traer_scripts(self):
        """Iba con |safe a la home: el script corría en el navegador de cada visitante."""

        html = self.render_card('Hola <img src=x onerror="alert(1)">')

        self.assertNotIn("onerror", html)
        self.assertNotIn("<img src=x", html)

    def test_la_descripcion_no_puede_traer_links_con_javascript(self):

        html = self.render_card('<a href="javascript:alert(1)">click</a>')

        #el propio template usa href="javascript:" para "Mostrar más", así que
        #miramos el payload y no cualquier aparición de la palabra
        self.assertNotIn("javascript:alert", html)
        self.assertIn("<a>click</a>", html, "debería quedar el texto sin el link")
