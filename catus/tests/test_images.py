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

        for size in [(3024, 4032), (2000, 3000), (4032, 3024), (3000, 2191)]:
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


class EdadYSexoQueEntraTest(ImageServiceTestCase):
    """El renglón de abajo del posteo: la edad y el sexo.

    El ajuste de tamaño de letra cubría sólo el nombre, así que este renglón seguía
    saliéndose del lienzo: la edad la escribe el rescatista a mano y "aproximadamente
    3 años y medio - Macho y Hembra" mide 1661 px con los 60 fijos de siempre, sobre
    1220 de ancho útil. El texto salía cortado por la derecha y no lo veía nadie,
    porque el posteo lo arma el cron y ahí no hay previsualización que mirar.
    """

    EDAD_LARGA = "aproximadamente 3 años y medio"

    #el marco blanco del lienzo: la foto va de 100 a 1300
    BORDE_DE_LA_FOTO = 1300

    def ancho_disponible(self):

        return (
            self.service.LADO_LIENZO_POSTEO
            - self.service.MARGEN_TEXTO_EDAD_SEXO_X
            - self.service.MARGEN_BORDE_POSTEO
        )

    def ancho_dibujado(self, texto, tamano):

        return self.service.ancho_del_texto(texto, self.service.FUENTE_EDAD_SEXO, tamano)

    def texto(self, **kwargs):

        kwargs.setdefault("edad", self.EDAD_LARGA)
        kwargs.setdefault("sexo", "A")

        return self.service.texto_de_edad_y_sexo(make_animal(**kwargs))

    def test_con_los_60_de_siempre_no_entraba(self):
        """Si esto dejara de ser cierto, el test de acá abajo no mediría nada."""

        self.assertGreater(self.ancho_dibujado(self.texto(), 60), self.ancho_disponible())

    def test_una_edad_larga_entra_en_el_lienzo(self):

        texto = self.texto()

        tamano = self.service.tamano_de_letra_para_edad_y_sexo(texto)

        self.assertLessEqual(
            self.service.MARGEN_TEXTO_EDAD_SEXO_X + self.ancho_dibujado(texto, tamano),
            self.service.LADO_LIENZO_POSTEO - self.service.MARGEN_BORDE_POSTEO,
            "'{}' se sale del lienzo con letra de {}".format(texto, tamano),
        )

    def test_una_edad_corta_conserva_el_tamano_de_siempre(self):
        """Achicar el renglón que ya entraba cambiaría el posteo de todos los animales."""

        self.assertEqual(
            self.service.tamano_de_letra_para_edad_y_sexo(self.texto(edad="2 años", sexo="M")),
            60,
        )

    def test_un_animal_sin_edad_muestra_el_sexo(self):

        self.assertEqual(self.texto(edad=None, sexo="H"), "Hembra")

    def borde_derecho_del_texto(self, posteo, desde_y, hasta_y):
        """Hasta qué x llega el texto blanco, dentro de la foto (que va de 100 a 1300)."""

        pixeles = posteo.convert("RGB").load()

        borde = 0
        for y in range(desde_y, hasta_y):
            for x in range(100, self.BORDE_DE_LA_FOTO):
                if all(canal > 200 for canal in pixeles[x, y]):
                    borde = max(borde, x)

        return borde

    def test_la_edad_no_sale_cortada_en_el_posteo(self):
        """Medido sobre el posteo ya armado: el texto que se pasa llega hasta el borde.

        La foto va sobre negro y el renglón arriba justamente para que el único blanco
        de esa franja sea la edad: abajo a la derecha está el círculo blanco del logo,
        que llega hasta el borde siempre y no mediría nada.
        """

        from catus.tests.factories import photo_bytes

        animal = make_animal(nombre="Willy", edad=self.EDAD_LARGA, sexo="A")

        posteo = self.service.generate_logo_image(
            animal, photo_bytes(size=(1200, 1200), color=(0, 0, 0)),
            nombre_font_size=150,
            posicion_nombre="Izquierda (arriba)",
            posicion_edad_sexo="Izquierda (arriba)",
        )

        #la barra del nombre termina en y=280 y el renglón de la edad arranca en 305
        with Image.open(posteo) as imagen:
            borde = self.borde_derecho_del_texto(imagen, 300, 390)

        self.assertGreater(borde, 0, "no se encontró el renglón de la edad: el test no mide nada")
        self.assertLess(
            borde, self.BORDE_DE_LA_FOTO - 10,
            "la edad llega al borde de la foto: salió cortada",
        )
