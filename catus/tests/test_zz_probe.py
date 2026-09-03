"""Probe: reemplazar y borrar fotos en la edicion."""
from unittest import mock
from django.test import TestCase, RequestFactory

from catus.models import Animal
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo
from catus.views.animal import EditView


class FotosTest(TestCase):

    def setUp(self):
        self.user = make_user(email="r@x.test")
        self.animal = make_animal(nombre="Willy", cargado_por=self.user, edad="1",
                                  zona="CABA", datos="<p>x</p>", sexo="M", tipo="G")
        self.a = make_animal_image(animal=self.animal)
        self.b = make_animal_image(animal=self.animal)

    def _base(self):
        return {
            "nombre": "Willy", "edad": "1", "zona": "CABA", "datos": "<p>x</p>",
            "sexo": "M", "tipo": "G", "estado": "D",
            "animalimage_set-TOTAL_FORMS": "2",
            "animalimage_set-INITIAL_FORMS": "2",
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
            "animalimage_set-0-id": str(self.a.id),
            "animalimage_set-1-id": str(self.b.id),
        }

    def _post(self, data, files=None):
        req = RequestFactory().post("/animales/%s/" % self.animal.id, data)
        if files:
            req.FILES.update(files)
        req.user = self.user
        req.session = {}
        with mock.patch("catus.views.animal.ModeracionService") as m, \
             mock.patch("catus.views.animal.MailService"):
            m.return_value.revisar_y_guardar.return_value = Animal.REVISION_OK
            return EditView.as_view(template_name="animal/edit.html")(req)

    def test_reemplaza_una_foto(self):
        vieja_a, vieja_b = self.a.image.name, self.b.image.name
        r = self._post(self._base(), {"animalimage_set-0-image": uploaded_photo(name="nueva.jpg", size=(1500, 1000))})
        print("reemplazo status:", r.status_code, r.context_data.get("errors") if r.status_code == 200 else "")
        self.a.refresh_from_db(); self.b.refresh_from_db()
        print("  a cambio:", self.a.image.name != vieja_a, "| b intacta:", self.b.image.name == vieja_b,
              "| crop a:", self.a.get_crop())

    def test_borra_las_dos(self):
        d = self._base()
        d["animalimage_set-0-DELETE"] = "on"
        d["animalimage_set-1-DELETE"] = "on"
        r = self._post(d)
        print("borrar todas status:", r.status_code)
        if r.status_code == 200:
            print("  errores:", r.context_data.get("errors"))
        print("  fotos que quedan:", self.animal.animalimage_set.count())

    def test_borra_una(self):
        d = self._base()
        d["animalimage_set-1-DELETE"] = "on"
        r = self._post(d)
        print("borrar una status:", r.status_code,
              r.context_data.get("errors") if r.status_code == 200 else "")
        print("  fotos que quedan:", self.animal.animalimage_set.count())
