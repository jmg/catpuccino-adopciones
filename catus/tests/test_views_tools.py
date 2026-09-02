"""Tests de las herramientas del equipo (/tools/).

Todo lo que hay acá es de administración: publicar en Instagram, generar
imágenes, mandar mails. Nada debería estar abierto.
"""
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings

from catus.models import Animal
from catus.tests.factories import make_animal, make_animal_image, make_user


class ToolsViewTestCase(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.cualquiera = make_user(email="cualquiera@ejemplo.test")
        self.admin = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)
        self.rescatista = make_user(email="rescatista@catpuccino.test")

    def call(self, view_class, user, method="post", data=None, **kwargs):

        request = getattr(self.factory, method)("/", data or {})
        request.user = user
        return view_class.as_view()(request, **kwargs)


class SendPreguntarEmailViewTest(ToolsViewTestCase):
    """Manda un mail con contenido libre al rescatista que se le indique.

    Sin control de acceso esto era un relay abierto: cualquiera podía mandar
    HTML arbitrario a cualquier usuario registrado, desde el dominio del sitio.
    """

    def setUp(self):
        super().setUp()
        make_animal(cargado_por=self.rescatista, estado="D", aprobado=True)

    def enviar(self, user):

        from catus.views.tools import SendPreguntarEmailView

        return self.call(SendPreguntarEmailView, user, data={
            "user_id": self.rescatista.id,
            "content": "<b>hola</b>",
        })

    @override_settings(ENV="TEST")
    def test_un_anonimo_no_puede_mandar_mails(self):

        self.enviar(AnonymousUser())

        self.assertEqual(len(mail.outbox), 0, "un anónimo mandó un mail desde el sitio")

    @override_settings(ENV="TEST")
    def test_un_usuario_comun_no_puede_mandar_mails(self):

        self.enviar(self.cualquiera)

        self.assertEqual(len(mail.outbox), 0, "un usuario común mandó un mail desde el sitio")

    @override_settings(ENV="TEST")
    def test_un_user_id_inexistente_no_rompe(self):

        from catus.views.tools import SendPreguntarEmailView

        response = self.call(SendPreguntarEmailView, self.admin, data={
            "user_id": 999999, "content": "hola",
        })

        self.assertEqual(response.status_code, 200)


class DownloadImagesViewTest(ToolsViewTestCase):

    def descargar(self, user, animal_id):

        from catus.views.tools import DownloadImagesView

        return self.call(DownloadImagesView, user, method="get", animal_id=str(animal_id))

    def test_un_usuario_comun_no_descarga(self):

        animal = make_animal(cargado_por=self.rescatista)

        response = self.descargar(self.cualquiera, animal.id)

        self.assertNotEqual(response.get("Content-Type"), "application/octet-stream")

    def test_un_animal_inexistente_no_rompe(self):

        response = self.descargar(self.admin, 999999)

        self.assertEqual(response.status_code, 200)

    def test_sin_imagenes_generadas_no_rompe(self):
        """Antes explotaba al leer image_for_instagram de una foto sin procesar."""

        animal = make_animal(cargado_por=self.rescatista)
        make_animal_image(animal=animal)

        response = self.descargar(self.admin, animal.id)

        self.assertEqual(response.status_code, 200)


class SaveFormViewTest(ToolsViewTestCase):

    def test_un_usuario_comun_no_marca_listo_para_publicar(self):

        from catus.views.tools import SaveFormView

        animal = make_animal(cargado_por=self.rescatista)

        self.call(SaveFormView, self.cualquiera, data={
            "animal_id": animal.id, "instagram_listo_para_publicar": "1",
        })

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar)

    def test_un_animal_inexistente_no_rompe(self):

        from catus.views.tools import SaveFormView

        response = self.call(SaveFormView, self.admin, data={"animal_id": 999999})

        self.assertEqual(response.status_code, 200)
