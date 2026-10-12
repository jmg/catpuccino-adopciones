"""Las fotos de los formularios de pre-adopción se achican antes de guardarse.

Corre con ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.tests.test_subidas
"""
import io
import shutil
import tempfile

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils.datastructures import MultiValueDict
from PIL import Image

from catus.services.images import UPLOAD_MAX_SIDE, shrink_uploaded_image, shrink_uploads

ORIENTATION = 274  # tag EXIF


def photo(width, height, fmt="JPEG", name="foto.jpg", mode="RGB", orientation=None, quality=95):
    """Una subida con una imagen con ruido: el ruido es lo que hace pesadas a las fotos reales."""
    image = Image.effect_noise((width, height), 90).convert(mode)
    out = io.BytesIO()
    kwargs = {}
    if fmt == "JPEG":
        kwargs["quality"] = quality
        if orientation:
            exif = Image.Exif()
            exif[ORIENTATION] = orientation
            kwargs["exif"] = exif
    image.save(out, fmt, **kwargs)
    return SimpleUploadedFile(name, out.getvalue(), content_type="image/jpeg")


def opened(upload):
    upload.seek(0)
    image = Image.open(io.BytesIO(upload.read()))
    image.load()
    return image


class AchicarFotoSubidaTest(SimpleTestCase):

    def test_una_foto_grande_se_achica_y_conserva_nombre_y_formato(self):
        upload = photo(4000, 3000)
        shrunk = shrink_uploaded_image(upload)

        self.assertIsNot(shrunk, upload)
        self.assertEqual(shrunk.name, "foto.jpg")
        self.assertLess(shrunk.size, upload.size * 0.9)
        image = opened(shrunk)
        self.assertEqual(image.format, "JPEG")
        self.assertEqual(max(image.size), UPLOAD_MAX_SIDE)
        self.assertEqual(image.size, (1920, 1440))

    def test_la_rotacion_del_celular_queda_en_los_pixeles(self):
        # Guardada apaisada, para verse vertical (orientación EXIF 6).
        shrunk = shrink_uploaded_image(photo(4000, 2000, orientation=6))

        image = opened(shrunk)
        self.assertEqual(image.size, (960, 1920))
        self.assertNotIn(ORIENTATION, image.getexif())

    def test_una_foto_que_ya_es_chica_no_se_toca(self):
        upload = photo(800, 600, quality=70)
        self.assertIs(shrink_uploaded_image(upload), upload)

    def test_un_png_conserva_la_transparencia(self):
        upload = photo(3000, 3000, fmt="PNG", name="captura.png", mode="RGBA")
        shrunk = shrink_uploaded_image(upload)

        image = opened(shrunk)
        self.assertEqual(shrunk.name, "captura.png")
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.size, (1920, 1920))

    def test_un_jpg_que_en_realidad_es_png_sigue_siendo_png(self):
        upload = photo(3000, 2000, fmt="PNG", name="foto.jpg")
        image = opened(shrink_uploaded_image(upload))
        self.assertEqual(image.format, "PNG")

    def test_lo_que_no_es_una_foto_legible_pasa_igual(self):
        for name, data in [
            ("contrato.pdf", b"%PDF-1.4\n" + b"x" * 5000),
            ("foto.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 5000),
            ("video.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 5000),
        ]:
            upload = SimpleUploadedFile(name, data)
            self.assertIs(shrink_uploaded_image(upload), upload, name)
            self.assertEqual(upload.read(), data, name)  # y se sigue pudiendo leer entera

    def test_una_foto_cortada_pasa_igual_en_vez_de_fallar(self):
        whole = photo(3000, 2000)
        upload = SimpleUploadedFile("rota.jpg", whole.read()[: whole.size // 3])
        self.assertIs(shrink_uploaded_image(upload), upload)

    def test_sobreviven_todos_los_campos_y_archivos(self):
        files = MultiValueDict({
            "field_1": [photo(4000, 3000, name="a.jpg"), photo(4000, 3000, name="b.jpg")],
            "field_2": [SimpleUploadedFile("nota.pdf", b"%PDF-1.4 hola")],
        })
        shrunk = shrink_uploads(files)

        self.assertEqual(sorted(shrunk.keys()), ["field_1", "field_2"])
        self.assertEqual([f.name for f in shrunk.getlist("field_1")], ["a.jpg", "b.jpg"])
        self.assertEqual(shrunk["field_2"].name, "nota.pdf")
        self.assertIsNone(shrink_uploads(None))


class FormularioPreAdopcionConFotoTest(TestCase):
    """El camino completo: un formulario de pre-adopción enviado con una foto del celular."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

        from forms_builder.forms import fields
        from forms_builder.forms.models import Form

        from catus.models import Animal, CatusUser

        owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.animal = Animal.objects.create(nombre="Michi", cargado_por=owner, estado="D", tipo="G")

        self.form = Form.objects.create(title="Pre adopción", slug="pre-adopcion")
        # El primer campo lleva el id del animal: AdoptionService lo lee de ahí.
        self.animal_field = self.form.fields.create(label="Nombre del gato a adoptar", field_type=fields.TEXT, visible=True)
        self.name_field = self.form.fields.create(label="Nombre y Apellido", field_type=fields.TEXT, visible=True)
        self.email_field = self.form.fields.create(label="Email", field_type=fields.EMAIL, visible=True)
        self.photo_field = self.form.fields.create(label="Foto 1", field_type=fields.FILE, visible=True)

    def test_la_foto_guardada_es_la_achicada(self):
        from forms_builder.forms.models import FieldEntry

        from catus.models import EstadoFormulario

        upload = photo(4032, 3024, name="IMG_1234.jpg")
        # forms_builder nombra cada input con el slug de su campo.
        response = self.client.post(f"/pre-adopcion/?id={self.animal.id}", {
            self.animal_field.slug: str(self.animal.id),
            self.name_field.slug: "Ana Pérez",
            self.email_field.slug: "ana@example.com",
            self.photo_field.slug: upload,
        })

        self.assertEqual(response.status_code, 200)
        entry = FieldEntry.objects.get(field_id=self.photo_field.id)
        self.assertRegex(entry.value, r"^forms/[0-9a-f-]{36}/IMG_1234\.jpg$")  # mismo nombre
        with open(f"{self.media}/{entry.value}", "rb") as stored:
            data = stored.read()
        self.assertLess(len(data), upload.size * 0.9)
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.format, "JPEG")
        self.assertEqual(image.size, (1920, 1440))

        # Lo que viene después de guardar sigue pasando: el formulario se registra y se manda por mail.
        self.assertEqual(EstadoFormulario.objects.get().gato, self.animal)
        self.assertTrue(any("pre-adopción" in m.subject for m in mail.outbox))
