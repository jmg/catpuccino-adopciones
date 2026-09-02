"""Tests del procesamiento de fotos: optimización al subir y armado del posteo."""
import os
import shutil
import tempfile

from PIL import Image

from django.test import TestCase, override_settings

from catus.services.images import ImageService
from catus.tests.factories import make_animal, make_animal_image


class ImageServiceTestCase(TestCase):

    def setUp(self):
        self.service = ImageService()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)


class OptimizeTest(ImageServiceTestCase):

    def test_achica_una_foto_grande(self):

        imagen = make_animal_image(size=(3000, 2000))

        self.service.optimize(imagen.image, max_width=1200)

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertEqual(foto.size, (1200, 800))

    def test_no_agranda_una_foto_vertical_chica(self):
        """Una foto de celular en vertical (1080x1920) no debería salir agrandada.

        El cálculo escalaba siempre por el ANCHO, así que cualquier foto vertical
        más angosta que el máximo terminaba estirada a un archivo más pesado que
        el original y sin más detalle.
        """

        imagen = make_animal_image(size=(1080, 1920))

        self.service.optimize(imagen.image, max_width=1200)

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertLessEqual(foto.size[0], 1080)
            self.assertLessEqual(foto.size[1], 1920)

    def test_el_lado_largo_no_pasa_del_maximo(self):

        for size in [(3000, 2000), (2000, 3000), (4000, 4000), (1600, 900)]:
            imagen = make_animal_image(size=size)

            self.service.optimize(imagen.image, max_width=1200)

            imagen.refresh_from_db()
            with Image.open(imagen.image.path) as foto:
                self.assertLessEqual(
                    max(foto.size), 1200,
                    "la foto {} quedó en {}".format(size, foto.size),
                )

    def test_una_foto_chica_queda_igual(self):

        imagen = make_animal_image(size=(600, 400))

        self.service.optimize(imagen.image, max_width=1200)

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertEqual(foto.size, (600, 400))

    def test_mantiene_la_proporcion(self):

        imagen = make_animal_image(size=(3000, 1000))

        self.service.optimize(imagen.image, max_width=1200)

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertAlmostEqual(foto.size[0] / foto.size[1], 3.0, places=1)

    def test_deja_el_archivo_utilizable(self):

        imagen = make_animal_image(size=(2000, 1500))

        self.service.optimize(imagen.image, max_width=1200)

        imagen.refresh_from_db()
        self.assertTrue(os.path.exists(imagen.image.path))
        self.assertGreater(imagen.image.size, 0)


class GenerateLogoImageTest(ImageServiceTestCase):
    """El posteo final: 1200 de foto dentro de un lienzo de 1400 con marco blanco."""

    def setUp(self):
        super().setUp()
        self.animal = make_animal(nombre="Willy", edad="2 años", sexo="M")

    def build(self, size=(900, 1600), **kwargs):

        from catus.tests.factories import photo_bytes

        return self.service.generate_logo_image(
            self.animal, photo_bytes(size=size),
            nombre_font_size=150,
            posicion_nombre="Izquierda (abajo)",
            posicion_edad_sexo="Izquierda (abajo)",
            **kwargs
        )

    def test_el_posteo_sale_cuadrado(self):

        with Image.open(self.build()) as posteo:
            self.assertEqual(posteo.size, (1400, 1400))

    def test_funciona_con_fotos_de_cualquier_forma(self):

        for size in [(900, 1600), (1600, 900), (1000, 1000), (400, 1600)]:
            with Image.open(self.build(size=size)) as posteo:
                self.assertEqual(posteo.size, (1400, 1400), "falló con {}".format(size))

    def test_respeta_un_recorte_manual(self):

        with Image.open(self.build(crop=(0.0, 0.5, 1.0, 0.5625))) as posteo:
            self.assertEqual(posteo.size, (1400, 1400))

    def test_un_animal_sin_edad_no_rompe(self):

        self.animal.edad = None

        with Image.open(self.build()) as posteo:
            self.assertEqual(posteo.size, (1400, 1400))

    def test_un_nombre_muy_largo_no_rompe(self):

        self.animal.nombre = "Bartolomeo Maximiliano de los Santos"

        with Image.open(self.build()) as posteo:
            self.assertEqual(posteo.size, (1400, 1400))
