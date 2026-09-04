"""Tests del importador de datos desde un post de Instagram.

El rescatista pega el link de un post y la app lo lee para prellenar el formulario.
La URL la elige la persona, así que el server no puede ir a buscar cualquier cosa.
"""
from unittest import mock

from django.test import TestCase

from catus.services.gpt import GPTService
from catus.utils import es_url_de_instagram


class EsUrlDeInstagramTest(TestCase):

    def test_acepta_links_de_posts(self):

        for url in [
            "https://www.instagram.com/p/Cq6AYP9rCob/",
            "https://instagram.com/p/Cq6AYP9rCob/?img_index=1",
            "http://www.instagram.com/reel/abc123/",
        ]:
            self.assertTrue(es_url_de_instagram(url), url)

    def test_rechaza_otros_dominios(self):

        for url in [
            "https://ejemplo.test/p/abc/",
            "https://instagram.com.atacante.test/p/abc/",
            "https://noinstagram.com/p/abc/",
        ]:
            self.assertFalse(es_url_de_instagram(url), url)

    def test_rechaza_direcciones_internas(self):
        """Sin esto el server podía ser usado para pedir cosas de la red interna."""

        for url in [
            "http://127.0.0.1:8000/admin/",
            "http://localhost/",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.0.1/",
            "file:///etc/passwd",
        ]:
            self.assertFalse(es_url_de_instagram(url), url)

    def test_rechaza_basura(self):

        for url in [None, "", "no soy una url", "javascript:alert(1)"]:
            self.assertFalse(es_url_de_instagram(url), repr(url))


class PullDataFromIgTest(TestCase):

    def test_no_sale_a_buscar_una_url_que_no_es_de_instagram(self):

        with mock.patch("catus.services.gpt.requests.get") as get:
            with self.assertRaises(ValueError):
                GPTService().pull_data_from_ig("http://169.254.169.254/latest/meta-data/")

        get.assert_not_called()

    def test_una_pagina_sin_og_title_no_rompe(self):
        """Antes accedía a .attrs sobre None y devolvía un 500."""

        respuesta = mock.Mock()
        respuesta.content = b"<html><head><title>hola</title></head><body></body></html>"

        with mock.patch("catus.services.gpt.requests.get", return_value=respuesta):
            with self.assertRaises(ValueError):
                GPTService()._get_html_title_and_images("https://www.instagram.com/p/abc/")

    def test_lee_el_texto_del_post(self):

        respuesta = mock.Mock()
        respuesta.content = (
            b'<html><head><meta property="og:title" content="Willy busca hogar">'
            b"</head><body></body></html>"
        )

        with mock.patch("catus.services.gpt.requests.get", return_value=respuesta):
            texto, imagenes = GPTService()._get_html_title_and_images("https://www.instagram.com/p/abc/")

        self.assertEqual(texto, "Willy busca hogar")
        self.assertEqual(imagenes, [])


class EsUrlDeImagenPublicaTest(TestCase):
    """Las fotos que se traen por URL las manda el navegador: el server no puede abrir cualquier cosa."""

    def test_acepta_los_cdn_de_instagram(self):

        from catus.utils import es_url_de_imagen_publica

        for url in [
            "https://scontent-eze1-1.cdninstagram.com/v/t51.29350-15/foto.jpg",
            "https://scontent.xx.fbcdn.net/v/t51/foto.jpg",
            "https://www.instagram.com/p/abc/media/?size=l",
        ]:
            self.assertTrue(es_url_de_imagen_publica(url), url)

    def test_rechaza_archivos_locales(self):
        """Con file:// el server leía sus propios archivos, incluido el de secretos."""

        from catus.utils import es_url_de_imagen_publica

        for url in [
            "file:///etc/secrets/catpuccino_adopciones.PROD.json",
            "file:///etc/passwd",
        ]:
            self.assertFalse(es_url_de_imagen_publica(url), url)

    def test_rechaza_la_red_interna_y_otros_dominios(self):

        from catus.utils import es_url_de_imagen_publica

        for url in [
            "http://127.0.0.1:3306/",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost/admin/",
            "https://sitio-del-atacante.test/foto.jpg",
            "https://cdninstagram.com.atacante.test/foto.jpg",
            "",
            None,
        ]:
            self.assertFalse(es_url_de_imagen_publica(url), repr(url))


class ParseResponseTest(TestCase):
    """Interpreta lo que devuelve el modelo, que a su vez sale del caption de un post."""

    def setUp(self):
        self.service = GPTService()

    def test_lee_un_json_normal(self):

        data = self.service.parse_response(
            '{"nombre": "Willy", "tipo": "gato", "sexo": "macho", "edad": "2 años", '
            '"descripcion": "Muy compañero"}'
        )

        self.assertEqual(data["Nombre"], "Willy")
        self.assertEqual(data["Tipo"], "G")
        self.assertEqual(data["Sexo"], "M")
        self.assertEqual(data["Edad"], "2 años")

    def test_lee_un_json_envuelto_en_backticks(self):
        """El modelo suele responder con ```json ... ```; antes salía todo mal parseado."""

        data = self.service.parse_response(
            '```json\n{"nombre": "Rocco", "tipo": "perro", "sexo": "macho", "edad": "3 años"}\n```'
        )

        self.assertEqual(data["Nombre"], "Rocco")
        self.assertEqual(data["Tipo"], "P", "un perro se cargó como gato")

    def test_lee_un_dict_de_python(self):

        data = self.service.parse_response("{'nombre': 'Willy', 'tipo': 'gato'}")

        self.assertEqual(data["Nombre"], "Willy")

    def test_no_ejecuta_codigo_de_la_respuesta(self):
        """Con eval(), el caption de un post de Instagram podía ejecutar código en el server."""

        import os

        marca = os.path.join("/tmp", "catus-rce-no-deberia-existir")
        if os.path.exists(marca):
            os.remove(marca)

        payload = "__import__('pathlib').Path(%r).write_text('rce')" % marca

        data = self.service.parse_response(payload)

        self.assertFalse(os.path.exists(marca), "se ejecutó código de la respuesta del modelo")
        self.assertNotIn("Nombre", data)

    def test_una_respuesta_basura_no_rompe(self):

        for basura in ["", "no encontré nada", "{{{", None]:
            data = self.service.parse_response(basura)
            self.assertIn("response", data)

    def test_una_lista_no_se_toma_como_datos(self):

        data = self.service.parse_response('["Willy", "Rocco"]')

        self.assertNotIn("Nombre", data)

    def test_un_nombre_con_no_adentro_no_se_borra(self):
        """Comparando por subcadena, un perro llamado Bruno se quedaba sin nombre.

        Y el JS de la carga corta la precarga entera cuando el nombre viene vacío, asi
        que no se perdía sólo el nombre: se perdía toda la importación del post.
        """

        data = self.service.parse_response(
            '{"nombre": "Bruno", "tipo": "perro", "sexo": "macho", "edad": "2 años"}'
        )

        self.assertEqual(data["Nombre"], "Bruno")

        for nombre in ["Bruno", "Nono", "Manolo", "Antonio", "Bonita"]:
            self.assertEqual(self.service.clean_value(nombre), nombre, nombre)

    def test_una_edad_que_dice_no_se_sigue_quedando_vacia(self):

        data = self.service.parse_response(
            '{"nombre": "Willy", "tipo": "gato", "edad": "No se especifica."}'
        )

        self.assertEqual(data["Edad"], "")

        for valor in ["no", "No", "no se", "no corresponde", "No se menciona en el post."]:
            self.assertEqual(self.service.clean_value(valor), "", valor)


class RedirectsTest(TestCase):
    """El destino de un redirect vuelve a pasar por la allowlist antes de pedirlo.

    requests sigue los 3xx solo, asi que validar el link que pegó la persona no alcanza:
    un redirector abierto convertía un link de instagram.com en un pedido a la red
    interna, hecho por el server.
    """

    def _respuesta(self, status_code=200, content=b"", location=None):

        respuesta = mock.Mock()
        respuesta.status_code = status_code
        respuesta.content = content
        respuesta.headers = {"Location": location} if location else {}

        return respuesta

    def test_no_sigue_un_redirect_a_otro_host(self):

        for destino in [
            "http://169.254.169.254/latest/meta-data/",
            "https://l.instagram.com/?u=http://169.254.169.254/",
            "https://sitio-del-atacante.test/",
        ]:
            redirect = self._respuesta(302, location=destino)

            with mock.patch("catus.services.gpt.requests.get", return_value=redirect) as get:
                with self.assertRaises(ValueError, msg=destino):
                    GPTService()._get_html_title_and_images("https://www.instagram.com/p/abc/")

            #el post se pidió una vez y el destino del redirect no se pidió nunca
            self.assertEqual(get.call_count, 1, destino)
            self.assertFalse(get.call_args[1].get("allow_redirects", True), destino)

    def test_sigue_un_redirect_dentro_de_instagram(self):
        """instagram.com redirige a www.instagram.com: eso tiene que seguir andando."""

        redirect = self._respuesta(302, location="https://www.instagram.com/p/abc/")
        ok = self._respuesta(
            200,
            content=b'<html><head><meta property="og:title" content="Willy busca hogar">'
                    b"</head><body></body></html>",
        )

        with mock.patch("catus.services.gpt.requests.get", side_effect=[redirect, ok]) as get:
            texto, imagenes = GPTService()._get_html_title_and_images("https://instagram.com/p/abc/")

        self.assertEqual(texto, "Willy busca hogar")
        self.assertEqual(get.call_count, 2)

    def test_corta_un_bucle_de_redirects(self):

        redirect = self._respuesta(302, location="https://www.instagram.com/p/abc/")

        with mock.patch("catus.services.gpt.requests.get", return_value=redirect) as get:
            with self.assertRaises(ValueError):
                GPTService()._get_html_title_and_images("https://www.instagram.com/p/abc/")

        self.assertLessEqual(get.call_count, GPTService.MAX_REDIRECTS + 1)


class TimeoutDeOpenAITest(TestCase):

    def test_la_llamada_al_modelo_tiene_timeout(self):
        """Sin request_timeout el SDK 0.x espera 600s y el worker corta a los 30: el
        rescatista pegaba el link y se comía un 502."""

        pagina = mock.Mock()
        pagina.status_code = 200
        pagina.headers = {}
        pagina.content = (
            b'<html><head><meta property="og:title" content="Willy busca hogar">'
            b"</head><body></body></html>"
        )

        respuesta = {"choices": [{"message": {"content": '{"nombre": "Willy", "tipo": "gato"}'}}]}

        with mock.patch("catus.services.gpt.requests.get", return_value=pagina):
            with mock.patch("catus.services.gpt.openai.ChatCompletion.create", return_value=respuesta) as create:
                data = GPTService().pull_data_from_ig("https://www.instagram.com/p/abc/")

        self.assertEqual(data["Nombre"], "Willy")
        self.assertTrue(create.call_args[1].get("request_timeout"))
        self.assertLessEqual(create.call_args[1]["request_timeout"], 15)
