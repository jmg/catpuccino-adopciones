"""Los errores del registro, en español y diciendo qué hacer.

El sitio tenía apagadas las traducciones de Django (USE_I18N = False), así que a quien
se registraba con un mail ya usado le salía "User with this Email already exists." y a
quien escribía mal la segunda contraseña, "The two password fields didn't match.".
"""
from django.test import TestCase

from catus.forms import SignupForm
from catus.tests.factories import make_user

BUENA = "una-clave-larga-y-rara-2026"


class ErroresDelRegistroTest(TestCase):

    def datos(self, **cambios):
        datos = {"email": "nueva@ejemplo.test", "instagram": "nueva", "password1": BUENA, "password2": BUENA}
        datos.update(cambios)
        return datos

    def test_un_registro_bien_hecho_es_valido(self):
        self.assertTrue(SignupForm(data=self.datos()).is_valid())

    def test_el_mail_repetido_dice_que_hacer(self):
        make_user(email="ya@ejemplo.test")

        form = SignupForm(data=self.datos(email="ya@ejemplo.test"))

        self.assertFalse(form.is_valid())
        self.assertEqual(len(form.errors["email"]), 1)
        self.assertIn("Ya hay una cuenta con ese mail", form.errors["email"][0])

    def test_las_contrasenas_distintas_se_avisan_en_espanol(self):
        form = SignupForm(data=self.datos(password2="otra-cosa-distinta-9"))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["password2"], ["Las dos contraseñas no son iguales. Escribilas de nuevo."])

    def test_los_mensajes_de_django_salen_en_espanol(self):
        form = SignupForm(data=self.datos(email="", password1="12345678901", password2="12345678901"))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["email"], ["Este campo es obligatorio."])
        self.assertIn("completamente por dígitos", " ".join(form.errors["password2"]))

    def test_la_etiqueta_de_la_segunda_contrasena_esta_bien_escrita(self):
        self.assertEqual(SignupForm().fields["password2"].label, "Confirmar contraseña")
