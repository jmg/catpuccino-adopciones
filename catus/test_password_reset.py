"""Password reset mails: who gets them, and the scheme of their links.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_password_reset
"""
import unicodedata
from unittest import mock

from django.contrib.auth.forms import PasswordResetForm as DjangoPasswordResetForm
from django.core import mail
from django.test import TestCase


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold()


def lookup_as_mysql(form, email):
    """Django's lookup (email__iexact) as MySQL answers it in production:
    utf8mb4_unicode_ci ignores accents as well as case. sqlite does not, so the
    tests answer it here."""
    from catus.models import CatusUser

    return (u for u in CatusUser.objects.filter(is_active=True)
            if _fold(u.email) == _fold(email) and u.has_usable_password())


class PasswordResetTest(TestCase):
    """CVE-2019-19844: Django 2.0 mailed the reset link to the address typed, and
    MySQL found victima@gmail.com when asked for victima@gmáil.com."""

    def setUp(self):
        from catus.models import CatusUser

        self.victim = CatusUser.objects.create(email="victima@gmail.com", username="victima")
        self.victim.set_password("una-clave-de-la-victima")
        self.victim.save()

        patcher = mock.patch.object(DjangoPasswordResetForm, "get_users", lookup_as_mysql)
        patcher.start()
        self.addCleanup(patcher.stop)

    def reset(self, email, **headers):
        return self.client.post("/accounts/password_reset/", {"email": email}, **headers)

    def test_djangos_own_form_would_mail_the_accented_domain(self):
        # The lookup above reproduces the hole: Django 2.0's form sends the link
        # to whatever was typed.
        form = DjangoPasswordResetForm({"email": "victima@gmáil.com"})
        self.assertTrue(form.is_valid())
        form.save(domain_override="adopciones.catpuccino.org")

        self.assertEqual([m.to for m in mail.outbox], [["victima@gmáil.com"]])

    def test_an_accented_lookalike_gets_nothing(self):
        # The form takes it (it looks sent, as for any address) and mails nothing.
        response = self.reset("victima@gmáil.com", HTTP_X_FORWARDED_PROTO="https")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(mail.outbox, [])

        # Accents before the @ do not even pass Django 2.0's email validation;
        # either way, nothing goes out.
        for email in ("víctima@gmail.com", "VÍCTIMA@GMAIL.COM"):
            self.reset(email, HTTP_X_FORWARDED_PROTO="https")
            self.assertEqual(mail.outbox, [], email)

    def test_the_account_gets_it_at_its_own_address(self):
        response = self.reset("VICTIMA@Gmail.com", HTTP_X_FORWARDED_PROTO="https")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["victima@gmail.com"])
        html = message.alternatives[0][0] if message.alternatives else message.body
        self.assertIn("victima@gmail.com", html)
        self.assertNotIn("VICTIMA@Gmail.com", html)

    def test_behind_the_proxy_the_link_is_https(self):
        self.reset("victima@gmail.com", HTTP_X_FORWARDED_PROTO="https")

        self.assertIn("https://", mail.outbox[0].body)
        self.assertNotIn("http://", mail.outbox[0].body)

    def test_plain_http_is_answered_without_a_redirect(self):
        # The platform's health check reaches the container over http (nginx adds
        # X-Forwarded-Proto: https for /healthz, but nothing requires it).
        for headers in ({}, {"HTTP_X_FORWARDED_PROTO": "https"}):
            response = self.client.get("/accounts/login/", **headers)
            self.assertEqual(response.status_code, 200, headers)
