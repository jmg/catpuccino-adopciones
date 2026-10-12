"""Who can open an adopter's contract.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_contrato_acceso
"""
import uuid

from django.test import TestCase


class ContractAccessTest(TestCase):
    """The contract screens show the adopter's name, DNI, address and phone, by a
    sequential id: only the animal's rescuer and the team may open them."""

    def setUp(self):
        from catus.models import Animal, CatusUser, Contrato, ContratoPersona, EstadoFormulario

        self.owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.stranger = CatusUser.objects.create(username="otro", email="otro@example.com")
        self.team = CatusUser.objects.create_superuser("equipo@example.com", password="x")

        animal = Animal.objects.create(nombre="Michi", cargado_por=self.owner, estado="R", tipo="G")
        self.estado = EstadoFormulario.objects.create(gato=animal, estado="A", hash=str(uuid.uuid4()))
        adoptante = ContratoPersona.objects.create(persona_nombre="Ana Adoptante", persona_dni="30111222")
        self.contrato = Contrato.objects.create(
            hash=str(uuid.uuid4()), gato=animal, estado_formulario=self.estado, adoptante=adoptante,
        )

    def login(self, user):
        self.client.force_login(user)

    def test_without_an_account_the_contract_asks_to_log_in(self):
        response = self.client.get("/formulario/{}/contrato/".format(self.estado.id))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_another_rescuer_cannot_open_it(self):
        self.login(self.stranger)
        for url in (
            "/formulario/{}/contrato/".format(self.estado.id),
            "/formulario/{}/datos/".format(self.estado.id),
            "/contrato_adopcion/{}/download/".format(self.contrato.id),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, url)
            self.assertNotIn(b"30111222", response.content)

    def test_the_rescuer_and_the_team_can(self):
        for user in (self.owner, self.team):
            self.login(user)
            response = self.client.get("/formulario/{}/contrato/".format(self.estado.id))
            self.assertEqual(response.status_code, 200, user.username)

    def test_the_adopter_link_by_hash_stays_open(self):
        response = self.client.get("/contrato/{}/".format(self.contrato.hash))
        self.assertEqual(response.status_code, 200)
