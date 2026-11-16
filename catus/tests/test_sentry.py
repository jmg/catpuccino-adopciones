"""Lo que llega a Jentry de un error: sin las respuestas de los formularios ni la sesión.

Con send_default_pii=True el SDK mandaba en cada error el cuerpo del POST (el formulario de
pre-adopción entero, el contrato con el DNI), las cookies con la de sesión y el usuario con
su mail. catus_project/sentry.py le saca eso a cada evento antes de que salga.
"""
from django.test import SimpleTestCase

from catus_project.sentry import sin_datos_personales


def evento_de_un_post():
    """Un evento como lo arma la integración de Django para un POST que falló."""

    return {
        "level": "error",
        "request": {
            "url": "https://adopciones.catpuccino.org/contrato/0f3c9a1e-hash-del-adoptante/",
            "method": "POST",
            "query_string": "id=12&email=ana%40ejemplo.com",
            "data": {"persona_dni": "30123456", "persona_email": "ana@ejemplo.com"},
            "cookies": {"sessionid": "abc", "csrftoken": "def"},
            "headers": {
                "Cookie": "sessionid=abc; csrftoken=def",
                "Authorization": "Bearer algo",
                "X-Forwarded-For": "190.2.3.4",
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "multipart/form-data",
            },
            "env": {"REMOTE_ADDR": "190.2.3.4", "SERVER_NAME": "adopciones"},
        },
        "user": {"id": 7, "email": "rescatista@ejemplo.com", "username": "rescatista@ejemplo.com",
                 "ip_address": "190.2.3.4"},
        "logentry": {
            "message": "No se pudo confirmarle el formulario %s a %s",
            "formatted": "No se pudo confirmarle el formulario abc a ana@ejemplo.com",
            "params": ["abc", "ana@ejemplo.com"],
        },
        "exception": {"values": [{"type": "SMTPRecipientsRefused", "value": "{'ana@ejemplo.com': (550, 'no')}"}]},
        "breadcrumbs": {"values": [
            {"category": "httplib", "data": {
                "url": "https://graph.facebook.com/v21.0/debug_token",
                "http.query": "input_token=EAAB&access_token=123|secreto-de-la-app",
                "method": "GET",
            }},
            {"category": "catus.views.adoption", "message": "Formulario de ana@ejemplo.com"},
        ]},
    }


class SinDatosPersonalesTest(SimpleTestCase):

    def setUp(self):
        self.evento = sin_datos_personales(evento_de_un_post(), {})

    def test_no_manda_el_cuerpo_ni_las_cookies_ni_la_query_string(self):

        pedido = self.evento["request"]
        for parte in ("data", "cookies", "query_string", "env"):
            self.assertNotIn(parte, pedido)

    def test_saca_los_headers_de_la_sesion_y_la_ip(self):

        headers = {k.lower() for k in self.evento["request"]["headers"]}

        self.assertEqual(headers, {"user-agent", "content-type"})

    def test_deja_la_ruta_y_el_metodo_sin_el_link_del_contrato(self):
        """El link del contrato es el permiso para abrirlo, sin cuenta."""

        self.assertEqual(self.evento["request"]["url"], "https://adopciones.catpuccino.org/contrato/[link]/")
        self.assertEqual(self.evento["request"]["method"], "POST")

    def test_del_usuario_queda_solo_el_id(self):

        self.assertEqual(self.evento["user"], {"id": 7})

    def test_un_usuario_sin_id_no_se_manda(self):

        evento = sin_datos_personales({"user": {"ip_address": "190.2.3.4"}}, {})

        self.assertNotIn("user", evento)

    def test_los_mails_de_los_logs_y_las_excepciones_no_salen(self):

        texto = repr(self.evento)

        self.assertNotIn("ana@ejemplo.com", texto)
        self.assertNotIn("rescatista@ejemplo.com", texto)
        self.assertIn("No se pudo confirmarle el formulario abc a [mail]", texto)

    def test_el_token_de_graph_no_sale_en_los_breadcrumbs(self):
        """debug_token lleva el secreto de la app en la query string."""

        self.assertNotIn("secreto-de-la-app", repr(self.evento))
        miga = self.evento["breadcrumbs"]["values"][0]
        self.assertEqual(miga["data"]["url"], "https://graph.facebook.com/v21.0/debug_token")

    def test_las_transacciones_tambien(self):

        transaccion = {
            "type": "transaction",
            "request": {"url": "https://adopciones.catpuccino.org/postularme/firmado:abc/", "data": {"x": "y"}},
            "spans": [{"op": "http.client", "data": {"url": "https://graph.facebook.com/v21.0/1/media?access_token=x",
                                                     "http.query": "access_token=x"}}],
        }

        sin_datos_personales(transaccion, {})

        self.assertNotIn("access_token", repr(transaccion))
        self.assertNotIn("data", transaccion["request"])
        self.assertEqual(transaccion["request"]["url"], "https://adopciones.catpuccino.org/postularme/[link]/")

    def test_un_evento_sin_pedido_pasa_igual(self):
        """Los de los crons no tienen request ni usuario."""

        evento = {"level": "error", "message": "algo"}

        self.assertEqual(sin_datos_personales(evento, {}), {"level": "error", "message": "algo"})


class ConfiguracionTest(SimpleTestCase):
    """Lo que settings.py le pide al SDK (con ENV=TEST se inicializa como en producción)."""

    def test_el_sdk_no_junta_datos_personales(self):

        import sentry_sdk

        opciones = sentry_sdk.get_client().options

        self.assertFalse(opciones["send_default_pii"])
        self.assertEqual(opciones["max_request_body_size"], "never")
        self.assertFalse(opciones["include_local_variables"])
        self.assertIs(opciones["before_send"], sin_datos_personales)
        self.assertIs(opciones["before_send_transaction"], sin_datos_personales)
