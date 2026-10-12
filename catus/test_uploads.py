"""Photos attached to the adoption forms are shrunk before they are stored.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_uploads
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

ORIENTATION = 274  # EXIF tag


def photo(width, height, fmt="JPEG", name="foto.jpg", mode="RGB", orientation=None, quality=95):
    """An upload holding a noisy picture: noise is what makes real photos heavy."""
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


class ShrinkUploadedImageTest(SimpleTestCase):

    def test_a_large_photo_is_shrunk_keeping_its_name_and_format(self):
        upload = photo(4000, 3000)
        shrunk = shrink_uploaded_image(upload)

        self.assertIsNot(shrunk, upload)
        self.assertEqual(shrunk.name, "foto.jpg")
        self.assertLess(shrunk.size, upload.size * 0.9)
        image = opened(shrunk)
        self.assertEqual(image.format, "JPEG")
        self.assertEqual(max(image.size), UPLOAD_MAX_SIDE)
        self.assertEqual(image.size, (1920, 1440))

    def test_the_phone_rotation_is_baked_into_the_pixels(self):
        # Stored landscape, meant to be seen portrait (EXIF orientation 6).
        shrunk = shrink_uploaded_image(photo(4000, 2000, orientation=6))

        image = opened(shrunk)
        self.assertEqual(image.size, (960, 1920))
        self.assertNotIn(ORIENTATION, image.getexif())

    def test_a_photo_that_is_already_small_is_left_alone(self):
        upload = photo(800, 600, quality=70)
        self.assertIs(shrink_uploaded_image(upload), upload)

    def test_a_png_keeps_its_transparency(self):
        upload = photo(3000, 3000, fmt="PNG", name="captura.png", mode="RGBA")
        shrunk = shrink_uploaded_image(upload)

        image = opened(shrunk)
        self.assertEqual(shrunk.name, "captura.png")
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.size, (1920, 1920))

    def test_a_jpg_that_is_really_a_png_stays_a_png(self):
        upload = photo(3000, 2000, fmt="PNG", name="foto.jpg")
        image = opened(shrink_uploaded_image(upload))
        self.assertEqual(image.format, "PNG")

    def test_what_is_not_a_readable_photo_passes_through(self):
        for name, data in [
            ("contrato.pdf", b"%PDF-1.4\n" + b"x" * 5000),
            ("foto.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 5000),
            ("video.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 5000),
        ]:
            upload = SimpleUploadedFile(name, data)
            self.assertIs(shrink_uploaded_image(upload), upload, name)
            self.assertEqual(upload.read(), data, name)  # and it can still be read whole

    def test_a_truncated_photo_passes_through_instead_of_failing(self):
        whole = photo(3000, 2000)
        upload = SimpleUploadedFile("rota.jpg", whole.read()[: whole.size // 3])
        self.assertIs(shrink_uploaded_image(upload), upload)

    def test_every_field_and_every_file_survives(self):
        files = MultiValueDict({
            "field_1": [photo(4000, 3000, name="a.jpg"), photo(4000, 3000, name="b.jpg")],
            "field_2": [SimpleUploadedFile("nota.pdf", b"%PDF-1.4 hola")],
        })
        shrunk = shrink_uploads(files)

        self.assertEqual(sorted(shrunk.keys()), ["field_1", "field_2"])
        self.assertEqual([f.name for f in shrunk.getlist("field_1")], ["a.jpg", "b.jpg"])
        self.assertEqual(shrunk["field_2"].name, "nota.pdf")
        self.assertIsNone(shrink_uploads(None))


class PreAdoptionFormUploadTest(TestCase):
    """The whole path: a pre-adoption form posted with a phone photo."""

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
        # The first field holds the animal's id: AdoptionService reads it from there.
        self.animal_field = self.form.fields.create(label="Nombre del gato a adoptar", field_type=fields.TEXT, visible=True)
        self.name_field = self.form.fields.create(label="Nombre y Apellido", field_type=fields.TEXT, visible=True)
        self.email_field = self.form.fields.create(label="Email", field_type=fields.EMAIL, visible=True)
        self.photo_field = self.form.fields.create(label="Foto 1", field_type=fields.FILE, visible=True)

    def test_the_stored_photo_is_the_shrunk_one(self):
        from forms_builder.forms.models import FieldEntry

        from catus.models import EstadoFormulario

        upload = photo(4032, 3024, name="IMG_1234.jpg")
        # forms_builder names each input after its field's slug.
        response = self.client.post(f"/pre-adopcion/?id={self.animal.id}", {
            self.animal_field.slug: str(self.animal.id),
            self.name_field.slug: "Ana Pérez",
            self.email_field.slug: "ana@example.com",
            self.photo_field.slug: upload,
        })

        self.assertEqual(response.status_code, 200)
        entry = FieldEntry.objects.get(field_id=self.photo_field.id)
        self.assertRegex(entry.value, r"^forms/[0-9a-f-]{36}/IMG_1234\.jpg$")  # same name
        with open(f"{self.media}/{entry.value}", "rb") as stored:
            data = stored.read()
        self.assertLess(len(data), upload.size * 0.9)
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.format, "JPEG")
        self.assertEqual(image.size, (1920, 1440))

        # Everything after the save still happens: the entry is filed and mailed.
        self.assertEqual(EstadoFormulario.objects.get().gato, self.animal)
        self.assertTrue(any("pre-adopción" in m.subject for m in mail.outbox))
