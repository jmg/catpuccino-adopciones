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


class EditarAnimalTestCase(AnimalViewTestCase):
    """POST de edición del animal, como lo manda la pantalla del rescatista."""

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


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="k", ENV="TEST")
class RevisionAlEditarTest(EditarAnimalTestCase):
    """Editar un animal ya revisado tiene que volver a revisarlo.

    Sin esto alguien podía cargar un gato de verdad, quedar aprobado, y después
    editar la publicación para reemplazar fotos y texto por otra cosa, conservando
    el "OK" que el equipo ve en /tools/animalespendientes/.
    """

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

    def test_mover_solo_el_recorte_no_gasta_una_llamada(self):
        """La revisión mira la foto y el texto; el recorte para Instagram no lo ve.

        La condición era `any(f.has_changed())` sobre el formset y los cuatro campos del
        recorte cuentan como cambio, así que corregirle el encuadre a una foto pagaba una
        llamada al pedo. Y si la IA contestaba 'R', encima sacaba al animal de la cola del
        posteo automático: por mover un cuadradito.
        """

        imagen = self.animal.get_images()[0]

        revisar = self.editar(self.animal, **{
            "animalimage_set-0-crop_x": "0.1",
            "animalimage_set-0-crop_y": "0.0",
            "animalimage_set-0-crop_w": "0.5",
            "animalimage_set-0-crop_h": "0.5",
        })

        self.assertFalse(revisar.called, "cambiar el recorte gastó una llamada paga")

        imagen.refresh_from_db()
        self.assertEqual(imagen.crop_x, 0.1, "no se guardó el recorte: el test no probó nada")


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


class NombreEscapadoAlAprobarTest(AnimalViewTestCase):
    """La respuesta de aprobar sale como text/html en la sesión de quien aprueba.

    El nombre lo escribe cualquiera que se registre y el link "Aprobar!" se abre desde
    el mail con la sesión de alguien del equipo: sin escapar, un animal llamado
    "<script>..." corría en el navegador del superusuario.
    """

    def aprobar(self, animal):

        return self.call(AprobarView, self.admin, method="get", data={"id": animal.id})

    def test_el_nombre_va_escapado(self):

        animal = make_animal(nombre="<script>alert(1)</script>", cargado_por=self.duenio, aprobado=False)

        cuerpo = self.aprobar(animal).content.decode()

        self.assertNotIn("<script>", cuerpo, "el nombre salió sin escapar")
        self.assertIn("&lt;script&gt;", cuerpo)

    def test_tambien_va_escapado_si_ya_estaba_aprobado(self):

        animal = make_animal(nombre="<script>alert(1)</script>", cargado_por=self.duenio, aprobado=True)

        self.assertNotIn("<script>", self.aprobar(animal).content.decode())

    def test_un_fallo_del_mail_no_pierde_la_aprobacion(self):
        """El mail se mandaba antes de guardar: si el proveedor fallaba, el animal
        quedaba sin aprobar y quien apretó "Aprobar!" se comía un 500."""

        from unittest import mock

        from catus.services.mail import MailService

        with mock.patch.object(MailService, "send_mail_aprobacion", side_effect=Exception("proveedor caído")):
            response = self.aprobar(self.animal)

        self.animal.refresh_from_db()
        self.assertTrue(self.animal.aprobado, "se perdió la aprobación porque falló el mail")
        self.assertEqual(response.status_code, 200)


class TopeDePedidosAInstagramTest(AnimalViewTestCase):
    """/animal/pulldatafromig/ sale a buscar el post y hace una llamada paga a OpenAI.

    El registro es abierto, así que estar logueado no es un permiso: sin tope,
    cualquiera con una cuenta le vacía la cuenta de OpenAI al refugio con un bucle
    de curl. El tope cuenta pedidos, no animales: siempre se pide el mismo post.
    """

    def pedir(self, user):

        from unittest import mock

        from catus.services.gpt import GPTService
        from catus.views.animal import PullDataFromIg

        request = self.factory.get("/animal/pulldatafromig/", {"url": "https://www.instagram.com/p/abc/"})
        request.user = user

        with mock.patch.object(GPTService, "pull_data_from_ig", return_value={"Nombre": "Willy"}) as pull:
            response = PullDataFromIg.as_view()(request)

        return response, pull

    @override_settings(GPT_IG_MAX_POR_DIA=2)
    def test_pasado_el_tope_no_se_llama_a_la_api(self):

        import json

        for _ in range(2):
            self.pedir(self.duenio)

        response, pull = self.pedir(self.duenio)

        self.assertFalse(pull.called, "se gastó una llamada paga después del tope")
        self.assertIn("error", json.loads(response.content.decode()))
        self.assertEqual(response.status_code, 200, "el tope no puede ser una excepción")

    @override_settings(GPT_IG_MAX_POR_DIA=2)
    def test_debajo_del_tope_se_atiende_normalmente(self):

        import json

        response, pull = self.pedir(self.duenio)

        self.assertTrue(pull.called)
        self.assertEqual(json.loads(response.content.decode())["Nombre"], "Willy")

    @override_settings(GPT_IG_MAX_POR_DIA=2)
    def test_el_tope_es_de_cada_persona(self):

        for _ in range(2):
            self.pedir(self.duenio)

        response, pull = self.pedir(self.intruso)

        self.assertTrue(pull.called, "el tope de una persona le frenó los pedidos a otra")


class ImagenDeInstagramAlEditarTest(EditarAnimalTestCase):
    """La imagen del posteo lleva el nombre, la edad y el sexo quemados en el pixel.

    generar_imagen_para_instagram se saltea la foto que ya tiene su image_for_instagram,
    así que la imagen no se rehacía nunca: el rescatista corregía la edad —o reemplazaba
    la foto— y el posteo salía igual, con los datos viejos, sin que nadie lo mirara.
    """

    def setUp(self):
        super().setUp()

        import shutil
        import tempfile

        from catus.tests.factories import make_animal_image, uploaded_photo

        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(self.override.disable)

        self.animal.datos = "Un gatito."
        self.animal.edad = "2 años"
        self.animal.save()

        self.imagen = make_animal_image(animal=self.animal)
        self.imagen.image_for_instagram.save("posteo.jpg", uploaded_photo(), save=True)

    def tiene_imagen_de_posteo(self):

        self.imagen.refresh_from_db()

        return bool(self.imagen.image_for_instagram)

    def test_cambiar_la_edad_rehace_la_imagen_del_posteo(self):

        self.editar(self.animal, edad="3 años")

        self.assertFalse(
            self.tiene_imagen_de_posteo(),
            "el posteo iba a salir con la edad vieja dibujada",
        )

    def test_cambiar_el_nombre_rehace_la_imagen_del_posteo(self):

        self.editar(self.animal, nombre="Pelusa")

        self.assertFalse(self.tiene_imagen_de_posteo())

    def test_cambiar_el_sexo_rehace_la_imagen_del_posteo(self):

        self.editar(self.animal, sexo="H")

        self.assertFalse(self.tiene_imagen_de_posteo())

    def test_reemplazar_la_foto_rehace_su_imagen_del_posteo(self):
        """La imagen compuesta es de la foto vieja: la nueva ni aparece en el posteo."""

        from catus.tests.factories import uploaded_photo

        self.editar(self.animal, **{"animalimage_set-0-image": uploaded_photo(name="otra.jpg")})

        self.assertFalse(self.tiene_imagen_de_posteo())

    def test_editar_solo_la_zona_no_toca_la_imagen(self):
        """Rearmar cuesta segundos de CPU por foto y cambia el nombre del archivo."""

        self.editar(self.animal, zona="Otra zona")

        self.assertTrue(self.tiene_imagen_de_posteo(), "se rearmó una imagen que estaba bien")

    def test_mover_solo_el_recorte_rehace_la_imagen(self):
        """El recorte es el cuadrado que se publica: cambiarlo cambia la imagen compuesta.

        No dispara la revisión con IA (eso lo prueba RevisionAlEditarTest), pero sí hay
        que rearmar el posteo: si no, el rescatista corrige el encuadre para que no salga
        el animal cortado y sale igual.
        """

        self.editar(self.animal, **{
            "animalimage_set-0-crop_x": "0.1",
            "animalimage_set-0-crop_y": "0.0",
            "animalimage_set-0-crop_w": "0.5",
            "animalimage_set-0-crop_h": "0.5",
        })

        self.assertFalse(self.tiene_imagen_de_posteo())
        self.assertEqual(self.imagen.crop_x, 0.1, "no se guardó el recorte: el test no probó nada")

    def test_un_animal_ya_publicado_conserva_su_imagen(self):
        """Ese archivo es lo que se subió a Instagram.

        Rearmarlo no cambia el post que ya está en la cuenta —preparar_publicaciones
        filtra instagram_publicado=False, así que ni lo mira— y borrarlo sólo pierde el
        registro de lo que se publicó.
        """

        self.animal.instagram_publicado = True
        self.animal.save()

        self.editar(self.animal, nombre="Pelusa")

        self.assertTrue(
            self.tiene_imagen_de_posteo(),
            "se borró la imagen de un posteo que ya salió",
        )
