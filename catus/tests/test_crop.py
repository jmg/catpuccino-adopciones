"""Tests del recorte cuadrado para Instagram."""
from PIL import Image, ImageDraw

from django.test import TestCase

from catus.services.images import ImageService
from catus.forms import AnimalImageForm
from catus.models import AnimalImage
from catus.tests.factories import photo_bytes, uploaded_photo
from catus.utils import clean_crop, has_crop_fields, parse_crop


def con_sujeto(size, box):
    """Foto gris con un sujeto texturado en box=(x0, y0, x1, y1)."""

    photo = Image.new("RGB", size, (128, 128, 128))
    draw = ImageDraw.Draw(photo)
    x0, y0, x1, y1 = box

    for x in range(int(x0), int(x1), 8):
        draw.line([(x, y0), (x, y1)], fill=(255, 255, 255), width=2)
    for y in range(int(y0), int(y1), 8):
        draw.line([(x0, y), (x1, y)], fill=(30, 30, 30), width=2)

    return photo


def como_archivo(image):
    from io import BytesIO

    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90)
    buffer.seek(0)
    return buffer


class CleanCropTest(TestCase):
    """El recorte llega del navegador: no se puede confiar en los valores."""

    def test_acepta_un_recorte_valido(self):

        self.assertEqual(clean_crop([0.1, 0.2, 0.5, 0.5]), (0.1, 0.2, 0.5, 0.5))

    def test_acepta_numeros_como_texto(self):

        self.assertEqual(clean_crop(["0.1", "0.2", "0.5", "0.5"]), (0.1, 0.2, 0.5, 0.5))

    def test_acepta_la_foto_entera(self):

        self.assertEqual(clean_crop([0, 0, 1, 1]), (0.0, 0.0, 1.0, 1.0))

    def test_tolera_el_redondeo_del_selector(self):

        self.assertIsNotNone(clean_crop([0, 0, 1.0005, 1.0005]))

    def test_rechaza_valores_no_numericos(self):

        for invalido in (None, ["a", "b", "c", "d"], [0.1, None, 0.5, 0.5], [0.1, 0.2]):
            self.assertIsNone(clean_crop(invalido), "deberia rechazar {}".format(invalido))

    def test_rechaza_tamanos_imposibles(self):

        self.assertIsNone(clean_crop([0.1, 0.1, 0, 0.5]))
        self.assertIsNone(clean_crop([0.1, 0.1, -0.5, 0.5]))

    def test_rechaza_recortes_fuera_de_la_foto(self):

        self.assertIsNone(clean_crop([-0.5, 0.1, 0.5, 0.5]))
        self.assertIsNone(clean_crop([0.8, 0.1, 0.5, 0.5]))
        self.assertIsNone(clean_crop([0.1, 0.8, 0.5, 0.5]))

    def test_rechaza_infinitos_y_nan(self):
        """NaN pasa cualquier comparacion sin fallar: hay que descartarlo aparte."""

        self.assertIsNone(clean_crop([0.1, 0.2, float("inf"), 0.5]))
        self.assertIsNone(clean_crop([float("-inf"), 0.2, 0.5, 0.5]))
        self.assertIsNone(clean_crop([0.1, 0.2, float("nan"), 0.5]))
        self.assertIsNone(clean_crop(["NaN", "0", "0.5", "0.5"]))


class ParseCropTest(TestCase):

    def setUp(self):
        self.post = {"crop_x_7": "0.1", "crop_y_7": "0.2", "crop_w_7": "0.5", "crop_h_7": "0.5"}

    def test_lee_el_recorte_de_una_imagen(self):

        self.assertEqual(parse_crop(self.post, "_7"), (0.1, 0.2, 0.5, 0.5))

    def test_otra_imagen_no_tiene_recorte(self):

        self.assertIsNone(parse_crop(self.post, "_9"))

    def test_distingue_vacio_de_ausente(self):
        """Vacio = volver al automatico. Ausente = respetar lo guardado."""

        vacio = {"crop_x_7": "", "crop_y_7": "", "crop_w_7": "", "crop_h_7": ""}

        self.assertTrue(has_crop_fields(vacio, "_7"))
        self.assertIsNone(parse_crop(vacio, "_7"))
        self.assertFalse(has_crop_fields(self.post, "_9"))


class CropBoxTest(TestCase):

    def setUp(self):
        self.service = ImageService()

    def test_convierte_fracciones_a_pixeles(self):

        img = Image.new("RGB", (1000, 600))

        self.assertEqual(self.service.crop_box_from_fractions(img, (0.2, 0.0, 0.6, 1.0)), (200, 0, 800, 600))

    def test_recorta_siempre_cuadrado(self):

        img = Image.new("RGB", (800, 1422))

        box = self.service.crop_box_from_fractions(img, (0.0, 0.13, 1.0, 0.5626))

        self.assertEqual(box[2] - box[0], box[3] - box[1])

    def test_no_se_sale_de_la_foto(self):

        img = Image.new("RGB", (1000, 600))

        box = self.service.crop_box_from_fractions(img, (0.8, 0.0, 0.5, 1.0))

        self.assertLessEqual(box[2], 1000)
        self.assertLessEqual(box[3], 600)

    def test_descarta_un_recorte_de_area_cero(self):

        img = Image.new("RGB", (1000, 600))

        self.assertIsNone(self.service.crop_box_from_fractions(img, (0.5, 0.5, 0.0, 0.0)))


class CropToSquareTest(TestCase):

    def setUp(self):
        self.service = ImageService()

    def test_siempre_devuelve_el_cuadrado_pedido(self):

        casos = [
            ((1000, 600), (0.2, 0.0, 0.6, 1.0)),
            ((1000, 600), None),
            ((600, 1000), None),
            ((900, 900), None),
        ]

        for size, crop in casos:
            salida = self.service.crop_to_square(Image.new("RGB", size), 1200, crop=crop)

            self.assertEqual(salida.size, (1200, 1200), "fallo con {} y crop={}".format(size, crop))

    def test_un_recorte_invalido_cae_al_automatico(self):

        salida = self.service.crop_to_square(Image.new("RGB", (1000, 600)), 1200, crop=(0.5, 0.5, 0.0, 0.0))

        self.assertEqual(salida.size, (1200, 1200))

    def test_centrada_centra_de_verdad(self):
        """Antes cortaba a 1/4 del lado largo, no a la mitad."""

        photo = Image.new("RGB", (600, 1400), (0, 0, 0))
        ImageDraw.Draw(photo).rectangle([0, 690, 600, 710], fill=(255, 0, 0))

        salida = self.service.crop_to_square(photo, 1200, centered=True, crop=None)

        franja = [salida.getpixel((600, y))[0] for y in range(560, 640)]
        self.assertGreater(max(franja), 200, "la franja del centro quedo fuera del recorte")


class SuggestCropTest(TestCase):

    def setUp(self):
        self.service = ImageService()

    def contiene(self, crop, size, box):

        if crop is None:
            return False

        width, height = size
        x0, y0, x1, y1 = box
        left, top = crop[0] * width, crop[1] * height
        right, bottom = left + crop[2] * width, top + crop[3] * height

        return left <= x0 and right >= x1 and top <= y0 and bottom >= y1

    def test_encuentra_al_sujeto_donde_este(self):

        casos = [
            ("derecha", (1200, 600), (900, 100, 1080, 500)),
            ("izquierda", (1200, 600), (120, 100, 300, 500)),
            ("arriba", (600, 1400), (100, 150, 500, 520)),
            ("abajo", (600, 1400), (100, 900, 500, 1270)),
        ]

        for nombre, size, box in casos:
            crop = self.service.suggest_crop(como_archivo(con_sujeto(size, box)))

            self.assertTrue(
                self.contiene(crop, size, box),
                "el sujeto de {} quedo cortado: crop={}".format(nombre, crop),
            )

    def test_el_recorte_nunca_se_sale_de_la_foto(self):

        for size, box in [((1200, 600), (1050, 50, 1190, 550)), ((600, 1400), (50, 1250, 550, 1390))]:
            crop = self.service.suggest_crop(como_archivo(con_sujeto(size, box)))

            self.assertGreaterEqual(crop[0], 0)
            self.assertGreaterEqual(crop[1], 0)
            self.assertLessEqual(crop[0] + crop[2], 1.0001)
            self.assertLessEqual(crop[1] + crop[3], 1.0001)

    def test_una_foto_cuadrada_no_necesita_recorte(self):

        self.assertIsNone(self.service.suggest_crop(photo_bytes(size=(800, 800))))

    def test_una_foto_plana_se_recorta_al_centro(self):

        crop = self.service.suggest_crop(photo_bytes(size=(1200, 600)))

        self.assertAlmostEqual(crop[0], 0.25, delta=0.06)

    def test_no_rompe_con_fotos_degeneradas(self):

        from io import BytesIO

        self.assertIsNone(self.service.suggest_crop(photo_bytes(size=(1, 1))))
        self.assertIsNone(self.service.suggest_crop(photo_bytes(size=(500, 1))))
        self.assertIsNone(self.service.suggest_crop(BytesIO(b"no soy una imagen")))

    def test_la_sugerencia_sirve_para_recortar(self):

        photo = con_sujeto((1200, 600), (800, 150, 1100, 450))

        crop = self.service.suggest_crop(como_archivo(photo))
        salida = self.service.crop_to_square(photo, 1200, crop=crop)

        self.assertEqual(salida.size, (1200, 1200))


class AnimalImageFormCropTest(TestCase):
    """Un recorte roto no puede impedir que se guarde el animal."""

    def test_guarda_un_recorte_valido(self):

        form = AnimalImageForm(
            data={"crop_x": "0.25", "crop_y": "0", "crop_w": "0.5", "crop_h": "0.5"},
            files={"image": uploaded_photo()},
        )

        self.assertTrue(form.is_valid(), form.errors)
        imagen = form.save(commit=False)
        self.assertEqual(imagen.get_crop(), (0.25, 0.0, 0.5, 0.5))

    def test_un_recorte_roto_se_ignora_pero_deja_guardar(self):

        for malo in ["no-es-un-numero", "NaN", "1e999", "<script>", "0,5"]:
            form = AnimalImageForm(
                data={"crop_x": malo, "crop_y": "0", "crop_w": "0.5", "crop_h": "0.5"},
                files={"image": uploaded_photo()},
            )

            self.assertTrue(form.is_valid(), "el recorte '{}' invalido el form: {}".format(malo, form.errors))
            self.assertIsNone(form.save(commit=False).get_crop())

    def test_un_recorte_fuera_de_la_foto_se_anula(self):

        form = AnimalImageForm(
            data={"crop_x": "0.9", "crop_y": "0.2", "crop_w": "0.5", "crop_h": "0.5"},
            files={"image": uploaded_photo()},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save(commit=False).get_crop())


class AnimalImageCropFieldsTest(TestCase):

    def test_get_crop_devuelve_none_si_falta_algun_campo(self):

        imagen = AnimalImage(crop_x=0.1, crop_y=0.2, crop_w=0.5, crop_h=None)

        self.assertIsNone(imagen.get_crop())

    def test_set_crop_ida_y_vuelta(self):

        imagen = AnimalImage()

        imagen.set_crop((0.1, 0.2, 0.5, 0.5))
        self.assertEqual(imagen.get_crop(), (0.1, 0.2, 0.5, 0.5))

        imagen.set_crop(None)
        self.assertIsNone(imagen.get_crop())
        self.assertIsNone(imagen.crop_x)
