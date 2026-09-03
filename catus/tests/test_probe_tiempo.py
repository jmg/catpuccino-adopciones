import json, time
from unittest import mock
from django.test import TestCase, override_settings
from catus.models import Animal
from catus.services.moderacion import ModeracionService
from catus.tests.factories import make_user
from catus.tests.test_probe_abuso import post_animal
from catus.views.animal import EditView


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="k", ENV="TEST")
class Tiempo(TestCase):

    def test_tiempo_por_alta(self):
        user = make_user(email="a@b.test")
        resp = json.dumps({"animales": ["gato"], "descripcion": "x",
                           "texto_sospechoso": False, "inapropiado": False})
        n = 20
        with mock.patch.object(ModeracionService, "_preguntar", return_value=resp) as p:
            with mock.patch("catus.services.mail.MailService.send_new_animal_mail"):
                with mock.patch("catus.services.images.ImageService.optimize"):
                    with mock.patch("catus.services.images.ImageService.suggest_crop", return_value=None):
                        t0 = time.time()
                        for i in range(n):
                            EditView.as_view()(post_animal(user, "g%d" % i))
                        dt = time.time() - t0
        print("\n>>> %d altas en %.2fs => %.1f ms de app por alta, %d llamadas" % (n, dt, dt/n*1000, p.call_count))
        print(">>> animales en base:", Animal.objects.count())

    def test_tamano_del_payload_a_openai(self):
        from catus.tests.factories import make_animal, make_animal_image
        animal = make_animal(nombre="Willy", tipo="G")
        for i in range(5):
            make_animal_image(animal=animal, size=(1200, 900))
        s = ModeracionService()
        fotos = s._leer_fotos(animal)
        print("\n>>> fotos enviadas:", len(fotos), "de", animal.get_images().count())
        print(">>> bytes del payload base64:", sum(len(f) for f in fotos))
