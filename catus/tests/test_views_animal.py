"""Tests de permisos y robustez de las vistas de animales.

El modelo de permisos de la app: cada animal tiene un dueño (cargado_por, el
rescatista que lo cargó) y los superusuarios administran todo. Una persona
logueada no debería poder tocar animales de otra persona.
"""
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings

from catus.models import Animal, CatusUser
from catus.tests.factories import make_animal, make_user
from catus.views.animal import (
    AddComment,
    AprobarView,
    MarcarAdoptado,
    MarcarExpirado,
    PhotosView,
    ValidateNameView,
)


class AnimalViewTestCase(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.duenio = make_user(email="duenio@catpuccino.test")
        self.intruso = make_user(email="intruso@catpuccino.test")
        self.admin = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)
        self.animal = make_animal(nombre="Willy", cargado_por=self.duenio, aprobado=False)

    def call(self, view_class, user, method="post", data=None, **kwargs):

        request = getattr(self.factory, method)("/", data or {})
        request.user = user
        return view_class.as_view()(request, **kwargs)


class AprobarViewTest(AnimalViewTestCase):
    """Aprobar publica el animal en el sitio: es una acción de administración."""

    def test_un_anonimo_no_puede_aprobar(self):

        response = self.call(AprobarView, AnonymousUser(), method="get", data={"id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertFalse(self.animal.aprobado, "un anónimo aprobó un animal")
        self.assertIn(response.status_code, (302, 403))

    def test_un_usuario_comun_no_puede_aprobar(self):

        response = self.call(AprobarView, self.intruso, method="get", data={"id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertFalse(self.animal.aprobado, "un usuario común aprobó un animal")
        #a quien ya está logueado se le contesta con un mensaje, no se lo manda al
        #login: ver SinPermisoTest más abajo
        self.assertNotIn("aprobado!", response.content.decode())

    def test_el_admin_aprueba(self):

        self.call(AprobarView, self.admin, method="get", data={"id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertTrue(self.animal.aprobado)

    def test_un_id_inexistente_no_rompe(self):

        response = self.call(AprobarView, self.admin, method="get", data={"id": 999999})

        self.assertEqual(response.status_code, 200)

    def test_sin_id_no_rompe(self):

        response = self.call(AprobarView, self.admin, method="get", data={})

        self.assertEqual(response.status_code, 200)


class MarcarEstadoTest(AnimalViewTestCase):
    """Marcar adoptado/expirado cambia lo que ve el público."""

    def test_un_intruso_no_puede_marcar_adoptado(self):

        self.call(MarcarAdoptado, self.intruso, data={"animal_id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertNotEqual(self.animal.estado, "A", "un intruso marcó adoptado un animal ajeno")

    def test_el_duenio_puede_marcar_adoptado(self):

        self.call(MarcarAdoptado, self.duenio, data={"animal_id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")
        self.assertIsNotNone(self.animal.fecha_adopcion)

    def test_el_admin_puede_marcar_animales_ajenos(self):

        self.call(MarcarAdoptado, self.admin, data={"animal_id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")

    def test_un_anonimo_no_puede_marcar(self):

        self.call(MarcarExpirado, AnonymousUser(), data={"animal_id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertNotEqual(self.animal.estado, "E")

    def test_marcar_en_lote_solo_toca_los_propios(self):

        ajeno = make_animal(nombre="Ajeno", cargado_por=self.intruso)

        self.call(MarcarAdoptado, self.duenio, data={"animal_ids": [self.animal.id, ajeno.id]})

        self.animal.refresh_from_db()
        ajeno.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")
        self.assertNotEqual(ajeno.estado, "A", "se marcó un animal de otra persona")

    def test_un_id_inexistente_no_rompe(self):
        """Antes daba NameError: se usaba la variable del for con la lista vacía."""

        response = self.call(MarcarAdoptado, self.duenio, data={"animal_id": 999999})

        self.assertEqual(response.status_code, 200)


class AddCommentTest(AnimalViewTestCase):
    """El comentario sobre los animales de un rescatista lo escribe el equipo."""

    def test_un_intruso_no_puede_comentar_sobre_otro(self):

        self.call(AddComment, self.intruso, data={"user_id": self.duenio.id, "comment": "hola"})

        self.duenio.refresh_from_db()
        self.assertNotEqual(self.duenio.animales_comentario, "hola")

    def test_el_admin_puede_comentar(self):

        self.call(AddComment, self.admin, data={"user_id": self.duenio.id, "comment": "llamar el lunes"})

        self.duenio.refresh_from_db()
        self.assertEqual(self.duenio.animales_comentario, "llamar el lunes")

    def test_un_user_id_inexistente_no_rompe(self):

        response = self.call(AddComment, self.admin, data={"user_id": 999999, "comment": "hola"})

        self.assertIn(response.status_code, (200, 404))


class PhotosViewTest(AnimalViewTestCase):
    """La usa el formulario público de pre-adopción para mostrar las fotos."""

    def test_un_id_inexistente_no_rompe(self):

        response = self.call(PhotosView, AnonymousUser(), data={"animal_id": 999999})

        self.assertEqual(response.status_code, 200)

    def test_sin_id_devuelve_vacio(self):

        import json

        response = self.call(PhotosView, AnonymousUser(), data={})

        self.assertEqual(json.loads(response.content.decode())["photos_count"], 0)

    def test_no_muestra_fotos_de_animales_sin_aprobar(self):
        """Los animales sin aprobar todavía no son públicos."""

        import json

        response = self.call(PhotosView, AnonymousUser(), data={"animal_id": self.animal.id})

        self.assertEqual(json.loads(response.content.decode())["photos_count"], 0)


class EditViewPermisosTest(AnimalViewTestCase):
    """Editar un animal ajeno cambiando el id de la URL.

    Solo se prueba el control de acceso: renderizar el formulario entero pide
    bootstrap4 y crispy, que se cargan al levantar el proyecto completo.
    """

    def edit(self, user, animal_id):

        from catus.views.animal import EditView

        request = self.factory.get("/animales/{}/".format(animal_id))
        request.user = user

        view = EditView()
        view.request = request
        return view.req(animal_id=str(animal_id))

    def test_un_intruso_no_puede_abrir_el_animal_de_otro(self):

        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            self.edit(self.intruso, self.animal.id)

    def test_un_animal_inexistente_da_404_y_no_500(self):

        from django.http import Http404

        with self.assertRaises(Http404):
            self.edit(self.duenio, 999999)


class ValidateNameViewTest(AnimalViewTestCase):

    def test_avisa_si_el_nombre_esta_en_uso(self):

        import json

        make_animal(nombre="Pelusa", estado="D", cargado_por=self.duenio)

        response = self.call(ValidateNameView, self.duenio, data={"name": "Pelusa"})

        self.assertFalse(json.loads(response.content.decode())["valid"])

    def test_acepta_un_nombre_libre(self):

        import json

        response = self.call(ValidateNameView, self.duenio, data={"name": "Nombre Nuevo"})

        self.assertTrue(json.loads(response.content.decode())["valid"])


class MailDeAprobacionTest(TestCase):
    """El aviso de "ya está publicado" que recibe el rescatista."""

    def enviar(self, animal):

        from catus.services.mail import MailService

        MailService().send_mail_aprobacion(animal)

    def test_avisa_al_rescatista(self):

        from django.core import mail
        from django.test import override_settings

        user = make_user(email="rescatista@catpuccino.test")
        animal = make_animal(nombre="Willy", cargado_por=user)

        with override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test"):
            self.enviar(animal)

        self.assertIn("rescatista@catpuccino.test", [d for m in mail.outbox for d in m.to])

    def test_un_animal_sin_rescatista_no_rompe(self):
        """Sin esto, aprobar un animal huérfano tiraba 500 y lo dejaba sin aprobar."""

        from django.test import override_settings

        animal = make_animal(nombre="Huérfano", cargado_por=None)

        with override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test"):
            self.enviar(animal)

    def test_un_rescatista_sin_mail_no_rompe(self):

        from django.test import override_settings

        user = make_user(email="")
        animal = make_animal(nombre="Willy", cargado_por=user)

        with override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test"):
            self.enviar(animal)


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="k", ENV="TEST")
class RevisionAlEditarTest(AnimalViewTestCase):
    """Editar un animal ya revisado tiene que volver a revisarlo.

    Sin esto alguien podía cargar un gato de verdad, quedar aprobado, y después
    editar la publicación para reemplazar fotos y texto por otra cosa, conservando
    el "OK" que el equipo ve en /tools/animalespendientes/.
    """

    def campos_del_formset(self, animal):

        imagenes = list(animal.get_images())

        datos = {
            "animalimage_set-TOTAL_FORMS": str(len(imagenes)),
            "animalimage_set-INITIAL_FORMS": str(len(imagenes)),
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
        }
        for i, imagen in enumerate(imagenes):
            datos["animalimage_set-%d-id" % i] = str(imagen.id)
            datos["animalimage_set-%d-animal" % i] = str(animal.id)

        return datos

    def editar(self, animal, **cambios):

        from unittest import mock
        from catus.services.moderacion import ModeracionService

        datos = {
            "tipo": animal.tipo, "estado": animal.estado, "nombre": animal.nombre,
            "edad": animal.edad or "", "sexo": animal.sexo, "zona": animal.zona or "",
            "datos": animal.datos or "",
        }
        datos.update(cambios)
        datos.update(self.campos_del_formset(animal))

        request = self.factory.post("/animales/%s/" % animal.id, datos)
        request.user = self.duenio

        from django.contrib.sessions.middleware import SessionMiddleware
        SessionMiddleware().process_request(request)
        request.session.save()

        from catus.views.animal import EditView
        view = EditView()
        view.request = request

        with mock.patch.object(ModeracionService, "revisar_y_guardar") as revisar:
            view.req(is_post=True, animal_id=str(animal.id))

        return revisar

    def setUp(self):
        super().setUp()
        from catus.tests.factories import make_animal_image

        self.animal.datos = "Un gatito."
        self.animal.save()
        make_animal_image(animal=self.animal)

    def test_cambiar_el_texto_dispara_una_nueva_revision(self):

        revisar = self.editar(self.animal, datos="Vendo iPhone barato 11-5555-5555")

        self.assertTrue(revisar.called, "editar el texto no volvió a revisar")

    def test_cambiar_el_nombre_dispara_una_nueva_revision(self):

        self.assertTrue(self.editar(self.animal, nombre="Otro").called)

    def test_editar_solo_la_zona_no_gasta_una_llamada(self):

        revisar = self.editar(self.animal, zona="Otra zona")

        self.assertFalse(revisar.called, "una edición menor gastó una llamada paga")


class SinPermisoTest(AnimalViewTestCase):
    """A quien ya está logueado hay que contestarle, no mandarlo al login.

    En Django 2.0 AccessMixin siempre redirige, así que alguien con cuenta que abriera
    el link "Aprobar!" del mail entraba en un ida y vuelta: se loguea, vuelve a la
    vista, y la vista lo manda al login otra vez, sin ningún mensaje.
    """

    def test_un_usuario_logueado_recibe_un_mensaje(self):

        response = self.call(AprobarView, self.intruso, method="get", data={"id": self.animal.id})

        self.assertEqual(response.status_code, 200)
        self.assertIn("No tenes permisos", response.content.decode())

    def test_un_anonimo_sigue_yendo_al_login(self):

        response = self.call(AprobarView, AnonymousUser(), method="get", data={"id": self.animal.id})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_el_permiso_no_se_afloja(self):

        self.call(AprobarView, self.intruso, method="get", data={"id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertFalse(self.animal.aprobado)
