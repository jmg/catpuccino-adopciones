"""Toda imagen subida a un modelo se guarda como gallery/<uuid><extensión>.

ADOPCIONES-3SVEZ: Django 5 toma como extensión todo lo que sigue al primer punto del nombre
y, si no entra en los 100 caracteres de la columna, acorta solo lo de antes. Una foto llamada
como la descripción del animal, con un punto en la primera oración, no se podía guardar. El
#553 lo arregló en el formulario del animal; el banner y el logo del perfil (y el admin)
seguían fallando igual: un 400 al guardar el perfil con una imagen así.
"""
import json
import os
import re
import shutil
import tempfile

from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from catus.models import AnimalImage, ruta_de_imagen
from catus.tests.factories import make_animal, make_user, photo_bytes, uploaded_photo
from catus.views.accounts import ProfileView

#inventado, con la forma del caso real: la descripción como nombre, con un punto temprano
NOMBRE_LARGO = (
    "Pelusa busca familia. Es una gata muy mimosa, juguetona y tranquila, "
    "se lleva bien con otros gatos y con perros chicos.JPG"
)
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class RutaDeImagenTest(SimpleTestCase):

    def test_queda_gallery_uuid_y_la_ultima_extension_en_minuscula(self):

        self.assertRegex(ruta_de_imagen(None, NOMBRE_LARGO), r"^gallery/{}\.jpg$".format(UUID))
        self.assertRegex(ruta_de_imagen(None, "foto.png"), r"^gallery/{}\.png$".format(UUID))

    def test_nombres_raros(self):

        #la extensión que valida Django (la última), aunque el nombre empiece con puntos
        self.assertRegex(ruta_de_imagen(None, "..jpg"), r"^gallery/{}\.jpg$".format(UUID))
        self.assertRegex(ruta_de_imagen(None, "sin_extension"), r"^gallery/{}$".format(UUID))
        self.assertRegex(ruta_de_imagen(None, "foto.extensionlarguisima"), r"^gallery/{}$".format(UUID))
        self.assertRegex(ruta_de_imagen(None, "foto.j p g"), r"^gallery/{}$".format(UUID))

    def test_cada_subida_tiene_su_nombre(self):

        self.assertNotEqual(ruta_de_imagen(None, "foto.jpg"), ruta_de_imagen(None, "foto.jpg"))


class ImagenesConNombreLargoTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.media, "gallery"))
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(self.override.disable)

        self.rescatista = make_user(email="perfil@catpuccino.test", handle="perfil_prueba")

    def guardar_perfil(self, **archivos):

        datos = {"email": self.rescatista.email, "handle": "perfil_prueba", "title": "", "description": "",
                 "facebook": "", "twitter": "", "instagram": ""}
        datos.update(archivos)
        request = RequestFactory().post("/accounts/profile/", datos)
        request.user = self.rescatista
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()

        view = ProfileView()
        view.request = request
        return json.loads(view.post().content)

    def test_el_banner_con_nombre_largo_se_guarda(self):

        respuesta = self.guardar_perfil(banner_img=SimpleUploadedFile(NOMBRE_LARGO, photo_bytes().getvalue(), content_type="image/jpeg"))

        self.assertEqual(respuesta["status"], "success", respuesta)
        self.rescatista.refresh_from_db()
        self.assertRegex(self.rescatista.banner_img.name, r"^gallery/{}\.jpg$".format(UUID))
        self.assertTrue(os.path.exists(self.rescatista.banner_img.path))
        self.assertEqual(respuesta["banner_img"], "/" + self.rescatista.banner_img.name)

    def test_el_logo_con_nombre_largo_se_guarda(self):

        respuesta = self.guardar_perfil(logo_img=SimpleUploadedFile(NOMBRE_LARGO, photo_bytes().getvalue(), content_type="image/jpeg"))

        self.assertEqual(respuesta["status"], "success", respuesta)
        self.rescatista.refresh_from_db()
        #pasa los 500 px del logo: CatusUser.save() lo achica y lo vuelve a guardar como .jpeg
        self.assertRegex(self.rescatista.logo_img.name, r"^gallery/{}\.jpe?g$".format(UUID))
        self.assertTrue(os.path.exists(self.rescatista.logo_img.path))

    def test_una_foto_guardada_por_fuera_del_formulario_tambien_entra(self):
        """El inline del admin y cualquier otro camino guardan por el modelo."""

        imagen = AnimalImage(animal=make_animal(cargado_por=self.rescatista))
        imagen.image.save(NOMBRE_LARGO, uploaded_photo(), save=True)

        self.assertRegex(imagen.image.name, r"^gallery/{}\.jpg$".format(UUID))
        self.assertTrue(os.path.exists(imagen.image.path))
