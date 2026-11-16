"""Cómo le habla el sitio a Graph (Facebook / Instagram) desde que no usa pyfb.

pyfb 0.6.0 (abandonado) pedía con urlopen, sin timeout, a la v5.0, con el token en la URL
también en los POST, y un error de Graph llegaba como HTTPError con el motivo escondido en
el cuerpo. Ahora todo pasa por FacebookApiService.graph_get / graph_post, con requests: acá
se fija qué sale (versión, token, timeout) y qué se levanta cuando Graph dice que no.
requests está reemplazado: nada sale a Facebook.
"""
import re
from unittest import mock

from django.test import SimpleTestCase, override_settings

from catus.services import facebook
from catus.services.facebook import ClienteGraph, FacebookApiService, GraphError

GRAPH = "https://graph.facebook.com/v21.0"


def respuesta(status=200, json_data=None, text=""):
    falsa = mock.Mock(status_code=status, text=text)
    if json_data is None:
        falsa.json.side_effect = ValueError("no es JSON")
    else:
        falsa.json.return_value = json_data
    return falsa


class PedidosTest(SimpleTestCase):

    def test_un_get_lleva_el_token_en_los_parametros_y_timeout(self):

        with mock.patch("catus.services.facebook.requests.get", return_value=respuesta(json_data={"id": "1"})) as get:
            datos = ClienteGraph("TOKEN").request("123?fields=status_code,status")

        self.assertEqual(datos, {"id": "1"})
        get.assert_called_once_with(GRAPH + "/123?fields=status_code,status",
                                    params={"access_token": "TOKEN"}, timeout=20)

    def test_un_post_lleva_los_datos_y_el_token_en_el_cuerpo(self):
        """pyfb ponía el token en la URL también en los POST: quedaba en cualquier log."""

        with mock.patch("catus.services.facebook.requests.post", return_value=respuesta(json_data={"id": "c1"})) as post:
            datos = ClienteGraph("TOKEN").request("1784/media", image_url="https://x/y.jpg", caption="Hola")

        self.assertEqual(datos, {"id": "c1"})
        post.assert_called_once_with(
            GRAPH + "/1784/media", timeout=20,
            data={"access_token": "TOKEN", "image_url": "https://x/y.jpg", "caption": "Hola"},
        )

    def test_lo_que_no_es_texto_va_como_json(self):

        with mock.patch("catus.services.facebook.requests.post", return_value=respuesta(json_data={})) as post:
            ClienteGraph("TOKEN").request("/1784/messages", recipient={"id": "9"}, message={"text": "hola"})

        self.assertEqual(post.call_args.args, (GRAPH + "/1784/messages",))
        self.assertEqual(post.call_args.kwargs["data"]["recipient"], '{"id": "9"}')

    def test_el_servicio_usa_el_token_de_la_cuenta(self):

        cuenta = mock.Mock(facebook_token="DE-LA-CUENTA")

        with mock.patch("catus.services.facebook.requests.get", return_value=respuesta(json_data={})) as get:
            FacebookApiService(account=cuenta).facebook.request("me")

        self.assertEqual(get.call_args.kwargs["params"], {"access_token": "DE-LA-CUENTA"})


class ErroresTest(SimpleTestCase):

    def test_el_error_de_graph_trae_el_json_entero(self):

        cuerpo = {"error": {"message": "Session has expired", "code": 190, "error_subcode": 463}}

        with mock.patch("catus.services.facebook.requests.get", return_value=respuesta(400, cuerpo)):
            with self.assertRaises(GraphError) as error:
                FacebookApiService.graph_get("me", access_token="x")

        self.assertEqual(str(error.exception), "Session has expired")
        self.assertEqual(error.exception.error["code"], 190)
        self.assertEqual(FacebookApiService.show_error(error.exception), "Error de Instagram 190/463: Session has expired")

    def test_un_error_con_status_200_tambien_es_error(self):

        with mock.patch("catus.services.facebook.requests.get", return_value=respuesta(200, {"error": {"message": "no"}})):
            with self.assertRaises(GraphError):
                FacebookApiService.graph_get("me", access_token="x")

    def test_una_respuesta_que_no_es_json_dice_el_status(self):
        """Un 502 del proxy contesta HTML, no el JSON de Graph."""

        with mock.patch("catus.services.facebook.requests.post", return_value=respuesta(502, text="<html>502</html>")):
            with self.assertRaises(GraphError) as error:
                FacebookApiService.graph_post("1/media", access_token="x", caption="c")

        self.assertIsNone(error.exception.error)
        self.assertIn("502", FacebookApiService.show_error(error.exception))

    def test_un_timeout_sale_como_lo_que_es(self):

        import requests

        with mock.patch("catus.services.facebook.requests.get", side_effect=requests.Timeout("lento")):
            with self.assertRaises(requests.Timeout):
                FacebookApiService.graph_get("me", access_token="x")


@override_settings(FACEBOOK_APP_ID="APP", FACEBOOK_APP_SECRET="SECRETO")
class TokensTest(SimpleTestCase):

    def test_el_token_largo_se_pide_a_la_misma_version(self):
        """Se pedía a la v4.0, sin timeout."""

        with mock.patch("catus.services.facebook.requests.get",
                        return_value=respuesta(json_data={"access_token": "LARGO", "expires_in": 100})) as get:
            token, vence = FacebookApiService.get_long_lived_token("CORTO")

        self.assertEqual((token, vence), ("LARGO", 100))
        get.assert_called_once_with(GRAPH + "/oauth/access_token", timeout=20, params={
            "grant_type": "fb_exchange_token", "client_id": "APP", "client_secret": "SECRETO",
            "fb_exchange_token": "CORTO",
        })

    def test_el_token_largo_que_falla_levanta_con_el_motivo(self):

        with mock.patch("catus.services.facebook.requests.get",
                        return_value=respuesta(400, {"error": {"message": "Invalid OAuth access token.", "code": 190}})):
            with self.assertRaisesMessage(Exception, "Invalid OAuth access token."):
                FacebookApiService.get_long_lived_token("CORTO")

    def test_el_token_de_instagram_tiene_timeout(self):

        with mock.patch("catus.services.facebook.requests.get",
                        return_value=respuesta(json_data={"access_token": "IG", "expires_in": 5})) as get:
            FacebookApiService.get_long_lived_token_instagram("VIEJO")

        self.assertEqual(get.call_args.kwargs["timeout"], 20)


class UnaSolaVersionTest(SimpleTestCase):

    def test_no_hay_otra_version_de_graph_en_el_codigo(self):

        import inspect

        fuente = inspect.getsource(facebook)
        versiones = set(re.findall(r"graph\.facebook\.com/(v\d+\.\d+)", fuente))

        self.assertEqual(versiones, {"v21.0"})
        self.assertEqual(FacebookApiService.GRAPH, GRAPH)
