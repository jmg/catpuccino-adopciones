"""El banner y el logo del perfil del rescatista (CatusUser.save -> ImageService.resize).

resize escalaba siempre para dejar el ancho en el límite, aunque lo que se pasara fuera el
alto. Una foto vertical de celular de 1080x1920 como banner (límite 1500) quedaba en
1500x2666, y un logo de 400x800 (límite 500) en 500x1000: agrandados en vez de achicados,
más pesados, borrosos y con el alto todavía por encima del límite.
"""
import shutil
import tempfile

from PIL import Image

from django.test import TestCase, override_settings

from catus.tests.factories import make_user, uploaded_photo


class ResizeDelPerfilTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def guardada(self, campo, size):
        """Sube una imagen de ese tamaño al campo del perfil y devuelve el tamaño guardado."""

        usuario = make_user(email="perfil-{}-{}x{}@catpuccino.test".format(campo, *size))
        setattr(usuario, campo, uploaded_photo(size=size))
        usuario.save()
        usuario.refresh_from_db()

        with Image.open(getattr(usuario, campo).path) as foto:
            return foto.size

    def test_un_banner_vertical_se_achica_por_el_alto(self):

        self.assertEqual(self.guardada("banner_img", (1080, 1920)), (844, 1500))

    def test_un_logo_vertical_y_angosto_no_se_agranda(self):

        self.assertEqual(self.guardada("logo_img", (400, 800)), (250, 500))

    def test_un_banner_apaisado_se_achica_por_el_ancho(self):

        self.assertEqual(self.guardada("banner_img", (3000, 1000)), (1500, 500))

    def test_una_imagen_que_ya_entra_no_se_toca(self):

        self.assertEqual(self.guardada("logo_img", (300, 200)), (300, 200))

    def test_ningun_lado_queda_por_encima_del_limite_ni_se_agranda(self):

        for size in ((1200, 3000), (3000, 1200), (2000, 2000), (501, 499), (120, 900)):
            with self.subTest(size=size):
                ancho, alto = self.guardada("logo_img", size)
                self.assertLessEqual(max(ancho, alto), 500)
                self.assertLessEqual(ancho, size[0])
                self.assertLessEqual(alto, size[1])
