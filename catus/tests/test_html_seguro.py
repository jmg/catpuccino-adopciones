"""Tests del sanitizador de texto enriquecido.

La descripción del animal y la del perfil las escribe cualquiera que se registre y
se muestran en páginas públicas. Tienen que conservar el formato y no dejar pasar
nada que se ejecute.
"""
from django.template import Context, Template
from django.test import TestCase

from catus.services.html_seguro import sanitizar_html


class ConservaElFormatoTest(TestCase):

    def test_deja_pasar_el_formato_basico(self):

        html = "<p>Willy es <strong>muy</strong> compañero y <em>juguetón</em>.</p>"

        self.assertEqual(sanitizar_html(html), html)

    def test_deja_pasar_listas_y_saltos(self):

        html = "<ul><li>Castrado</li><li>Vacunado</li></ul><br>"

        self.assertEqual(sanitizar_html(html), html)

    def test_deja_pasar_un_link_normal(self):

        salida = sanitizar_html('<a href="https://instagram.com/catpuccino">Instagram</a>')

        self.assertIn('href="https://instagram.com/catpuccino"', salida)
        self.assertIn("Instagram", salida)

    def test_a_los_links_les_agrega_target_y_rel(self):

        salida = sanitizar_html('<a href="https://ejemplo.test">link</a>')

        self.assertIn('target="_blank"', salida)
        self.assertIn("noopener", salida)

    def test_conserva_el_texto_de_las_etiquetas_que_saca(self):

        salida = sanitizar_html("<div><span>Willy</span> busca hogar</div>")

        self.assertIn("Willy", salida)
        self.assertIn("busca hogar", salida)

    def test_los_acentos_quedan_bien(self):

        salida = sanitizar_html("<p>Es muy cariñoso y está castrado</p>")

        self.assertIn("cariñoso", salida)
        self.assertIn("está", salida)


class NoDejaPasarCodigoTest(TestCase):

    def test_saca_los_scripts(self):

        salida = sanitizar_html('Hola <script>fetch("/robar")</script>')

        self.assertNotIn("<script", salida)
        self.assertNotIn("fetch(", salida.replace("&", ""))

    def test_saca_los_manejadores_de_evento(self):

        salida = sanitizar_html('<p onclick="alert(1)">texto</p>')

        self.assertNotIn("onclick", salida)
        self.assertIn("texto", salida)

    def test_saca_las_imagenes_con_onerror(self):
        """Es el vector clásico: <img src=x onerror=...>."""

        salida = sanitizar_html('<img src=x onerror="alert(1)">')

        self.assertNotIn("<img", salida)
        self.assertNotIn("onerror", salida)

    def test_saca_los_href_con_javascript(self):

        for href in ["javascript:alert(1)", "JavaScript:alert(1)", " javascript:alert(1)",
                     "data:text/html,<script>alert(1)</script>"]:
            salida = sanitizar_html('<a href="{}">click</a>'.format(href))

            self.assertNotIn("javascript", salida.lower(), href)
            self.assertNotIn("data:", salida.lower(), href)
            self.assertIn("click", salida)

    def test_saca_iframes_y_objetos(self):

        for etiqueta in ["<iframe src='http://malo.test'></iframe>",
                         "<object data='x'></object>",
                         "<embed src='x'>",
                         "<form action='/x'><input name='y'></form>"]:
            salida = sanitizar_html(etiqueta)

            for prohibida in ("<iframe", "<object", "<embed", "<form", "<input"):
                self.assertNotIn(prohibida, salida, etiqueta)

    def test_saca_los_estilos(self):
        """style permite exfiltrar y tapar la pantalla."""

        salida = sanitizar_html('<p style="position:fixed;top:0;width:100%">tapando</p>')

        self.assertNotIn("style", salida)

    def test_el_texto_con_menor_que_se_escapa(self):

        salida = sanitizar_html("Pesa < 3 kg y mide > 20 cm")

        self.assertNotIn("< 3", salida)
        self.assertIn("&lt;", salida)

    def test_una_etiqueta_sin_cerrar_no_desarma_la_pagina(self):

        salida = sanitizar_html("<p>sin cerrar")

        self.assertEqual(salida.count("<p>"), 1)
        self.assertEqual(salida.count("</p>"), 1)

    def test_no_rompe_con_entradas_raras(self):

        for entrada in [None, "", "<<<>>>", "<p", "texto sin etiquetas", 12345]:
            self.assertIsInstance(sanitizar_html(entrada), str)


class FiltroDeTemplateTest(TestCase):

    def render(self, valor):

        return Template("{% load catus_html %}{{ valor|html_seguro }}").render(Context({"valor": valor}))

    def test_el_formato_se_ve(self):

        salida = self.render("<p>Willy es <strong>muy</strong> compañero</p>")

        self.assertIn("<strong>", salida)

    def test_el_script_no_llega_al_navegador(self):

        salida = self.render('<img src=x onerror="alert(1)">')

        self.assertNotIn("onerror", salida)
        self.assertNotIn("<img", salida)

    def test_un_valor_vacio_no_rompe(self):

        self.assertEqual(self.render(None), "")


class EsquemasSinUrlparseTest(TestCase):
    """El filtro de esquema no puede depender de urlparse.

    Los navegadores ignoran espacios y caracteres de control adentro del esquema, así
    que "java\\tscript:alert(1)" ejecuta igual. Que urlparse los saque depende de
    hardenings de CPython (bpo-43882, CVE-2023-24329) que llegaron en 2021 y 2023: si
    al Python de producción le falta alguno, ahí había un XSS almacenado en /<handle>/.
    """

    def test_bloquea_javascript_con_caracteres_de_control(self):

        for payload in [
            "java\tscript:alert(1)",
            "java\nscript:alert(1)",
            "java\rscript:alert(1)",
            "\x00javascript:alert(1)",
            "\x01javascript:alert(1)",
            "  javascript:alert(1)",
            "\x0bjavascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "javascript\x7f:alert(1)",
        ]:
            salida = sanitizar_html('<a href="{}">click</a>'.format(payload))

            self.assertNotIn("javascript", salida.lower(), "pasó: {!r}".format(payload))
            self.assertNotIn("href=", salida, "pasó: {!r}".format(payload))

    def test_bloquea_data_y_vbscript(self):

        for payload in ["data:text/html,<script>alert(1)</script>", "vbscript:msgbox(1)"]:
            salida = sanitizar_html('<a href="{}">click</a>'.format(payload))

            self.assertNotIn("href=", salida, "pasó: {!r}".format(payload))

    def test_deja_pasar_los_links_normales(self):

        for url in ["https://instagram.com/catpuccino", "http://ejemplo.test/a?b=1#c",
                    "mailto:hola@catpuccino.test", "/adopciones/", "../foto.jpg"]:
            salida = sanitizar_html('<a href="{}">link</a>'.format(url))

            self.assertIn("href=", salida, "bloqueó un link válido: {!r}".format(url))

    def test_un_link_relativo_con_dos_puntos_despues_de_la_barra_es_relativo(self):

        salida = sanitizar_html('<a href="/buscar/gato:negro">link</a>')

        self.assertIn("href=", salida)


class DatosRealesTest(TestCase):
    """Las descripciones que ya están cargadas usan solo p, strong, em, span y br.

    Se comprobó contra los snapshots del refugio (catus.sqlite y el backup de
    2025-06): cero div, img, table o headings. Las etiquetas que no están en la
    lista se descartan pero su texto se conserva, así que no se pierde nada.
    """

    def test_conserva_el_formato_que_realmente_se_usa(self):

        entrada = "<p>Es <strong>muy</strong> <em>mimoso</em>.</p><p>Castrado.<br>Vacunado.</p>"

        salida = sanitizar_html(entrada)

        for tag in ["<p>", "<strong>", "<em>", "<br>"]:
            self.assertIn(tag, salida)

    def test_una_etiqueta_que_no_esta_en_la_lista_no_se_lleva_el_texto(self):

        salida = sanitizar_html("<div>Primera</div><span>Segunda</span>")

        self.assertIn("Primera", salida)
        self.assertIn("Segunda", salida)
        self.assertNotIn("<div", salida)

    def test_no_se_permiten_imagenes_remotas(self):
        """Una imagen remota en una descripción pública registra la IP de quien la ve."""

        salida = sanitizar_html('<img src="https://rastreador.test/pixel.gif">')

        self.assertNotIn("<img", salida)
        self.assertNotIn("rastreador.test", salida)
