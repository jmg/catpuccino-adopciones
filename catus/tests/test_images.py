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
    """Achicar la foto recién subida.

    Hay tres cosas en tensión y las tres importan: no guardar archivos enormes, no
    agrandar (agrandar no agrega detalle y pesa más), y no bajar el lado corto por
    debajo de lo que necesita el cuadrado de Instagram, que se recorta justo de ahí.
    """

    def optimizada(self, size, max_width=1200):

        imagen = make_animal_image(size=size)
        self.service.optimize(imagen.image, max_width=max_width)
        imagen.refresh_from_db()

        with Image.open(imagen.image.path) as foto:
            return foto.size

    def test_achica_una_foto_grande(self):

        self.assertEqual(self.optimizada((3000, 2000)), (1800, 1200))

    def test_nunca_agranda(self):
        """Escalar siempre por el ancho estiraba las verticales de celular."""

        for size in [(1080, 1920), (600, 400), (1200, 1200), (900, 1600)]:
            resultado = self.optimizada(size)

            self.assertLessEqual(resultado[0], size[0], "agrandó el ancho de {}".format(size))
            self.assertLessEqual(resultado[1], size[1], "agrandó el alto de {}".format(size))

    def test_no_baja_del_cuadrado_que_pide_instagram(self):
        """El posteo recorta un cuadrado del lado corto.

        Achicar por el lado largo a secas dejaba una vertical de celular en 675x1200,
        y después el posteo estiraba 675 hasta 1200: se publicaba más borroso que antes.
        """

        for size in [(3024, 4032), (2000, 3000), (4032, 3024)]:
            resultado = self.optimizada(size)

            self.assertGreaterEqual(
                min(resultado), self.service.LADO_CUADRADO_IG,
                "{} quedó en {}: el cuadrado de IG va a salir estirado".format(size, resultado),
            )

    def test_una_foto_con_el_lado_corto_chico_se_deja_como_está(self):
        """Si ya venía por debajo del cuadrado, estirarla no aporta nada."""

        self.assertEqual(self.optimizada((1080, 1920)), (1080, 1920))

    def test_una_foto_chica_queda_igual(self):

        self.assertEqual(self.optimizada((600, 400)), (600, 400))

    def test_una_panoramica_tiene_techo(self):
        """Respetar el lado corto no puede terminar guardando una foto gigante."""

        resultado = self.optimizada((5000, 1000))

        self.assertLessEqual(max(resultado), self.service.TOPE_LADO_LARGO)

    def test_mantiene_la_proporcion(self):

        resultado = self.optimizada((3000, 1000))

        self.assertAlmostEqual(resultado[0] / resultado[1], 3.0, places=1)

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
