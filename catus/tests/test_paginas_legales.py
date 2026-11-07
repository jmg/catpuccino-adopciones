"""Las páginas de términos y de privacidad, y desde dónde las enlaza el sitio.

Corre con ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.tests.test_paginas_legales
"""
from django.test import TestCase


class PaginasLegalesTest(TestCase):

    def test_los_terminos_y_la_politica_de_privacidad_estan_publicados(self):
        for url, title in (("/terminos/", "Términos y Condiciones de Uso"), ("/privacidad/", "Política de Privacidad")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, title)
            self.assertContains(response, "catpuccino.ok@gmail.com")

    def test_todas_las_paginas_las_enlazan_desde_el_pie(self):
        response = self.client.get("/como-funciona/")
        self.assertContains(response, 'href="/terminos/"')
        self.assertContains(response, 'href="/privacidad/"')

    def test_el_registro_dice_que_se_acepta(self):
        response = self.client.get("/accounts/register/")
        self.assertContains(response, "Al crear tu cuenta aceptás")
        self.assertContains(response, 'href="/terminos/"')

    def test_el_sitemap_las_lista(self):
        response = self.client.get("/sitemap.xml")
        self.assertContains(response, "https://adopciones.catpuccino.org/terminos/")
        self.assertContains(response, "https://adopciones.catpuccino.org/privacidad/")
