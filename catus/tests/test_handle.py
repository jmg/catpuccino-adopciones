"""Tests del handle, que es la URL pública del perfil del rescatista (/<handle>/).

Si dos personas quedan con el mismo handle, esa URL devuelve 500 para las dos.
"""
from django.test import TestCase

from catus.forms import CatusUserForm
from catus.models import CatusUser
from catus.services.validation import ValidationService
from catus.tests.factories import make_user


class BuildHandleTest(TestCase):

    def setUp(self):
        self.service = ValidationService()

    def test_usa_el_instagram_tal_cual_si_esta_libre(self):

        self.assertEqual(self.service.build_handle("catpuccino", None), "catpuccino")

    def test_limpia_los_caracteres_que_no_van(self):

        self.assertEqual(self.service.build_handle("@catpuccino.ok", None), "catpuccinook")

    def test_evita_repetir_uno_ya_usado(self):

        make_user(email="a@test.com", handle="catpuccino")

        self.assertNotEqual(self.service.build_handle("catpuccino", None), "catpuccino")

    def test_limpia_y_ademas_evita_repetir(self):
        """El caso que fallaba: se limpiaban los caracteres y ya no se rechequeaba."""

        make_user(email="a@test.com", handle="catpuccino")

        handle = self.service.build_handle("@catpuccino", None)

        self.assertTrue(self.service.esta_libre(handle, None), "propuso un handle ya usado")

    def test_sigue_buscando_hasta_encontrar_uno_libre(self):

        make_user(email="a@test.com", handle="catpuccino")
        make_user(email="b@test.com", handle="catpuccino_2")
        make_user(email="c@test.com", handle="catpuccino_3")

        handle = self.service.build_handle("catpuccino", None)

        self.assertTrue(self.service.esta_libre(handle, None))

    def test_sin_nada_util_no_inventa_handle(self):

        self.assertIsNone(self.service.build_handle("...", None))
        self.assertIsNone(self.service.build_handle("", None))
        self.assertIsNone(self.service.build_handle(None, None))

    def test_el_propio_handle_no_cuenta_como_ocupado(self):

        user = make_user(email="a@test.com", handle="catpuccino")

        self.assertTrue(self.service.esta_libre("catpuccino", user))


class CatusUserFormHandleTest(TestCase):

    def datos(self, handle, email="yo@test.com"):

        return {
            "handle": handle, "email": email, "title": "", "description": "",
            "facebook": "", "twitter": "", "instagram": "",
        }

    def test_rechaza_un_handle_ya_usado(self):
        """La pantalla lo chequea por AJAX, pero eso no alcanza si mandan el POST directo."""

        make_user(email="otra@test.com", handle="catpuccino")
        yo = make_user(email="yo@test.com")

        form = CatusUserForm(self.datos("catpuccino"), instance=yo)

        self.assertFalse(form.is_valid())
        self.assertIn("handle", form.errors)

    def test_acepta_conservar_el_propio(self):

        yo = make_user(email="yo@test.com", handle="catpuccino")

        form = CatusUserForm(self.datos("catpuccino"), instance=yo)

        self.assertTrue(form.is_valid(), form.errors)

    def test_rechaza_caracteres_invalidos(self):

        yo = make_user(email="yo@test.com")

        form = CatusUserForm(self.datos("cat puccino!"), instance=yo)

        self.assertFalse(form.is_valid())
        self.assertIn("handle", form.errors)

    def test_permite_dejarlo_vacio(self):

        yo = make_user(email="yo@test.com")

        form = CatusUserForm(self.datos(""), instance=yo)

        self.assertTrue(form.is_valid(), form.errors)

    def test_dos_perfiles_vacios_no_chocan(self):
        """handle vacío no es un handle: no puede contar como repetido."""

        make_user(email="otra@test.com", handle="")
        yo = make_user(email="yo@test.com")

        form = CatusUserForm(self.datos(""), instance=yo)

        self.assertTrue(form.is_valid(), form.errors)
