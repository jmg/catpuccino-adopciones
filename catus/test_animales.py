"""Who can edit an animal, approve it, and act for the team.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_animales
"""
from unittest import mock

from django.core import mail
from django.test import TestCase


class AnimalPermissionsTest(TestCase):
    """Registration is open: having an account is not enough to touch someone
    else's animal."""

    def setUp(self):
        from catus.models import Animal, CatusUser

        self.owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.stranger = CatusUser.objects.create(username="otro", email="otro@example.com")
        self.team = CatusUser.objects.create_superuser("equipo@example.com", password="x")
        self.animal = Animal.objects.create(nombre="Michi", cargado_por=self.owner, estado="D", tipo="G", datos="Mimosa")

    def edit(self, nombre):
        # A photo URL that is not Instagram's: the form saves, nothing is fetched.
        return self.client.post("/animales/{}/".format(self.animal.id), {
            "tipo": "G", "estado": "D", "nombre": nombre, "edad": "2 años", "sexo": "H", "zona": "CABA",
            "datos": "Mimosa",
            "animalimage_set-TOTAL_FORMS": "0", "animalimage_set-INITIAL_FORMS": "0",
            "animalimage_set-MIN_NUM_FORMS": "0", "animalimage_set-MAX_NUM_FORMS": "1000",
            "instagram_image": ["https://example.com/foto.jpg"],
        })

    def test_another_account_cannot_open_or_edit_it(self):
        self.client.force_login(self.stranger)

        self.assertEqual(self.client.get("/animales/{}/".format(self.animal.id)).status_code, 403)
        self.assertEqual(self.edit("Robado").status_code, 403)

        self.animal.refresh_from_db()
        self.assertEqual((self.animal.nombre, self.animal.cargado_por_id), ("Michi", self.owner.id))

    def test_the_rescuer_edits_it(self):
        self.client.force_login(self.owner)

        self.assertEqual(self.edit("Michina").status_code, 302)

        self.animal.refresh_from_db()
        self.assertEqual((self.animal.nombre, self.animal.cargado_por_id), ("Michina", self.owner.id))

    def test_the_team_edits_it_and_it_stays_the_rescuers(self):
        self.client.force_login(self.team)

        self.assertEqual(self.edit("Michina").status_code, 302)

        self.animal.refresh_from_db()
        self.assertEqual((self.animal.nombre, self.animal.cargado_por_id), ("Michina", self.owner.id))

    def test_another_account_cannot_mark_it_adopted(self):
        self.client.force_login(self.stranger)

        self.client.post("/animal/marcaradoptado/", {"animal_id": self.animal.id})
        self.client.post("/animal/marcarexpirado/", {"animal_ids": [self.animal.id]})

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "D")

    def test_the_rescuer_marks_it_adopted(self):
        self.client.force_login(self.owner)

        self.client.post("/animal/marcaradoptado/", {"animal_id": self.animal.id})

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")


class ApproveTest(TestCase):
    """Approving publishes the animal on the site and mails its rescuer."""

    def setUp(self):
        from catus.models import Animal, CatusUser

        self.owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.team = CatusUser.objects.create_superuser("equipo@example.com", password="x")
        self.animal = Animal.objects.create(nombre="Michi", cargado_por=self.owner, estado="D", tipo="G")
        self.url = "/animal/aprobar/?id={}".format(self.animal.id)

    def approved(self):
        self.animal.refresh_from_db()
        return self.animal.aprobado

    def test_without_an_account_it_asks_to_log_in(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertFalse(self.approved())

    def test_a_rescuer_cannot_approve_even_their_own(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.approved())

    def test_the_team_approves(self):
        self.client.force_login(self.team)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.approved())


class TeamOnlyTest(TestCase):

    def setUp(self):
        from catus.models import CatusUser

        self.owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.team = CatusUser.objects.create_superuser("equipo@example.com", password="x")

    def test_the_ask_mail_is_the_teams_and_goes_as_text(self):
        data = {"user_id": self.owner.id, "content": "<a href='https://phish.example'>Entrá acá</a>"}

        self.client.post("/tools/sendpreguntaremail/", data)
        self.client.force_login(self.owner)
        self.client.post("/tools/sendpreguntaremail/", data)
        self.assertEqual(len(mail.outbox), 0)

        self.client.force_login(self.team)
        self.client.post("/tools/sendpreguntaremail/", data)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].alternatives[0][0]
        self.assertNotIn("<a href=", body)
        self.assertIn("&lt;a href=", body)

    def test_the_sites_instagram_account_is_linked_only_by_the_team(self):
        with mock.patch("catus.views.facebook.FacebookApiService") as service:
            self.client.post("/facebook/login/", {"access_token": "token-ajeno"})
            self.client.force_login(self.owner)
            self.client.post("/facebook/login/", {"access_token": "token-ajeno"})

        service.assert_not_called()
