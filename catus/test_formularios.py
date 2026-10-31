"""Who can see an adoption form, and change its state.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_formularios
"""
import json
import uuid

from django.test import RequestFactory, TestCase


class FormularioTest(TestCase):
    """/formularios/<hash>/ shows the candidate's phone, email, address and answers.
    The link goes by mail to the team and to whoever loaded the animal, never to the
    adopter: it is theirs, and registration is open."""

    def setUp(self):
        from forms_builder.forms import fields
        from forms_builder.forms.models import FieldEntry, Form

        from catus.models import Animal, CatusUser, EstadoFormulario

        self.owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.stranger = CatusUser.objects.create(username="otro", email="otro@example.com")
        self.team = CatusUser.objects.create_superuser("equipo@example.com", password="x")

        self.animal = Animal.objects.create(nombre="Michi", cargado_por=self.owner, estado="D", tipo="G")
        self.ajeno = Animal.objects.create(nombre="Ajeno", cargado_por=self.stranger, estado="D", tipo="G")

        form = Form.objects.create(title="Pre adopción", slug="pre-adopcion")
        entry = form.entries.create(entry_time="2026-10-31 12:00:00+00:00")
        respuestas = [
            ("Gato", fields.TEXT, str(self.animal.id)),
            ("Nombre y Apellido", fields.TEXT, "Ana Adoptante"),
            ("Celular", fields.TEXT, "1155554444"),
            ("¿Por qué querés adoptar?", fields.TEXT, "<script>alert('xss')</script>"),
        ]
        for label, field_type, value in respuestas:
            field = form.fields.create(label=label, field_type=field_type, visible=True)
            FieldEntry.objects.create(entry=entry, field_id=field.id, value=value)

        self.hash = str(uuid.uuid4())
        self.estado = EstadoFormulario.objects.create(
            form_entry=entry, gato=self.animal, estado="N", hash=self.hash, tipo="A", persona_nombre="Ana Adoptante",
        )
        self.url = "/formularios/{}/".format(self.hash)

    def test_without_an_account_it_asks_to_log_in(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertNotIn(b"1155554444", response.content)

    def test_another_rescuer_cannot_open_it(self):
        self.client.force_login(self.stranger)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"1155554444", response.content)

    def test_the_rescuer_and_the_team_can(self):
        for user in (self.owner, self.team):
            self.client.force_login(user)
            response = self.client.get(self.url)

            self.assertEqual(response.status_code, 200, user.username)
            self.assertIn(b"1155554444", response.content)

    def test_an_answer_is_shown_as_text_not_run(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)

        self.assertNotIn(b"<script>alert('xss')</script>", response.content)
        self.assertIn(b"&lt;script&gt;", response.content)

    def assert_state_unchanged(self):
        self.estado.refresh_from_db()
        self.animal.refresh_from_db()
        self.assertEqual(self.estado.estado, "N")
        self.assertEqual(self.estado.gato_id, self.animal.id)
        self.assertEqual(self.animal.estado, "D")

    def test_without_an_account_the_state_cannot_change(self):
        response = self.client.post(self.url, {"estado": "A"})

        self.assertEqual(response.status_code, 302)
        self.assert_state_unchanged()

    def test_another_rescuer_cannot_change_the_state(self):
        self.client.force_login(self.stranger)
        response = self.client.post(self.url, {"estado": "A"})

        self.assertEqual(response.status_code, 403)
        self.assert_state_unchanged()

    def test_the_rescuer_cannot_move_the_form_to_someone_elses_animal(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {"estado": "N", "gato": self.ajeno.id})

        self.assertEqual(json.loads(response.content)["status"], "error")
        self.assert_state_unchanged()

    def test_the_rescuer_marks_the_adoption(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {"estado": "A"})

        self.assertEqual(json.loads(response.content), {"status": "ok", "estado": "A"})
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")
        self.assertIsNotNone(self.animal.fecha_adopcion)

    def test_the_list_of_every_form_is_gone(self):
        for user in (None, self.owner):
            if user:
                self.client.force_login(user)
            response = self.client.get("/formslist/?start=0&length=0&search[value]=a")
            self.assertEqual(response.status_code, 404)


class OpenSearchTest(TestCase):
    """The tables' search filters only by the view's own columns: it used to take
    field names from the browser, which turned the row count into an oracle."""

    def test_a_field_name_from_the_browser_is_not_searched(self):
        from catus.models import Animal, CatusUser, EstadoFormulario
        from catus.services.base import BaseService

        user = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        user.set_password("una-clave-larga")
        user.save()
        animal = Animal.objects.create(nombre="Michi", cargado_por=user, estado="D", tipo="G")
        EstadoFormulario.objects.create(gato=animal, hash="h1", persona_nombre="Ana")

        guess = user.password[:8]
        query = (
            "columns[0][searchable]=true&columns[0][search][value]=gato__cargado_por__password"
            "&search[value]={}&start=0&length=10".format(guess)
        )
        request = RequestFactory().get("/tabla/?" + query)

        response = BaseService().open_search(request, {0: "persona_nombre"}, {0: "persona_nombre"}, model=EstadoFormulario)

        self.assertEqual(json.loads(response.content)["iTotalRecords"], 0)
