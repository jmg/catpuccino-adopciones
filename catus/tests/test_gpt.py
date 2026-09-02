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
