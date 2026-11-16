"""Topes del registro y del "me olvidé la contraseña", las dos páginas abiertas que más
cuesta dejar sin tope.

El registro es abierto y cada cuenta trae su cupo de revisiones con IA y de lecturas de
Instagram: abrir cuentas en serie es la forma de saltarse los topes por persona. Y el
reseteo le manda un mail a la dirección que se escriba: sin tope, un bucle le llenaba la
casilla a cualquier rescatista. Los dos cuentan en el memcached del contenedor
(catus/services/throttle.py), y con memcached caído tienen que seguir andando.
"""
from unittest import mock

from django.core import mail
from django.test import TestCase

from catus import auth
from catus.models import CatusUser
from catus.test_login_throttle import fake_memcached
from catus.tests.factories import make_user
from catus.views import user as vistas_de_usuario

CLAVE = "una-clave-larga-y-rara-2026"
VISITANTE = "190.2.3.4"


class TopeTest(TestCase):

    def setUp(self):
        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)


class RegistroTest(TopeTest):

    def registrar(self, email, conexion=VISITANTE, clave=CLAVE):
        self.client.logout()
        return self.client.post("/accounts/register/", {
            "email": email, "instagram": email.split("@")[0], "password1": clave, "password2": clave,
        }, HTTP_X_FORWARDED_FOR=conexion)

    def test_unas_pocas_cuentas_desde_la_misma_conexion_pasan(self):

        for n in range(vistas_de_usuario.REGISTRO_MAX_CUENTAS_POR_DIA):
            respuesta = self.registrar("refugio{}@ejemplo.test".format(n))
            self.assertEqual(respuesta.status_code, 302, n)

        self.assertEqual(CatusUser.objects.count(), vistas_de_usuario.REGISTRO_MAX_CUENTAS_POR_DIA)

    def test_pasado_el_tope_no_crea_la_cuenta_y_dice_por_que(self):

        for n in range(vistas_de_usuario.REGISTRO_MAX_CUENTAS_POR_DIA):
            self.registrar("refugio{}@ejemplo.test".format(n))

        respuesta = self.registrar("otra@ejemplo.test")

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Hoy ya se crearon varias cuentas desde tu conexión")
        self.assertFalse(CatusUser.objects.filter(email="otra@ejemplo.test").exists())

    def test_el_tope_es_por_conexion(self):

        for n in range(vistas_de_usuario.REGISTRO_MAX_CUENTAS_POR_DIA):
            self.registrar("refugio{}@ejemplo.test".format(n))

        respuesta = self.registrar("otra@ejemplo.test", conexion="190.9.9.9")

        self.assertEqual(respuesta.status_code, 302)

    def test_los_intentos_fallidos_tambien_tienen_tope(self):
        """Quien prueba mails de a uno para ver cuáles ya tienen cuenta no crea ninguna."""

        make_user(email="ya@ejemplo.test")
        for _ in range(vistas_de_usuario.REGISTRO_MAX_INTENTOS_POR_HORA):
            self.assertContains(self.registrar("ya@ejemplo.test"), "Ya hay una cuenta con ese mail")

        respuesta = self.registrar("nueva@ejemplo.test")

        self.assertContains(respuesta, "demasiados intentos de registro")
        self.assertFalse(CatusUser.objects.filter(email="nueva@ejemplo.test").exists())

    def test_sin_memcached_el_registro_sigue_andando(self):

        with mock.patch("catus.services.throttle._memcached", side_effect=OSError("refused")):
            for n in range(vistas_de_usuario.REGISTRO_MAX_CUENTAS_POR_DIA + 2):
                self.assertEqual(self.registrar("refugio{}@ejemplo.test".format(n)).status_code, 302)


class CambiarLaContrasenaTest(TopeTest):

    def setUp(self):
        super().setUp()
        self.rescatista = make_user(email="rescatista@ejemplo.test")
        self.rescatista.set_password(CLAVE)
        self.rescatista.save()

    def pedir(self, email="rescatista@ejemplo.test", conexion=VISITANTE):
        return self.client.post("/accounts/password_reset/", {"email": email},
                                HTTP_X_FORWARDED_FOR=conexion, HTTP_X_FORWARDED_PROTO="https")

    def test_un_pedido_normal_manda_el_mail(self):

        respuesta = self.pedir()

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual([m.to for m in mail.outbox], [["rescatista@ejemplo.test"]])

    def test_una_casilla_recibe_pocos_aunque_pidan_desde_muchas_conexiones(self):

        for n in range(auth.RESET_MAX_POR_DIA_POR_MAIL + 3):
            self.pedir(conexion="190.3.3.{}".format(n + 1))
        respuesta = self.pedir(email="RESCATISTA@Ejemplo.test", conexion="190.4.4.4")

        self.assertEqual(len(mail.outbox), auth.RESET_MAX_POR_DIA_POR_MAIL)
        self.assertContains(respuesta, "Ya mandamos varios mails para cambiar la contraseña")

    def test_una_conexion_tiene_tope_aunque_cambie_de_mail(self):

        for n in range(auth.RESET_MAX_POR_HORA):
            self.assertEqual(self.pedir(email="nadie{}@ejemplo.test".format(n)).status_code, 302)

        respuesta = self.pedir()

        self.assertContains(respuesta, "Pediste demasiados cambios de contraseña desde tu conexión")
        self.assertEqual(mail.outbox, [])

    def test_el_tope_no_dice_que_direcciones_tienen_cuenta(self):
        """Una dirección sin cuenta llega al tope igual que una con cuenta."""

        for n in range(auth.RESET_MAX_POR_DIA_POR_MAIL):
            self.pedir(email="nadie@ejemplo.test", conexion="190.5.5.{}".format(n + 1))

        respuesta = self.pedir(email="nadie@ejemplo.test", conexion="190.6.6.6")

        self.assertContains(respuesta, "Ya mandamos varios mails")

    def test_en_memcached_no_queda_el_mail(self):

        store = {}
        from catus.test_login_throttle import FakeMemcached

        with mock.patch("catus.services.throttle._memcached", side_effect=lambda: FakeMemcached(store)):
            self.pedir()

        self.assertTrue(store)
        self.assertNotIn("rescatista", " ".join(store))

    def test_sin_memcached_sigue_andando(self):

        with mock.patch("catus.services.throttle._memcached", side_effect=OSError("refused")):
            for _ in range(auth.RESET_MAX_POR_DIA_POR_MAIL + 2):
                self.assertEqual(self.pedir().status_code, 302)

        self.assertEqual(len(mail.outbox), auth.RESET_MAX_POR_DIA_POR_MAIL + 2)
