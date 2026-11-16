"""El backend de mail propio (catus/mail_backend.py): la API v3 de SendGrid con requests.

Todos los mails del sitio salen por acá: los formularios al rescatista, el recibo al
adoptante, el contrato en PDF, los avisos al equipo y el cambio de contraseña. Reemplaza a
sendgrid-django, que no se mantiene más; lo que se fija acá es el pedido que le llega a
SendGrid, campo por campo, y qué pasa cuando no lo acepta. Nada habla con SendGrid:
requests.post está reemplazado.
"""
import base64
from unittest import mock

import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage, get_connection
from django.test import SimpleTestCase, TestCase, override_settings

from catus.mail_backend import TIMEOUT, URL, SendGridBackend, SendGridError
from catus.utils import send_html_email

BACKEND = "catus.mail_backend.SendGridBackend"


def respuesta(status=202, json_data=None):
    falsa = mock.Mock(status_code=status)
    if json_data is None:
        falsa.json.side_effect = ValueError("sin cuerpo")
    else:
        falsa.json.return_value = json_data
    return falsa


@override_settings(EMAIL_BACKEND=BACKEND, SENDGRID_API_KEY="SG.clave-de-prueba")
class PedidoASendGridTest(SimpleTestCase):

    def mandar(self, *args, **kwargs):
        with mock.patch("catus.mail_backend.requests.post", return_value=respuesta()) as post:
            enviados = send_html_email(*args, **kwargs)
        self.assertEqual(enviados, 1)
        self.assertEqual(post.call_count, 1)
        return post.call_args

    def test_un_mail_del_sitio_tal_como_lo_recibe_sendgrid(self):

        pdf = b"%PDF-1.4 contrato"
        llamada = self.mandar(
            "Contrato de adopción", "<p>Hola <b>Ana</b></p>", "Catpuccino Adopciones <adopciones@catpuccino.test>",
            ["ana@ejemplo.test"], file={"name": "contrato.pdf", "content": pdf, "content_type": "application/pdf"},
        )

        self.assertEqual(llamada.args, (URL,))
        self.assertEqual(llamada.kwargs["timeout"], TIMEOUT)
        self.assertEqual(llamada.kwargs["headers"], {"Authorization": "Bearer SG.clave-de-prueba"})

        datos = llamada.kwargs["json"]
        texto, html = datos["content"][0]["value"], datos["content"][1]["value"]
        self.assertEqual(datos, {
            "personalizations": [{"to": [{"email": "ana@ejemplo.test"}], "subject": "Contrato de adopción"}],
            "from": {"email": "adopciones@catpuccino.test", "name": "Catpuccino Adopciones"},
            "subject": "Contrato de adopción",
            "content": [
                {"type": "text/plain", "value": texto},
                {"type": "text/html", "value": html},
            ],
            #send_html_email responde por defecto al primer destinatario, como siempre
            "reply_to": {"email": "ana@ejemplo.test"},
            "attachments": [{
                "filename": "contrato.pdf",
                "content": base64.b64encode(pdf).decode("ascii"),
                "type": "application/pdf",
            }],
        })
        #el HTML va adentro del marco de los mails del sitio (utils.envolver_mail), y el
        #texto es el mismo mail sin etiquetas (utils.texto_plano)
        self.assertIn("Hola <b>Ana</b>", html)
        self.assertIn("Hola Ana", texto)
        self.assertNotIn("<", texto)

    def test_cc_bcc_y_responder_a(self):

        datos = self.mandar(
            "Aviso", "<p>x</p>", "adopciones@catpuccino.test", ["equipo@catpuccino.test", "rescatista@ejemplo.test"],
            cc=["cc@ejemplo.test"], bcc=["oculto@ejemplo.test"], reply_to="Ana <ana@ejemplo.test>",
        ).kwargs["json"]

        personalizacion = datos["personalizations"][0]
        self.assertEqual(personalizacion["to"], [{"email": "equipo@catpuccino.test"}, {"email": "rescatista@ejemplo.test"}])
        self.assertEqual(personalizacion["cc"], [{"email": "cc@ejemplo.test"}])
        self.assertEqual(personalizacion["bcc"], [{"email": "oculto@ejemplo.test"}])
        self.assertEqual(datos["reply_to"], {"email": "ana@ejemplo.test", "name": "Ana"})
        self.assertEqual(datos["from"], {"email": "adopciones@catpuccino.test"})

    def test_una_direccion_repetida_va_una_sola_vez(self):
        """SendGrid rechaza el mail entero si una dirección se repite entre to, cc y bcc."""

        datos = self.mandar(
            "Aviso", "<p>x</p>", "adopciones@catpuccino.test", ["equipo@catpuccino.test", "EQUIPO@catpuccino.test"],
            bcc=["equipo@catpuccino.test", "otro@ejemplo.test"],
        ).kwargs["json"]

        personalizacion = datos["personalizations"][0]
        self.assertEqual(personalizacion["to"], [{"email": "equipo@catpuccino.test"}])
        self.assertEqual(personalizacion["bcc"], [{"email": "otro@ejemplo.test"}])

    def test_un_mail_solo_html_lleva_texto_igual(self):
        """text/plain va primero y no puede ir vacío: SendGrid lo exige."""

        mensaje = EmailMessage("Hola", "<p>hola</p>", "adopciones@catpuccino.test", ["ana@ejemplo.test"])
        mensaje.content_subtype = "html"

        with mock.patch("catus.mail_backend.requests.post", return_value=respuesta()) as post:
            mensaje.send()

        self.assertEqual(post.call_args.kwargs["json"]["content"], [
            {"type": "text/plain", "value": " "}, {"type": "text/html", "value": "<p>hola</p>"},
        ])

    def test_el_header_reply_to_gana_y_no_va_como_header(self):

        mensaje = EmailMessage("Hola", "texto", "adopciones@catpuccino.test", ["ana@ejemplo.test"],
                               reply_to=["otro@ejemplo.test"], headers={"Reply-To": "equipo@catpuccino.test", "X-Algo": "1"})

        with mock.patch("catus.mail_backend.requests.post", return_value=respuesta()) as post:
            mensaje.send()

        datos = post.call_args.kwargs["json"]
        self.assertEqual(datos["reply_to"], {"email": "equipo@catpuccino.test"})
        self.assertEqual(datos["headers"], {"X-Algo": "1"})


@override_settings(EMAIL_BACKEND=BACKEND, SENDGRID_API_KEY="SG.clave-de-prueba")
class CuandoSendGridNoLoAceptaTest(SimpleTestCase):

    RECHAZO = {"errors": [{"message": "The from address does not match a verified Sender Identity.", "field": "from"}]}

    def test_levanta_con_el_motivo_y_sin_las_direcciones(self):
        """Como el backend viejo: los que mandan ya atrapan la excepción. El texto termina en
        Jentry, así que no lleva a quién iba."""

        conexion = get_connection()
        mensaje = EmailMessage("Hola", "texto", "adopciones@catpuccino.test", ["ana@ejemplo.test"])

        with mock.patch("catus.mail_backend.requests.post", return_value=respuesta(403, self.RECHAZO)):
            with self.assertRaises(SendGridError) as error:
                conexion.send_messages([mensaje])

        self.assertIn("403", str(error.exception))
        self.assertIn("verified Sender Identity", str(error.exception))
        self.assertNotIn("ana@ejemplo.test", str(error.exception))

    def test_send_html_email_reintenta_y_despues_levanta(self):

        with mock.patch("catus.mail_backend.requests.post", return_value=respuesta(500)) as post, \
                mock.patch("catus.utils.time.sleep"):
            with self.assertRaises(SendGridError):
                send_html_email("Hola", "<p>x</p>", "adopciones@catpuccino.test", "ana@ejemplo.test")

        self.assertEqual(post.call_count, 3)

    def test_un_timeout_tambien_levanta(self):

        mensaje = EmailMessage("Hola", "texto", "adopciones@catpuccino.test", ["ana@ejemplo.test"])

        with mock.patch("catus.mail_backend.requests.post", side_effect=requests.Timeout("lento")):
            with self.assertRaises(requests.Timeout):
                mensaje.send()

    def test_con_fail_silently_no_levanta_y_lo_loguea(self):

        mensajes = [EmailMessage("Uno", "texto", "adopciones@catpuccino.test", ["ana@ejemplo.test"]),
                    EmailMessage("Dos", "texto", "adopciones@catpuccino.test", ["ana@ejemplo.test"])]

        with mock.patch("catus.mail_backend.requests.post", side_effect=[respuesta(400, self.RECHAZO), respuesta()]):
            with self.assertLogs("catus.mail_backend", level="WARNING"):
                enviados = get_connection(fail_silently=True).send_messages(mensajes)

        self.assertEqual(enviados, 1)

    @override_settings(SENDGRID_API_KEY="")
    def test_sin_clave_es_un_error_de_configuracion(self):

        with self.assertRaises(ImproperlyConfigured):
            SendGridBackend()


class ConfiguracionTest(TestCase):

    def test_es_el_backend_del_sitio(self):
        #el de settings.py tal cual: el que corre los tests lo cambia por el de memoria
        from catus_project import settings as ajustes

        self.assertEqual(ajustes.EMAIL_BACKEND, BACKEND)

    @override_settings(EMAIL_BACKEND=BACKEND, SENDGRID_API_KEY="SG.clave-de-prueba",
                       DEFAULT_FROM_EMAIL="adopciones@catpuccino.test")
    def test_el_mail_de_la_contrasena_sale_del_remitente_del_sitio(self):
        """Django lo manda sin decir desde dónde: salía de webmaster@localhost, que SendGrid
        no acepta."""

        from catus.forms import PasswordResetForm
        from catus.tests.factories import make_user

        usuario = make_user(email="rescatista@ejemplo.test")
        usuario.set_password("una-clave-larga-y-rara")
        usuario.save()

        form = PasswordResetForm({"email": "rescatista@ejemplo.test"})
        self.assertTrue(form.is_valid())
        with mock.patch("catus.mail_backend.requests.post", return_value=respuesta()) as post:
            form.save(domain_override="adopciones.catpuccino.org", use_https=True,
                      email_template_name="registration/password_reset_email.txt",
                      html_email_template_name="registration/password_reset_email.html")

        datos = post.call_args.kwargs["json"]
        self.assertEqual(datos["from"], {"email": "adopciones@catpuccino.test"})
        self.assertEqual(datos["personalizations"][0]["to"], [{"email": "rescatista@ejemplo.test"}])
        self.assertEqual([c["type"] for c in datos["content"]], ["text/plain", "text/html"])

    def test_settings_usa_el_remitente_del_sitio(self):

        from catus_project import settings as ajustes

        self.assertEqual(ajustes.DEFAULT_FROM_EMAIL, ajustes.SEND_MAIL)
