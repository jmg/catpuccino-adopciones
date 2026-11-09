"""Guardar un animal es todo o nada: si falla una foto, no queda nada a medias.

EditView guardaba el animal primero y las fotos después. Cuando una foto fallaba
(ADOPCIONES-3SVEZ, 2026-11-08: un nombre de archivo que Django no podía acortar), el alta
daba error pero el animal quedaba guardado, sin fotos y sin revisión: dos intentos dejaron
dos animales a medias, y el tercero lo frenaba el control de duplicados contra uno de ellos.
"""
import shutil
import tempfile
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings

from catus.models import Animal, AnimalImage
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo
from catus.views.animal import EditView


class FallaAlProcesarLaFoto(Exception):
    pass


class AltaTodoONadaTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(self.override.disable)

        self.rescatista = make_user(email="todo-o-nada@catpuccino.test")

    def guardar(self, url, datos, **kwargs):

        request = RequestFactory().post(url, datos)
        request.user = self.rescatista
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()

        with mock.patch("catus.views.animal.MailService"):
            return EditView.as_view(template_name="animal/edit.html")(request, **kwargs)

    def datos(self, filas, ya_guardadas=0, edad="1 año"):

        return {
            "tipo": "G", "estado": "D", "nombre": "Toto", "edad": edad, "sexo": "M",
            "zona": "CABA", "datos": "<p>Muy tranquilo.</p>",
            "animalimage_set-TOTAL_FORMS": str(filas),
            "animalimage_set-INITIAL_FORMS": str(ya_guardadas),
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
        }

    def foto_nueva(self, indice):

        prefijo = "animalimage_set-{}-".format(indice)
        return {prefijo + "id": "", prefijo + "animal": "", prefijo + "crop_x": "", prefijo + "crop_y": "",
                prefijo + "crop_w": "", prefijo + "crop_h": "", prefijo + "image": uploaded_photo(color=(30, 140, 90))}

    def test_si_falla_la_foto_en_un_alta_no_queda_el_animal(self):

        datos = self.datos(filas=1)
        datos.update(self.foto_nueva(0))

        with mock.patch("catus.views.animal.ImageService.optimize", side_effect=FallaAlProcesarLaFoto):
            with self.assertRaises(FallaAlProcesarLaFoto):
                self.guardar("/animales/", datos)

        self.assertFalse(Animal.objects.filter(cargado_por=self.rescatista).exists(),
                         "el alta falló y el animal quedó guardado a medias")
        self.assertFalse(AnimalImage.objects.exists())

    def test_despues_de_una_falla_el_reintento_entra(self):
        """Sin el animal a medias, el control de duplicados no frena el segundo intento."""

        datos = self.datos(filas=1)
        datos.update(self.foto_nueva(0))
        with mock.patch("catus.views.animal.ImageService.optimize", side_effect=FallaAlProcesarLaFoto):
            with self.assertRaises(FallaAlProcesarLaFoto):
                self.guardar("/animales/", datos)

        datos = self.datos(filas=1)
        datos.update(self.foto_nueva(0))
        response = self.guardar("/animales/", datos)

        self.assertEqual(response.status_code, 302)
        animal = Animal.objects.get(cargado_por=self.rescatista)
        self.assertEqual(animal.animalimage_set.count(), 1)

    def test_si_falla_una_foto_nueva_en_una_edicion_no_se_guarda_nada_de_la_edicion(self):

        animal = make_animal(nombre="Toto", tipo="G", sexo="M", edad="1 año", zona="CABA", cargado_por=self.rescatista)
        guardada = make_animal_image(animal=animal)

        datos = self.datos(filas=2, ya_guardadas=1, edad="2 años")
        datos.update({"animalimage_set-0-id": str(guardada.id), "animalimage_set-0-animal": str(animal.id),
                      "animalimage_set-0-crop_x": "", "animalimage_set-0-crop_y": "",
                      "animalimage_set-0-crop_w": "", "animalimage_set-0-crop_h": ""})
        datos.update(self.foto_nueva(1))

        with mock.patch("catus.views.animal.ImageService.optimize", side_effect=FallaAlProcesarLaFoto):
            with self.assertRaises(FallaAlProcesarLaFoto):
                self.guardar("/animales/{}/".format(animal.id), datos, animal_id=animal.id)

        animal.refresh_from_db()
        self.assertEqual(animal.edad, "1 año", "se guardó la edad de una edición que falló")
        self.assertEqual(list(animal.animalimage_set.values_list("id", flat=True)), [guardada.id])
