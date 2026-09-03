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


class MarcarListoParaInstagramTest(ToolsViewTestCase):
    """El botón "Listo para Instagram" decide qué publica el cron."""

    def toggle(self, animal, valor):

        from catus.views.tools import SaveFormView

        return self.call(SaveFormView, self.admin, data={
            "animal_id": animal.id,
            "instagram_listo_para_publicar": valor,
        })

    def test_marcar_lo_deja_listo(self):

        animal = make_animal(cargado_por=self.rescatista)

        self.toggle(animal, "on")

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_listo_para_publicar)

    def test_desmarcar_lo_saca_de_la_cola(self):
        """El botón manda "" al desmarcar; antes eso lo dejaba marcado igual."""

        animal = make_animal(cargado_por=self.rescatista, instagram_listo_para_publicar=True)

        self.toggle(animal, "")

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar, "desmarcar no tuvo efecto")


class PublishCommandTest(TestCase):
    """A qué animales alcanza el cron de publicación."""

    def animales_a_publicar(self):
        """Usa el filtro real del comando, no una copia."""

        from catus.management.commands.publish import Command

        return list(Command().animales_a_publicar())

    def test_publica_los_que_estan_en_adopcion(self):

        animal = make_animal(instagram_listo_para_publicar=True, aprobado=True, estado="D")

        self.assertIn(animal, self.animales_a_publicar())

    def test_no_publica_un_animal_ya_adoptado(self):
        """Se marcaba listo el lunes, se adoptaba el martes y el cron lo publicaba igual."""

        animal = make_animal(instagram_listo_para_publicar=True, aprobado=True, estado="A")

        self.assertNotIn(animal, self.animales_a_publicar())

    def test_no_publica_un_animal_sin_aprobar(self):

        animal = make_animal(instagram_listo_para_publicar=True, aprobado=False, estado="D")

        self.assertNotIn(animal, self.animales_a_publicar())

    def test_no_republica_lo_ya_publicado(self):

        animal = make_animal(
            instagram_listo_para_publicar=True, aprobado=True, estado="D",
            instagram_publicado=True,
        )

        self.assertNotIn(animal, self.animales_a_publicar())


class ComentarioDeAdoptadoEnInstagramTest(TestCase):
    """El cron que comenta en el post de Instagram cuando el animal encuentra hogar."""

    def animales_a_comentar(self):
        """Mismo filtro que update_status_in_ig."""

        from catus.models import Animal

        return list(Animal.objects.filter(
            estado="A",
            instagram_publicado=True,
            instagram_post_id__isnull=False,
            instagram_comment_id__isnull=True,
        ))

    def publicado(self, **kwargs):

        kwargs.setdefault("instagram_publicado", True)
        kwargs.setdefault("instagram_post_id", "123")
        return make_animal(**kwargs)

    def test_comenta_en_los_adoptados(self):

        animal = self.publicado(estado="A")

        self.assertIn(animal, self.animales_a_comentar())

    def test_no_comenta_en_los_reservados(self):
        """Decía "Ya fue adoptado" sobre un animal solo reservado, y no se podía corregir."""

        animal = self.publicado(estado="R")

        self.assertNotIn(animal, self.animales_a_comentar())

    def test_no_comenta_dos_veces(self):

        animal = self.publicado(estado="A", instagram_comment_id="456")

        self.assertNotIn(animal, self.animales_a_comentar())

    def test_no_comenta_en_los_que_no_se_publicaron(self):

        animal = make_animal(estado="A", instagram_publicado=False)

        self.assertNotIn(animal, self.animales_a_comentar())


class AnimalesPendientesViewTest(ToolsViewTestCase):
    """La pantalla donde el equipo revisa lo que falta aprobar."""

    def abrir(self, user):
        """django-conventions deriva template_name del módulo+clase al armar el urlconf;
        acá las vistas se llaman directo, así que hay que pasárselo."""

        from catus.views.tools import AnimalesPendientesView

        request = self.factory.get("/tools/animalespendientes/")
        request.user = user
        response = AnimalesPendientesView.as_view(
            template_name="tools/animalespendientes.html",
        )(request)

        #TemplateResponse llega sin renderizar cuando se llama a la vista directo
        if hasattr(response, "render") and not response.is_rendered:
            response.render()

        return response

    def test_un_usuario_comun_no_entra(self):

        response = self.abrir(self.cualquiera)

        self.assertIn("No tenes permisos", response.content.decode())

    def test_lista_los_que_faltan_aprobar(self):

        animal = make_animal(nombre="Willy", cargado_por=self.rescatista, aprobado=False)

        response = self.abrir(self.admin)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Willy", response.content.decode())

    def test_no_lista_los_adoptados(self):

        make_animal(nombre="YaAdoptado", cargado_por=self.rescatista, aprobado=False, estado="A")

        self.assertNotIn("YaAdoptado", self.abrir(self.admin).content.decode())

    def test_los_marcados_por_la_ia_aparecen_primero(self):
        """Es el punto de la pantalla: que lo dudoso se vea sin buscar."""

        from catus.models import Animal

        make_animal(nombre="Comun", cargado_por=self.rescatista, aprobado=False)
        make_animal(
            nombre="Sospechoso", cargado_por=self.rescatista, aprobado=False,
            revision_ia_estado=Animal.REVISION_REVISAR,
            revision_ia_motivo="No se ve ningún animal en las fotos.",
        )

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertLess(
            cuerpo.index("Sospechoso"), cuerpo.index("Comun"),
            "el marcado por la IA no quedó primero",
        )

    def test_muestra_el_motivo_de_la_ia(self):

        from catus.models import Animal

        make_animal(
            nombre="Sospechoso", cargado_por=self.rescatista, aprobado=False,
            revision_ia_estado=Animal.REVISION_REVISAR,
            revision_ia_motivo="No se ve ningún animal en las fotos.",
        )

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("No se ve ningún animal", cuerpo)
        self.assertIn("Revisar publicación", cuerpo)

    def test_los_animales_viejos_sin_revisar_no_molestan(self):
        """Tras migrar, todos los que ya existen quedan en 'sin revisar'."""

        from catus.models import Animal

        animal = make_animal(nombre="Viejo", cargado_por=self.rescatista, aprobado=False)
        self.assertEqual(animal.revision_ia_estado, Animal.REVISION_PENDIENTE)

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("Viejo", cuerpo)
        self.assertNotIn("Revisar publicación", cuerpo)
        self.assertNotIn("Revisada", cuerpo)
