"""The mail a rescuer sends the adopter from the contract screen.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_contrato_mail
"""
import importlib
import json
import uuid
from unittest import mock

from django.test import TestCase


class InlineThread:
    """Runs the mail in the test's own thread, so it can be checked."""

    def __init__(self, target):
        self.target = target

    def start(self):
        self.target()


def contrato_views():
    # django_conventions loads the views modules itself: patch the loaded one.
    return importlib.import_module("catus.views.contrato")


class ContractMailTest(TestCase):
    """It took the address, the subject and the HTML from the POST: any account
    (registration is open) mailed whatever it wanted to anyone, from the site's
    own address."""

    def setUp(self):
        from forms_builder.forms import fields
        from forms_builder.forms.models import FieldEntry, Form

        from catus.models import Animal, CatusUser, Contrato, ContratoPersona, EstadoFormulario

        self.owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        animal = Animal.objects.create(nombre="Michi", cargado_por=self.owner, estado="R", tipo="G")

        form = Form.objects.create(title="Pre adopción", slug="pre-adopcion")
        entry = form.entries.create(entry_time="2026-10-31 12:00:00+00:00")
        for label, value in (("Nombre y Apellido", "Ana Adoptante"), ("Email", " ana@example.com ")):
            field = form.fields.create(label=label, field_type=fields.TEXT, visible=True)
            FieldEntry.objects.create(entry=entry, field_id=field.id, value=value)

        self.estado = EstadoFormulario.objects.create(form_entry=entry, gato=animal, estado="R",
                                                      hash=str(uuid.uuid4()))
        self.adoptante = ContratoPersona.objects.create(persona_nombre="Ana Adoptante",
                                                        persona_email="ana@example.com")
        self.contrato = Contrato.objects.create(hash=str(uuid.uuid4()), gato=animal,
                                                estado_formulario=self.estado, adoptante=self.adoptante)
        self.client.force_login(self.owner)

    def send(self, **extra):
        data = {
            "gato_nombre": "Michi", "gato_color": "Negro", "gato_sexo": "M",
            "gato_fecha_nacimiento": "01/01/2025", "gato_edad": "1 año",
            "miembro_felis_catus_nombre": "Refugio", "send_email": "1",
        }
        data.update(extra)
        views = contrato_views()
        with mock.patch.object(views, "Thread", InlineThread), \
                mock.patch.object(views, "send_html_email") as send_html_email:
            response = self.client.post("/formulario/{}/contrato/".format(self.estado.id), data)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content.decode()), send_html_email

    def test_it_goes_only_to_the_forms_adopter_and_as_text(self):
        result, send_html_email = self.send(
            email="cualquiera@example.org",
            subject="Tu cuenta\r\nBcc: muchos@example.org",
            content='Hola <a href="https://phishing.example">entrá acá</a>\n<script>x()</script>',
        )

        self.assertEqual(result["status"], "success")
        send_html_email.assert_called_once()
        subject, content, _from, to = send_html_email.call_args[0]
        self.assertEqual(to, "ana@example.com")
        self.assertEqual(subject, "Tu cuenta Bcc: muchos@example.org")
        self.assertNotIn("<a ", content)
        self.assertNotIn("<script>", content)
        self.assertIn("&lt;a href=", content)
        self.assertIn("<br>", content)

    def test_the_adopters_email_on_the_contract_does_not_count(self):
        # Whoever has the adopter's link can rewrite persona_email; the address the
        # mail goes to is the one in the form.
        self.adoptante.persona_email = "otra@example.org"
        self.adoptante.save()

        result, send_html_email = self.send()

        self.assertEqual(send_html_email.call_args[0][3], "ana@example.com")
        self.assertEqual(send_html_email.call_args[0][0],
                         "Catpuccino Adopciones - Contrato de adopción responsable")

    def test_without_an_email_in_the_form_nothing_is_sent(self):
        from forms_builder.forms.models import FieldEntry

        FieldEntry.objects.filter(value__contains="@").update(value="no tengo")

        result, send_html_email = self.send(email="cualquiera@example.org")

        self.assertEqual(result["status"], "fail")
        send_html_email.assert_not_called()

    def test_another_rescuer_cannot_send_it(self):
        from catus.models import CatusUser

        self.client.force_login(CatusUser.objects.create(username="otro", email="otro@example.com"))
        with mock.patch.object(contrato_views(), "send_html_email") as send_html_email:
            response = self.client.post("/formulario/{}/contrato/".format(self.estado.id),
                                        {"send_email": "1", "email": "x@example.org"})

        self.assertEqual(response.status_code, 403)
        send_html_email.assert_not_called()
