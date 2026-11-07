"""El token con el que el sitio publica en Instagram no se puede perder en silencio.

En enero de 2026 venció el token de usuario y la publicación quedó cortada diez meses
sin que nadie se enterara. Ahora se guarda el token de la página, que no vence, y
refresh_token lo revisa todos los días y le avisa al equipo si hay que reconectar.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings

from catus.models import FacebookAccount
from catus.services.facebook import FacebookApiService
from catus.tests.factories import make_animal, make_user


def pagina(nombre, ig_id):

    return {"full_name": nombre, "username": None, "bio": None, "website": None,
            "profile_picture": None, "instagram_account_id": ig_id, "remote_id": ig_id}


class ConectarInstagramTest(TestCase):

    def setUp(self):

        self.factory = RequestFactory()
        self.equipo = make_user(email="equipo@catpuccino.test", is_superuser=True, is_staff=True)

    def conectar(self, paginas):

        from catus.views.facebook import LoginView

        request = self.factory.post("/facebook/login/", {"access_token": "token-corto"})
        request.user = self.equipo
        SessionMiddleware(lambda request: None).process_request(request)

        with mock.patch.object(FacebookApiService, "get_instagram_accounts", return_value=([], [], paginas)), \
                mock.patch.object(FacebookApiService, "get_long_lived_token", return_value=("token-largo-de-usuario", 5184000)), \
                mock.patch.object(FacebookApiService, "get_page_token", return_value="token-de-la-pagina") as page_token:
            response = LoginView.as_view()(request)

        return response, page_token

    def test_guarda_el_token_de_la_pagina_que_no_vence(self):

        response, page_token = self.conectar({"p1": pagina("Adopciones Catpuccino", "ig1")})

        cuenta = FacebookAccount.objects.get()
        self.assertEqual(cuenta.facebook_token, "token-de-la-pagina", "se guardó el token de usuario, que vence a los 60 días")
        self.assertIsNone(cuenta.facebook_token_expire_at)
        page_token.assert_called_once_with("token-largo-de-usuario", "p1")
        self.assertIn("Adopciones Catpuccino", response.content.decode())

    def test_no_guarda_una_pagina_sin_instagram_aunque_venga_ultima(self):
        """Antes se quedaba la última página que devolvía Facebook, tuviera Instagram o no."""

        self.conectar({"p1": pagina("Adopciones Catpuccino", "ig1"), "p2": pagina("Otra página", None)})

        cuenta = FacebookAccount.objects.get()
        self.assertEqual((cuenta.remote_id, cuenta.business_account_id), ("p1", "ig1"))

    def test_al_reconectar_se_queda_la_misma_cuenta(self):

        FacebookAccount.objects.create(remote_id="p2", business_account_id="ig2", facebook_token="viejo")

        self.conectar({"p1": pagina("Hard Tech Store", "ig1"), "p2": pagina("Adopciones Catpuccino", "ig2")})

        cuenta = FacebookAccount.objects.get()
        self.assertEqual(cuenta.business_account_id, "ig2", "al reconectar el sitio pasó a publicar en otra cuenta")
        self.assertEqual(cuenta.facebook_token, "token-de-la-pagina")

    def test_sin_ninguna_pagina_con_instagram_no_toca_nada(self):

        FacebookAccount.objects.create(remote_id="p2", business_account_id="ig2", facebook_token="viejo")

        response, page_token = self.conectar({"p1": pagina("Otra página", None)})

        self.assertEqual(FacebookAccount.objects.get().facebook_token, "viejo")
        self.assertFalse(page_token.called)
        self.assertIn("Instagram", response.content.decode())


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test", SSL_HOST="https://adopciones.test")
class RevisarTokenTest(TestCase):

    def setUp(self):

        self.cuenta = FacebookAccount.objects.create(
            full_name="Adopciones Catpuccino", remote_id="p1", business_account_id="ig1",
            facebook_token="token-secreto-123",
        )
        self.animal = make_animal()

    def en_dias(self, dias):

        return int((datetime.now(dt_timezone.utc) + timedelta(days=dias)).timestamp())

    def correr(self, info, instagram=None, page_token="token-de-la-pagina", info_pagina=None):

        out = StringIO()
        debug = mock.Mock(side_effect=[info, info_pagina or {}])

        with mock.patch.object(FacebookApiService, "debug_token", debug), \
                mock.patch.object(FacebookApiService, "get_page_token", return_value=page_token) as get_page, \
                mock.patch.object(FacebookApiService, "check_instagram", side_effect=instagram) as check:
            call_command("refresh_token", stdout=out)

        return out.getvalue(), get_page, check

    def test_un_token_de_pagina_sano_no_molesta_a_nadie(self):

        salida, get_page, check = self.correr({"is_valid": True, "type": "PAGE", "expires_at": 0, "data_access_expires_at": self.en_dias(80)})

        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(check.called, "no se probó que Instagram conteste")
        self.assertFalse(get_page.called)
        self.assertIn("no vence", salida)

    def test_un_token_de_usuario_se_cambia_por_el_de_la_pagina(self):

        self.correr(
            {"is_valid": True, "type": "USER", "expires_at": self.en_dias(59), "data_access_expires_at": self.en_dias(89)},
            info_pagina={"is_valid": True, "type": "PAGE", "expires_at": 0, "data_access_expires_at": self.en_dias(89)},
        )

        self.cuenta.refresh_from_db()
        self.assertEqual(self.cuenta.facebook_token, "token-de-la-pagina")
        self.assertIsNone(self.cuenta.facebook_token_expire_at)
        self.assertEqual(len(mail.outbox), 0)

    def test_si_dejo_de_andar_le_avisa_al_equipo_y_el_cron_queda_en_rojo(self):

        with self.assertRaises(CommandError):
            self.correr({"is_valid": False, "error": {"message": "Session has expired"}})

        self.assertEqual(len(mail.outbox), 1)
        aviso = mail.outbox[0]
        self.assertEqual(aviso.to, ["catpuccino.ok@gmail.com"])
        self.assertIn("Session has expired", aviso.body)
        self.assertIn("https://adopciones.test/tools/generarimagen/{}/".format(self.animal.id), aviso.body)

    def test_avisa_antes_de_que_facebook_corte_el_acceso(self):

        with self.assertRaises(CommandError):
            self.correr({"is_valid": True, "type": "PAGE", "expires_at": 0, "data_access_expires_at": self.en_dias(5)})

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("90 días", mail.outbox[0].body)

    def test_si_instagram_no_contesta_tambien_avisa(self):

        with self.assertRaises(CommandError):
            self.correr({"is_valid": True, "type": "PAGE", "expires_at": 0, "data_access_expires_at": self.en_dias(80)},
                        instagram=Exception("permiso revocado"))

        self.assertIn("permiso revocado", mail.outbox[0].body)

    def test_si_no_se_puede_preguntar_a_facebook_no_manda_mail_pero_falla(self):

        out = StringIO()
        with mock.patch.object(FacebookApiService, "debug_token", side_effect=Exception("timeout")):
            with self.assertRaises(CommandError):
                call_command("refresh_token", stdout=out)

        self.assertEqual(len(mail.outbox), 0)

    def test_nunca_escribe_el_token_en_el_log(self):
        """Antes imprimía el token nuevo: quedaba en los logs del cron."""

        salida, _, _ = self.correr(
            {"is_valid": True, "type": "USER", "expires_at": self.en_dias(59), "data_access_expires_at": self.en_dias(89)},
            info_pagina={"is_valid": True, "type": "PAGE", "expires_at": 0, "data_access_expires_at": self.en_dias(89)},
        )

        self.assertNotIn("token-secreto-123", salida)
        self.assertNotIn("token-de-la-pagina", salida)

    def test_sin_cuenta_conectada_avisa(self):

        FacebookAccount.objects.all().delete()

        with self.assertRaises(CommandError):
            call_command("refresh_token", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 1)
