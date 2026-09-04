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
        #el que carga el animal es el que después marca sus formularios
        self.rescatista = make_user()
        self.animal = make_animal(nombre="Willy", estado="D", cargado_por=self.rescatista)
        self.estado_form = make_estado_formulario(animal=self.animal, hash="abc123")

    def post(self, estado):

        request = self.factory.post("/formularios/abc123/", {
            "estado": estado,
            "gato": self.animal.id,
        })
        request.user = self.rescatista

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


class FormViewPostRobustezTest(TestCase):
    """El endpoint acepta POST directo, así que no puede confiar en lo que le llega."""

    def setUp(self):
        self.factory = RequestFactory()
        self.rescatista = make_user()
        self.animal = make_animal(nombre="Willy", estado="D", cargado_por=self.rescatista)
        self.estado_form = make_estado_formulario(animal=self.animal, hash="abc123", estado="N")

    def post(self, data):

        request = self.factory.post("/formularios/abc123/", data)
        request.user = self.rescatista

        view = FormView()
        view.request = request
        return view.post(form_hash="abc123")

    def test_un_post_sin_gato_no_borra_el_vinculo_con_el_animal(self):
        """El campo es opcional: al guardar sin él, el formulario perdía su animal."""

        self.post({"estado": "P"})

        self.estado_form.refresh_from_db()
        self.assertEqual(self.estado_form.gato, self.animal, "se perdió el animal del formulario")
        self.assertEqual(self.estado_form.estado, "P")

    def test_un_estado_invalido_no_rompe(self):
        """save() sin is_valid() levanta ValueError: 500 en vez de un mensaje."""

        import json

        response = self.post({"estado": "ZZZ", "gato": self.animal.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content.decode())["status"], "error")

    def test_un_estado_invalido_no_cambia_nada(self):

        self.post({"estado": "ZZZ", "gato": self.animal.id})

        self.estado_form.refresh_from_db()
        self.animal.refresh_from_db()
        self.assertEqual(self.estado_form.estado, "N")
        self.assertEqual(self.animal.estado, "D")

    def test_se_puede_cambiar_el_animal_a_proposito(self):

        otro = make_animal(nombre="Otro")

        self.post({"estado": "N", "gato": otro.id})

        self.estado_form.refresh_from_db()
        self.assertEqual(self.estado_form.gato, otro)


class FormViewPermisosTest(TestCase):
    """La vista se abre con el hash y sin login, así que el hash no puede ser la única llave.

    Un hash se consigue solo: te registrás, cargás un animal, completás el formulario
    público de ese animal y te llega por mail. Con uno cualquiera se marcaba "adoptado"
    cualquier animal del sitio, que es lo que lo saca del listado público.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.duenio = make_user(email="duenio@catpuccino.test")
        self.animal = make_animal(nombre="Willy", estado="D", cargado_por=self.duenio)
        self.estado_form = make_estado_formulario(animal=self.animal, hash="abc123")

    def post(self, user, estado="A"):

        request = self.factory.post("/formularios/abc123/", {
            "estado": estado,
            "gato": self.animal.id,
        })
        request.user = user

        view = FormView()
        view.request = request
        return view.post(form_hash="abc123")

    def test_un_ajeno_no_le_cambia_el_estado_al_animal_de_otro(self):

        import json

        response = self.post(make_user(email="ajeno@catpuccino.test"))

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "D", "un ajeno le marcó el animal como adoptado")
        self.assertIn(self.animal, Animal.get_all_for_adoption())
        self.assertEqual(json.loads(response.content.decode())["status"], "error")

    def test_un_anonimo_tampoco(self):

        from django.contrib.auth.models import AnonymousUser

        self.post(AnonymousUser())

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "D")

    def test_el_rescatista_del_animal_si_puede(self):

        self.post(self.duenio)

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")

    def test_el_equipo_si_puede(self):

        self.post(make_user(email="admin@catpuccino.test", is_superuser=True))

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")
