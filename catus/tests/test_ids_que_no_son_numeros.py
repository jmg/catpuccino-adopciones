"""Un id que no es un número es "no existe", no un 500.

Django castea el filtro por id a entero, así que un "abc" -un bot, un fetch a mano, un link
cortado- levantaba ValueError antes de llegar a la base. /animal/photos/ es pública (la usa
el formulario de pre-adopción), así que cualquiera podía sumar errores a Jentry.
"""
import json

from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory, TestCase

from catus.tests.factories import make_animal, make_user
from catus.views.animal import AddComment, MarcarAdoptado, PhotosView
from catus.views.user import SettingsLoginView


class IdsQueNoSonNumerosTest(TestCase):

    def setUp(self):
        self.duenio = make_user(email="duenio@catpuccino.test")
        self.admin = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)
        self.animal = make_animal(nombre="Willy", cargado_por=self.duenio)

    def llamar(self, vista, usuario, metodo="post", datos=None):
        request = getattr(RequestFactory(), metodo)("/", datos or {})
        request.user = usuario
        return vista.as_view()(request)

    def test_las_fotos_del_formulario_publico(self):

        respuesta = self.llamar(PhotosView, AnonymousUser(), datos={"animal_id": "abc"})

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(json.loads(respuesta.content)["photos_count"], 0)

    def test_las_fotos_de_un_animal_aprobado_siguen_saliendo(self):

        respuesta = self.llamar(PhotosView, AnonymousUser(), datos={"animal_id": str(self.animal.id)})

        self.assertIn("html", json.loads(respuesta.content))

    def test_marcar_adoptado(self):

        respuesta = self.llamar(MarcarAdoptado, self.duenio, datos={"animal_id": "abc"})

        self.assertEqual(json.loads(respuesta.content), {"success": False, "error": "No se encontró el animal."})

    def test_marcar_varios_con_uno_roto(self):

        self.llamar(MarcarAdoptado, self.duenio, datos={"animal_ids": ["abc", str(self.animal.id)]})

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")

    def test_la_nota_del_equipo(self):

        respuesta = self.llamar(AddComment, self.admin, datos={"user_id": "abc", "comment": "hola"})

        self.assertEqual(respuesta.content.decode(), "No se encontró el usuario.")

    def test_entrar_como_otro_usuario(self):

        for user_id in ("abc", "999999", None):
            datos = {"user_id": user_id} if user_id is not None else {}
            with self.assertRaises(Http404, msg=user_id):
                self.llamar(SettingsLoginView, self.admin, metodo="get", datos=datos)
