"""Tests del seguimiento de formularios de adopción, el flujo que usa el admin.

La vista se llama directo con RequestFactory: el urlconf real lo arma
django-conventions recorriendo las clases, y eso pide levantar el proyecto entero.
"""
from django.test import RequestFactory, TestCase

from catus.models import Animal
from catus.tests.factories import make_animal, make_estado_formulario, make_user
from catus.views.forms import FormView


class FormViewPostTest(TestCase):
    """POST a /formularios/<hash>/ : es como el admin cambia el estado de un candidato."""

    def setUp(self):
        self.factory = RequestFactory()
        self.animal = make_animal(nombre="Willy", estado="D")
        self.estado_form = make_estado_formulario(animal=self.animal, hash="abc123")

    def post(self, estado):

        request = self.factory.post("/formularios/abc123/", {
            "estado": estado,
            "gato": self.animal.id,
        })
        request.user = make_user()

        view = FormView()
        view.request = request
        return view.post(form_hash="abc123")

    def test_marcar_reservado_no_rompe(self):
        """Antes explotaba: se escribía animal.reservado, un campo que no existe."""

        response = self.post("R")

        self.assertEqual(response.status_code, 200)
        self.estado_form.refresh_from_db()
        self.assertEqual(self.estado_form.estado, "R")

    def test_marcar_reservado_deja_al_animal_reservado(self):
        """Si el candidato reservó al animal, el animal tiene que salir de disponibles."""

        self.post("R")

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "R")
        self.assertNotIn(self.animal, Animal.get_all_for_adoption())

    def test_marcar_adoptado_pone_fecha_y_estado(self):

        self.post("A")

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")
        self.assertIsNotNone(self.animal.fecha_adopcion)

    def test_marcar_adoptado_no_pisa_una_fecha_existente(self):

        from django.utils import timezone

        fecha = timezone.now() - timezone.timedelta(days=5)
        self.animal.fecha_adopcion = fecha
        self.animal.save()

        self.post("A")

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.fecha_adopcion, fecha)

    def test_un_formulario_sin_animal_no_rompe(self):
        """Los formularios de tránsito no tienen animal asociado."""

        estado_form = make_estado_formulario(animal=None, hash="sin-animal")

        request = self.factory.post("/formularios/sin-animal/", {"estado": "R", "gato": ""})
        request.user = make_user(email="otro@catpuccino.test")
        view = FormView()
        view.request = request

        response = view.post(form_hash="sin-animal")

        self.assertEqual(response.status_code, 200)

    def test_devuelve_el_estado_nuevo(self):

        import json

        response = self.post("A")

        self.assertEqual(json.loads(response.content.decode())["estado"], "A")
