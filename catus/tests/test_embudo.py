"""El embudo del formulario de pre-adopción (services/embudo.py).

No había ningún dato de cuántos abren el formulario y hasta dónde llegan: con 38 preguntas
obligatorias en el de gatos, no se podía decidir si acortarlo.
"""
from unittest import mock

from django.test import TestCase

from catus.models import PasoFormulario
from catus.services import embudo
from catus.tests.factories import make_user


class ContarTest(TestCase):

    def test_suma_por_dia_especie_y_paso(self):
        embudo.contar("G", "abrio")
        embudo.contar("gato", "abrio")
        embudo.contar("P", "abrio")
        self.assertEqual(PasoFormulario.objects.get(especie="G", paso="abrio").n, 2)
        self.assertEqual(PasoFormulario.objects.get(especie="P", paso="abrio").n, 1)

    def test_lo_que_no_es_un_paso_no_se_guarda(self):
        embudo.contar("G", "cualquiera")
        embudo.contar("X", "abrio")
        self.assertFalse(PasoFormulario.objects.exists())

    def test_si_falla_la_base_no_rompe(self):
        with mock.patch.object(PasoFormulario.objects, "filter", side_effect=RuntimeError("base caída")):
            embudo.contar("G", "abrio")  # no levanta

    def test_el_resumen_da_porcentajes_sobre_los_que_abrieron(self):
        for _ in range(4):
            embudo.contar("G", "abrio")
        embudo.contar("G", "enviado")
        gatos = embudo.resumen()[0]
        enviados = next(p for p in gatos["pasos"] if p["paso"] == "enviado")
        self.assertEqual((gatos["abrieron"], enviados["n"], enviados["porcentaje"]), (4, 1, 25))


class PasoDelNavegadorTest(TestCase):

    def test_un_paso_del_navegador_se_cuenta(self):
        response = self.client.post("/pre-adopcion/paso/", {"paso": "requisitos", "especie": "P"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(PasoFormulario.objects.get(especie="P", paso="requisitos").n, 1)

    def test_el_navegador_no_puede_contar_pasos_del_servidor(self):
        self.client.post("/pre-adopcion/paso/", {"paso": "enviado", "especie": "G"})
        self.assertFalse(PasoFormulario.objects.exists())

    def test_con_demasiados_desde_una_conexion_deja_de_contar(self):
        with mock.patch("catus.services.throttle.client_ip", return_value="203.0.113.9"), \
                mock.patch("catus.services.throttle.hit", return_value=10_000):
            self.client.post("/pre-adopcion/paso/", {"paso": "abrio", "especie": "G"})
        self.assertFalse(PasoFormulario.objects.exists())

    def test_get_no_hace_nada(self):
        self.assertEqual(self.client.get("/pre-adopcion/paso/").status_code, 405)


class PantallaDelEquipoTest(TestCase):

    def test_solo_el_equipo_la_ve(self):
        embudo.contar("G", "abrio")
        self.client.force_login(make_user(email="rescate@catpuccino.test"))
        self.assertNotContains(self.client.get("/tools/embudo/"), "Embudo del formulario")
        self.client.force_login(make_user(email="equipo@catpuccino.test", is_superuser=True))
        self.assertContains(self.client.get("/tools/embudo/"), "Abrió el formulario")


class EnvioDelFormularioTest(TestCase):
    """El servidor cuenta cómo terminó el envío; el de un bot (honeypot) no cuenta."""

    def setUp(self):
        from forms_builder.forms.models import Form
        Form.objects.create(title="Pre adopción", slug="formulario-de-pre-adopcion")

    def test_un_envio_rechazado_se_cuenta(self):
        with mock.patch("catus.views.adoption.PreAdoptionView._rejected", return_value="demasiados"):
            self.client.post("/pre-adopcion/", {})
        self.assertEqual(PasoFormulario.objects.get(paso="rechazado").n, 1)

    def test_el_de_un_bot_no_se_cuenta(self):
        from catus.views.adoption import HONEYPOT_FIELD
        self.client.post("/pre-adopcion/", {HONEYPOT_FIELD: "http://spam"})
        self.assertFalse(PasoFormulario.objects.exists())
