"""El adoptante acepta el contrato una sola vez.

Después de "Aceptar y descargar contrato" el PDF llega como descarga, así que la página no
cambiaba: el formulario y el botón seguían ahí, y el botón no se apagaba durante el envío.
Cada toque de más era un POST completo: el PDF otra vez, los mails al rescatista, al equipo
y al adoptante reenviados, y el animal marcado como adoptado de nuevo (revisión de la semana
del 2026-11-12).
"""
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from catus.models import Contrato, ContratoPersona
from catus.tests.factories import make_animal, make_estado_formulario, make_user


class HiloInmediato:
    """Thread que corre en el momento, para poder contar los mails."""

    def __init__(self, target=None, **kwargs):
        self.target = target

    def start(self):
        self.target()


DATOS = {
    "persona_nombre": "Ana Gómez", "persona_dni": "30111222", "persona_fecha_nacimiento": "01/02/1990",
    "persona_ocupacion": "Docente", "persona_email": "ana@ejemplo.test", "persona_celular": "1155554444",
    "persona_direccion": "Calle Falsa 123", "persona_localidad": "CABA",
}


class ContratoUnaSolaVezTest(TestCase):

    def setUp(self):

        self.factory = RequestFactory()
        rescatista = make_user(email="rescatista@catpuccino.test")
        self.animal = make_animal(nombre="Willy", cargado_por=rescatista)
        estado_form = make_estado_formulario(animal=self.animal, hash="form-hash", estado="N")
        adoptante = ContratoPersona.objects.create(persona_email="ana@ejemplo.test")
        self.contrato = Contrato.objects.create(hash="contrato-hash", estado_formulario=estado_form,
                                                gato=self.animal, adoptante=adoptante)

    def aceptar(self, generar=None):

        from catus.views.contrato import EditPersonaView

        request = self.factory.post("/contrato/contrato-hash/", DATOS)
        request.user = AnonymousUser()

        pdf = ("/contrato/descarga/firmada/", b"%PDF-1.4", "contrato.pdf")
        with mock.patch("catus.views.contrato.generate_contrato_pdf", side_effect=generar, return_value=pdf), \
                mock.patch("catus.views.contrato.send_html_email") as mails, \
                mock.patch("catus.views.contrato.Thread", HiloInmediato):
            response = EditPersonaView.as_view()(request, contrato_hash="contrato-hash")

        return response, mails

    def test_aceptar_dos_veces_manda_los_mails_una_sola_vez(self):

        import json

        response, mails = self.aceptar()
        self.assertEqual(json.loads(response.content)["status"], "success")
        self.assertEqual(mails.call_count, 2, "el primer aceptar tiene que avisar al rescatista y al adoptante")

        self.animal.refresh_from_db()
        adoptado_el = self.animal.fecha_adopcion
        self.assertEqual(self.animal.estado, "A")

        response, mails = self.aceptar()
        datos = json.loads(response.content)
        self.assertEqual(datos["status"], "success")
        self.assertEqual(datos["contrato_url"], "/contrato/descarga/firmada/", "el segundo toque tiene que poder bajar el PDF")
        self.assertFalse(mails.called, "un segundo toque volvió a mandar los mails")

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.fecha_adopcion, adoptado_el)

    def test_si_otro_pedido_lo_acepto_en_el_medio_no_se_repiten_los_mails(self):
        """Dos POST simultáneos pasan los dos el primer chequeo: lo acepta uno solo."""

        import json

        def gana_otro_pedido(contrato):
            Contrato.objects.filter(id=contrato.id).update(contrato_aceptado=True)
            return ("/contrato/descarga/firmada/", b"%PDF-1.4", "contrato.pdf")

        response, mails = self.aceptar(generar=gana_otro_pedido)

        self.assertEqual(json.loads(response.content)["status"], "success")
        self.assertFalse(mails.called, "los dos pedidos simultáneos mandaron los mails")
