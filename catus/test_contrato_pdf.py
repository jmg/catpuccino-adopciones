"""The filled-in contract, which holds the adopter's DNI.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_contrato_pdf
"""
import importlib
import json
import os
import shutil
import tempfile
import time
import uuid
from unittest import mock

from django.conf import settings
from django.core import signing
from django.test import TestCase, override_settings

from catus.services import contrato as service


class InlineThread:

    def __init__(self, target):
        self.target = target

    def start(self):
        self.target()


class ContractPdfTest(TestCase):

    def setUp(self):
        # A blank contract in a folder of its own: this writes under <static>/contrato/.
        self.static = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.static, ignore_errors=True)
        os.mkdir(os.path.join(self.static, "contrato"))
        shutil.copy(os.path.join(settings.BASE_DIR, "catus", "static", "contrato", "contrato.pdf"),
                    os.path.join(self.static, "contrato"))
        override = override_settings(STATICFILES_DIRS=[self.static])
        override.enable()
        self.addCleanup(override.disable)

        from catus.models import Animal, CatusUser, Contrato, ContratoPersona, EstadoFormulario

        self.owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.stranger = CatusUser.objects.create(username="otro", email="otro@example.com")
        animal = Animal.objects.create(nombre="Michi", cargado_por=self.owner, estado="R", tipo="G")
        estado = EstadoFormulario.objects.create(gato=animal, estado="R", hash=str(uuid.uuid4()))
        adoptante = ContratoPersona.objects.create(persona_nombre="Ana Adoptante", persona_dni="30111222",
                                                   persona_email="ana@example.com")
        self.contrato = Contrato.objects.create(hash=str(uuid.uuid4()), gato=animal, estado_formulario=estado,
                                                adoptante=adoptante, contrato_aceptado=True, gato_nombre="Michi",
                                                gato_edad="1 año", gato_color="Negro", gato_sexo="M",
                                                gato_alimento="Balanceado", gato_cuidados_especiales="Ninguno")

    def write_pdf(self, name=service.CONTRATO_PDF):
        folder = os.path.join(self.static, "contrato", self.contrato.hash)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"%PDF-1.4 con el DNI")

    def assertIsThePdf(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.content, b"%PDF-1.4 con el DNI")

    def test_the_adopters_submit_gets_a_signed_link_and_the_mail_still_carries_the_pdf(self):
        views = importlib.import_module("catus.views.contrato")
        data = {
            "persona_nombre": "Ana Adoptante", "persona_dni": "30111222", "persona_fecha_nacimiento": "01/01/1990",
            "persona_ocupacion": "Docente", "persona_celular": "1155554444", "persona_direccion": "Calle 1",
            "persona_localidad": "CABA", "persona_email": "ana@example.com",
        }
        with mock.patch.object(views, "Thread", InlineThread), \
                mock.patch.object(views, "send_html_email") as send_html_email:
            response = self.client.post("/contrato/{}/".format(self.contrato.hash), data)

        body = json.loads(response.content.decode())
        self.assertEqual(body["status"], "success", body)
        self.assertTrue(body["contrato_url"].startswith("/contrato_adopcion/pdf/"))
        self.assertNotIn(self.contrato.hash, body["contrato_url"])

        pdf = self.client.get(body["contrato_url"])
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        attachments = [call[1]["file"] for call in send_html_email.call_args_list]
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["name"], service.CONTRATO_PDF)

    def test_a_signed_link_opens_it_without_an_account(self):
        self.write_pdf()

        self.assertIsThePdf(self.client.get(service.contrato_pdf_url(self.contrato)))

    def test_only_a_link_signed_for_this_opens_it(self):
        self.write_pdf()
        url = service.contrato_pdf_url(self.contrato)

        for bad in (
            url[:-2] + ("A/" if url[-2] != "A" else "B/"),
            "/contrato_adopcion/pdf/{}/".format(self.contrato.hash),
            "/contrato_adopcion/pdf/{}/".format(signing.dumps(self.contrato.hash, salt="otra-cosa")),
        ):
            self.assertEqual(self.client.get(bad).status_code, 404, bad)

    def test_the_link_expires(self):
        self.write_pdf()
        url = service.contrato_pdf_url(self.contrato)

        later = time.time() + service.CONTRATO_PDF_MAX_AGE + 60
        with mock.patch("django.core.signing.time.time", return_value=later):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_a_link_for_a_contract_without_a_pdf_is_a_404(self):
        self.assertEqual(self.client.get(service.contrato_pdf_url(self.contrato)).status_code, 404)

    def test_the_rescuers_button_and_download_work(self):
        # Both asked for a file name the generator does not write.
        self.write_pdf()
        self.client.force_login(self.owner)
        download = "/contrato_adopcion/{}/download/".format(self.contrato.id)

        page = self.client.get("/formulario/{}/contrato/".format(self.contrato.estado_formulario_id))

        self.assertContains(page, 'href="{}"'.format(download))
        self.assertNotContains(page, "/static/contrato/{}".format(self.contrato.hash))
        self.assertIsThePdf(self.client.get(download))

    def test_the_download_finds_one_under_the_old_name(self):
        self.write_pdf(service.CONTRATO_PDF_VIEJO)
        self.client.force_login(self.owner)

        self.assertIsThePdf(self.client.get("/contrato_adopcion/{}/download/".format(self.contrato.id)))

    def test_nobody_else_downloads_it(self):
        self.write_pdf()
        download = "/contrato_adopcion/{}/download/".format(self.contrato.id)

        self.assertEqual(self.client.get(download).status_code, 302)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(download).status_code, 403)

    def test_the_link_sent_to_the_adopter_keeps_working(self):
        self.assertEqual(self.client.get("/contrato/{}/".format(self.contrato.hash)).status_code, 200)
