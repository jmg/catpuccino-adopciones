"""The terms and privacy pages, and where the site links them.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_legal
"""
from django.test import TestCase


class LegalPagesTest(TestCase):

    def test_the_terms_and_the_privacy_policy_are_published(self):
        for url, title in (("/terminos/", "Términos y Condiciones de Uso"), ("/privacidad/", "Política de Privacidad")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, title)
            self.assertContains(response, "catpuccino.ok@gmail.com")

    def test_every_page_links_them_from_the_footer(self):
        response = self.client.get("/como-funciona/")
        self.assertContains(response, 'href="/terminos/"')
        self.assertContains(response, 'href="/privacidad/"')

    def test_signing_up_says_what_you_accept(self):
        response = self.client.get("/accounts/register/")
        self.assertContains(response, "Al crear tu cuenta aceptás")
        self.assertContains(response, 'href="/terminos/"')

    def test_the_sitemap_lists_them(self):
        response = self.client.get("/sitemap.xml")
        self.assertContains(response, "https://adopciones.catpuccino.org/terminos/")
        self.assertContains(response, "https://adopciones.catpuccino.org/privacidad/")
