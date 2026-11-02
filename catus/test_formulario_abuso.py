"""What the anonymous adoption forms accept from anyone, and whom they mail.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_formulario_abuso
"""
import shutil
import tempfile
from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from catus.test_login_throttle import fake_memcached
from catus.views import adoption

VISITOR = "190.2.3.4"


class AdoptionFormAbuseTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)

        from forms_builder.forms import fields
        from forms_builder.forms.models import Form

        from catus.models import Animal, CatusUser

        owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.animal = Animal.objects.create(nombre="Michi", cargado_por=owner, estado="D", tipo="G")

        self.form = Form.objects.create(title="Pre adopción", slug="pre-adopcion", response="Recibido, gracias")
        # The cats' form as it is in forms.sql: the first field holds the animal's id,
        # and Email is free text there. The first two photos are the ones it asks for.
        self.animal_field = self.form.fields.create(label="Nombre del gato a adoptar", field_type=fields.TEXT, visible=True)
        self.name_field = self.form.fields.create(label="Nombre y Apellido", field_type=fields.TEXT, visible=True)
        self.email_field = self.form.fields.create(label="Email", field_type=fields.TEXT, visible=True)
        self.photo_fields = [
            self.form.fields.create(label="Fotos Protección ({})".format(n), field_type=fields.FILE, visible=True,
                                    required=n < 3)
            for n in (1, 2, 3)
        ]

    def submit(self, email="ana@example.com", forwarded=VISITOR, photo_size=1000, **extra):
        data = {
            self.animal_field.slug: str(self.animal.id),
            self.name_field.slug: "Ana Pérez",
            self.email_field.slug: email,
        }
        for field in self.photo_fields:
            data[field.slug] = SimpleUploadedFile("foto.jpg", b"x" * photo_size, content_type="image/jpeg")
        data.update(extra)
        return self.client.post("/pre-adopcion/?id={}".format(self.animal.id), data, HTTP_X_FORWARDED_FOR=forwarded)

    def stored(self):
        from catus.models import EstadoFormulario

        return EstadoFormulario.objects.count()

    def receipts(self):
        return [m for m in mail.outbox if m.subject == "Catpuccino Adopciones - Formulario Recibido"]

    def test_a_real_adopter_with_the_photos_gets_through(self):
        response = self.submit()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recibido, gracias")
        self.assertEqual(self.stored(), 1)
        self.assertEqual(self.receipts()[0].to, ["ana@example.com"])
        self.assertTrue(any("pre-adopción" in m.subject for m in mail.outbox))

    def test_the_form_carries_the_honeypot_and_the_limit(self):
        page = self.client.get("/pre-adopcion/?id={}".format(self.animal.id)).content.decode()

        self.assertIn('name="sitio_web"', page)
        self.assertIn("total > {}".format(adoption.FORM_MAX_BYTES), page)
        self.assertIn('onsubmit="return prepareSubmit(this);"', page)

    def test_six_phone_photos_fit_in_the_limit(self):
        # The dogs' form: six photos of about 6 MB, the size of a phone's.
        self.assertGreaterEqual(adoption.FORM_MAX_BYTES, 6 * 6 * 1024 * 1024)

    def test_the_honeypot_looks_fine_and_nothing_happens(self):
        response = self.submit(**{adoption.HONEYPOT_FIELD: "https://spam.example"})

        self.assertContains(response, "Recibido, gracias")
        self.assertEqual(self.stored(), 0)
        self.assertEqual(mail.outbox, [])

    def test_a_visitor_is_limited_per_hour_and_a_forged_header_does_not_help(self):
        for i in range(adoption.FORM_MAX_PER_HOUR):
            self.assertContains(self.submit(forwarded="9.9.9.{}, {}".format(i, VISITOR)), "Recibido, gracias")

        response = self.submit(forwarded="8.8.8.8, " + VISITOR)

        self.assertContains(response, "demasiados formularios")
        self.assertEqual(self.stored(), adoption.FORM_MAX_PER_HOUR)

    def test_the_limit_is_per_visitor(self):
        for _ in range(adoption.FORM_MAX_PER_HOUR):
            self.submit()

        self.assertContains(self.submit(forwarded="190.9.9.9"), "Recibido, gracias")

    def test_too_much_weight_is_refused_with_a_message_and_spends_no_attempt(self):
        with mock.patch.object(adoption, "FORM_MAX_BYTES", 10 * 1000):
            response = self.submit(photo_size=5000)

        self.assertContains(response, "pesan demasiado")
        self.assertEqual(self.stored(), 0)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(adoption.throttle.count("adoption-form", VISITOR), 0)

    def test_the_receipt_goes_only_to_one_valid_address(self):
        for typed in ("no es un mail", "uno@example.com, otro@example.com", "uno@example.com\nBcc: otro@example.com"):
            mail.outbox.clear()

            self.submit(email=typed, forwarded="190.9.9.9")

            self.assertEqual(self.receipts(), [], typed)
            self.assertTrue(any("pre-adopción" in m.subject for m in mail.outbox), typed)

    def test_one_mailbox_gets_few_receipts_even_from_many_addresses(self):
        for i in range(adoption.RECEIPTS_MAX_PER_DAY + 3):
            self.submit(email="victima@example.com", forwarded="190.3.3.{}".format(i + 1))
        self.submit(email="VICTIMA@example.com", forwarded="190.4.4.4")

        self.assertEqual(len(self.receipts()), adoption.RECEIPTS_MAX_PER_DAY)
        # The application itself still goes in, and to the rescuer.
        self.assertEqual(self.stored(), adoption.RECEIPTS_MAX_PER_DAY + 4)

    def test_without_memcached_the_form_keeps_working(self):
        with mock.patch("catus.services.throttle._memcached", side_effect=OSError("refused")):
            self.assertContains(self.submit(), "Recibido, gracias")

        self.assertEqual(self.stored(), 1)
