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
    """El posteo final: la foto en todo el lienzo de 1400 y la tarjeta encima."""

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


def blancos_por_renglon(posteo, desde_y, hasta_y):
    """Desde y hasta qué x hay blanco puro en esa franja: la tarjeta, sobre una foto gris."""

    pixeles = posteo.convert("RGB").load()
    xs = [x for y in range(desde_y, hasta_y, 4) for x in range(posteo.size[0])
          if all(canal > 245 for canal in pixeles[x, y])]
    return (min(xs), max(xs)) if xs else (None, None)


class EdadYSexoQueEntraTest(ImageServiceTestCase):
    """El renglón de la edad y el sexo, dentro de la tarjeta.

    El ajuste de tamaño de letra cubría sólo el nombre, así que este renglón seguía
    saliéndose: la edad la escribe el rescatista a mano y "aproximadamente 3 años y
    medio - Macho y Hembra" no entraba con el tamaño fijo de siempre. El texto salía
    cortado y no lo veía nadie, porque el posteo lo arma el cron y ahí no hay
    previsualización que mirar.
    """

    EDAD_LARGA = "aproximadamente 3 años y medio"

    def ancho_disponible(self):

        return self.service.ancho_para_el_texto_de_la_tarjeta(self.service.logo_para_la_tarjeta())

    def ancho_dibujado(self, texto, tamano):

        return self.service.ancho_del_texto(texto, self.service.FUENTE_EDAD_SEXO, tamano)

    def texto(self, **kwargs):

        kwargs.setdefault("edad", self.EDAD_LARGA)
        kwargs.setdefault("sexo", "A")

        return self.service.texto_de_edad_y_sexo(make_animal(**kwargs))

    def test_con_la_letra_mas_grande_no_entraba(self):
        """Si esto dejara de ser cierto, el test de acá abajo no mediría nada."""

        self.assertGreater(self.ancho_dibujado(self.texto(), max(self.service.TAMANOS_EDAD_SEXO)), self.ancho_disponible())

    def test_una_edad_larga_entra_en_la_tarjeta(self):

        texto = self.texto()

        tamano = self.service.tamano_de_letra_para_edad_y_sexo(texto)

        self.assertLessEqual(
            self.ancho_dibujado(texto, tamano), self.ancho_disponible(),
            "'{}' se sale de la tarjeta con letra de {}".format(texto, tamano),
        )

    def test_una_edad_corta_va_con_la_letra_mas_grande(self):

        self.assertEqual(
            self.service.tamano_de_letra_para_edad_y_sexo(self.texto(edad="2 años", sexo="M")),
            max(self.service.TAMANOS_EDAD_SEXO),
        )

    def test_un_animal_sin_edad_muestra_el_sexo(self):

        self.assertEqual(self.texto(edad=None, sexo="H"), "Hembra")

    def test_desconocido_no_se_escribe(self):

        self.assertEqual(self.texto(edad="2 años", sexo="D"), "2 años")
        self.assertEqual(self.texto(edad=None, sexo="D"), "")

    def test_la_edad_no_se_mete_en_el_logo(self):
        """Medido sobre el posteo ya armado: el renglón termina antes de que empiece el logo.

        El texto es gris azulado (más azul que rojo) y el logo es negro puro, así que se
        los distingue por color aunque estén en la misma franja.
        """

        from catus.tests.factories import photo_bytes

        animal = make_animal(nombre="Willy", edad=self.EDAD_LARGA, sexo="A")
        medidas = self.service.medidas_de_la_tarjeta(animal)
        x0, y0, x1, y1 = medidas["caja"]
        logo_x = x1 - self.service.TARJETA_PADDING_X - medidas["logo"].size[0]

        with Image.open(self.service.generate_logo_image(animal, photo_bytes(size=(1200, 1200)))) as posteo:
            pixeles = posteo.convert("RGB").load()
            borde = 0
            for y in range(medidas["base_linea"] - 40, medidas["base_linea"] + 2):
                for x in range(x0, x1):
                    r, g, b = pixeles[x, y]
                    if b - r >= 15 and min(r, g, b) < 200:
                        borde = max(borde, x)

        self.assertGreater(borde, 0, "no se encontró el renglón de la edad: el test no mide nada")
        self.assertLess(borde, logo_x, "la edad llega hasta el logo")


class TarjetaTest(ImageServiceTestCase):
    """La tarjeta del posteo: dónde va y cómo se acomoda el nombre."""

    NOMBRE_LARGO = "Bartolomeo Maximiliano de los Santos"

    def posteo(self, animal, **kwargs):

        from catus.tests.factories import photo_bytes

        return Image.open(self.service.generate_logo_image(animal, photo_bytes(size=(1200, 1200)), **kwargs))

    def test_queda_dentro_de_lo_que_muestra_la_grilla(self):
        """La grilla del perfil corta 175 px de cada costado del posteo cuadrado: con el
        diseño anterior mostraba "ngela" y medio logo. Con el nombre y la edad más largos
        que se nos ocurren, la tarjeta no sale de la franja segura."""

        animal = make_animal(nombre=self.NOMBRE_LARGO, edad="aproximadamente 3 años y medio", sexo="A")
        x0, y0, x1, y1 = self.service.medidas_de_la_tarjeta(animal)["caja"]

        with self.posteo(animal) as posteo:
            desde, hasta = blancos_por_renglon(posteo, y0 + 10, y1 - 10)

        self.assertIsNotNone(desde, "no se encontró la tarjeta: el test no mide nada")
        izquierda, derecha = self.service.FRANJA_SEGURA
        self.assertGreaterEqual(desde, izquierda - self.service.TARJETA_BORDE)
        self.assertLessEqual(hasta, derecha + self.service.TARJETA_BORDE)

    def test_va_centrada_abajo(self):

        animal = make_animal(nombre="Willy", edad="2 años", sexo="M")
        x0, y0, x1, y1 = self.service.medidas_de_la_tarjeta(animal)["caja"]

        self.assertEqual(y1, self.service.TARJETA_ABAJO)
        self.assertLessEqual(abs((x0 + x1) / 2 - self.service.LADO_LIENZO_POSTEO / 2), 1)

    def test_los_nombres_se_apoyan_a_la_misma_altura(self):
        """El que reportó el usuario en la maqueta: "Rocco" quedaba más abajo que "Ángela".

        Se ubicaba cada nombre por la tinta de sus letras, y la g de Ángela, que baja del
        renglón, subía todo el nombre. Con la letra del mismo tamaño, la base del nombre y
        el alto de la tarjeta tienen que ser los mismos, tenga o no letras que bajan.
        """

        angela = self.service.medidas_de_la_tarjeta(make_animal(nombre="Ángela", edad="1 año", sexo="H"))
        rocco = self.service.medidas_de_la_tarjeta(make_animal(nombre="Rocco", edad="4 años", sexo="M"))

        self.assertEqual(angela["fuente_nombre"].size, rocco["fuente_nombre"].size)
        self.assertEqual(angela["base_nombre"], rocco["base_nombre"])
        self.assertEqual(angela["caja"][1], rocco["caja"][1], "las tarjetas no miden lo mismo de alto")

    def test_un_nombre_corto_va_con_la_letra_mas_grande(self):

        ancho = self.service.ancho_para_el_texto_de_la_tarjeta(self.service.logo_para_la_tarjeta())

        self.assertEqual(self.service.nombre_en_renglones("Willy", ancho), (max(self.service.TAMANOS_NOMBRE), ["Willy"]))

    def test_dos_palabras_que_entran_van_en_un_renglon(self):

        ancho = self.service.ancho_para_el_texto_de_la_tarjeta(self.service.logo_para_la_tarjeta())

        self.assertEqual(self.service.nombre_en_renglones("Tomy bicolor", ancho)[1], ["Tomy bicolor"])

    def test_un_nombre_larguisimo_pasa_a_dos_renglones_y_entra(self):

        ancho = self.service.ancho_para_el_texto_de_la_tarjeta(self.service.logo_para_la_tarjeta())

        tamano, renglones = self.service.nombre_en_renglones(self.NOMBRE_LARGO, ancho)

        self.assertEqual(len(renglones), 2)
        self.assertEqual(" ".join(renglones), self.NOMBRE_LARGO)
        for renglon in renglones:
            self.assertLessEqual(self.service.ancho_del_nombre(renglon, tamano), ancho)

    def test_sin_edad_ni_sexo_lleva_solo_el_nombre(self):

        animal = make_animal(nombre="Michi", edad=None, sexo="D")

        medidas = self.service.medidas_de_la_tarjeta(animal)

        self.assertIsNone(medidas["fuente_linea"])
        with self.posteo(animal) as posteo:
            self.assertEqual(posteo.size, (1400, 1400))

    def test_las_posiciones_del_diseno_anterior_no_mueven_la_tarjeta(self):
        """Se siguen guardando y pasando, pero la tarjeta va siempre centrada abajo."""

        from catus.tests.factories import photo_bytes

        animal = make_animal(nombre="Willy", edad="2 años", sexo="M")

        arriba = self.service.generate_logo_image(animal, photo_bytes(size=(1200, 1200)),
                                                  nombre_font_size=50, posicion_nombre="Izquierda (arriba)",
                                                  posicion_edad_sexo="Izquierda (arriba)").read()
        abajo = self.service.generate_logo_image(animal, photo_bytes(size=(1200, 1200)),
                                                 nombre_font_size=150, posicion_nombre="Izquierda (abajo)",
                                                 posicion_edad_sexo="Izquierda (abajo)").read()

        self.assertEqual(arriba, abajo)
