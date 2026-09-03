"""Sonda temporal de la revision ia-integracion. BORRAR antes de commitear."""
import os
import shutil
import tempfile
import time
from unittest import mock

from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.test import TestCase, RequestFactory, override_settings

from catus.models import Animal, AnimalImage
from catus.services.moderacion import ModeracionService
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST")
class GuardadoDeAnimalTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        os.makedirs(os.path.join(self.media, "gallery"), exist_ok=True)
        self.factory = RequestFactory()
        self.user = make_user(email="resc@catpuccino.test", automatic_approve=True)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def post_data(self, con_foto=True, total=1):
        datos = {
            "tipo": "G", "estado": "D", "nombre": "Willy", "edad": "2 meses",
            "sexo": "M", "zona": "Palermo", "datos": "<p>Gatito en adopcion</p>",
            "animalimage_set-TOTAL_FORMS": str(total),
            "animalimage_set-INITIAL_FORMS": "0",
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
        }
        for i in range(total):
            p = "animalimage_set-{}-".format(i)
            datos[p + "crop_x"] = ""
            datos[p + "crop_y"] = ""
            datos[p + "crop_w"] = ""
            datos[p + "crop_h"] = ""
            if con_foto:
                datos[p + "image"] = uploaded_photo(name="foto{}.jpg".format(i), size=(2400, 1600))
        return datos

    def guardar(self, animal_id=None, **kw):
        from catus.views.animal import EditView

        url = "/animales/{}/".format(animal_id) if animal_id else "/animales/"
        request = self.factory.post(url, self.post_data(**kw))
        request.user = self.user
        request.session = SessionStore()

        view = EditView()
        view.request = request
        kwargs = {"animal_id": str(animal_id)} if animal_id else {}
        return view.req(is_post=True, **kwargs), request

    def test_content_none_ya_no_rompe(self):
        with mock.patch.object(ModeracionService, "_preguntar", return_value=None):
            response, request = self.guardar()
        self.assertEqual(response.status_code, 302)
        animal = Animal.objects.get(nombre="Willy")
        self.assertEqual(animal.revision_ia_estado, Animal.REVISION_ERROR)
        self.assertTrue(animal.aprobado, "con error de IA se aprueba igual")

    def test_que_fotos_ve_la_ia(self):
        """La IA, ¿lee la foto original o la optimizada?"""

        vistas = {}
        original = ModeracionService._leer_fotos

        def espia(self, animal):
            from PIL import Image
            from io import BytesIO
            import base64
            fotos = original(self, animal)
            for f in fotos:
                crudo = base64.b64decode(f.split(",", 1)[1])
                vistas["tam"] = Image.open(BytesIO(crudo)).size
            vistas["nombres"] = [i.image.name for i in animal.get_images()]
            vistas["existe"] = [os.path.exists(i.image.path) for i in animal.get_images()]
            return fotos

        with mock.patch.object(ModeracionService, "_leer_fotos", espia):
            with mock.patch.object(ModeracionService, "_preguntar",
                                   return_value='{"animales": ["gato"], "descripcion": "un gato"}'):
                response, request = self.guardar()

        print("\n>>> VISTAS POR LA IA:", vistas)
        animal = Animal.objects.get(nombre="Willy")
        from PIL import Image
        for img in animal.get_images():
            print(">>> en disco al final:", img.image.name, Image.open(img.image.path).size,
                  "crop:", img.get_crop())
        self.assertTrue(vistas["existe"], vistas)

    def test_editar_no_revisa(self):
        """Al editar un animal existente, ¿se re-revisa?"""

        with mock.patch.object(ModeracionService, "_preguntar",
                               return_value='{"animales": ["gato"], "descripcion": "un gato"}'):
            self.guardar()

        animal = Animal.objects.get(nombre="Willy")
        Animal.objects.filter(id=animal.id).update(revision_ia_estado=Animal.REVISION_PENDIENTE)

        with mock.patch.object(ModeracionService, "revisar_y_guardar") as revisar:
            request = self.factory.post("/animales/{}/".format(animal.id), {
                "tipo": "G", "estado": "D", "nombre": "Willy", "edad": "2 meses",
                "sexo": "M", "zona": "Palermo", "datos": "SPAM: comprá acá",
                "animalimage_set-TOTAL_FORMS": "1",
                "animalimage_set-INITIAL_FORMS": "1",
                "animalimage_set-MIN_NUM_FORMS": "0",
                "animalimage_set-MAX_NUM_FORMS": "1000",
                "animalimage_set-0-id": str(animal.get_images()[0].id),
                "animalimage_set-0-animal": str(animal.id),
                "animalimage_set-0-crop_x": "", "animalimage_set-0-crop_y": "",
                "animalimage_set-0-crop_w": "", "animalimage_set-0-crop_h": "",
            })
            request.user = self.user
            request.session = SessionStore()
            from catus.views.animal import EditView
            view = EditView()
            view.request = request
            response = view.req(is_post=True, animal_id=str(animal.id))

        print("\n>>> revisar_y_guardar llamado al editar:", revisar.called)
        animal.refresh_from_db()
        print(">>> estado revision tras editar:", animal.revision_ia_estado, "| datos:", animal.datos)

    def test_cuanto_tarda_el_guardado(self):
        """Mide el tiempo total del POST cuando la API tarda 25s (el timeout)."""

        def lenta(self, descripcion, fotos):
            time.sleep(0.3)
            return '{"animales": ["gato"], "descripcion": "un gato"}'

        with mock.patch.object(ModeracionService, "_preguntar", lenta):
            inicio = time.time()
            response, request = self.guardar(total=3)
            total = time.time() - inicio

        print("\n>>> POST completo con API de 0.3s y 3 fotos: {:.2f}s".format(total))
