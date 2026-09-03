"""Tests de la publicación en Instagram.

Nada acá habla con la API de verdad: el stub de pyfb falla si alguien lo intenta.
Lo que se prueba son las decisiones previas, que son las que dejaron posts de más
o de menos en la cuenta real.
"""
from unittest import mock

from django.test import TestCase, override_settings

from catus.services.facebook import FacebookApiService, MediaError
from catus.tests.factories import make_animal, make_animal_image, make_user


class PublishTest(TestCase):

    def setUp(self):
        self.animal = make_animal(nombre="Willy", cargado_por=make_user())

    @override_settings(ENV="LOCAL")
    def test_en_local_no_publica(self):
        """Reemplazaba la foto por una URL fija pero publicaba en la cuenta real."""

        make_animal_image(animal=self.animal)

        respuesta = FacebookApiService.publish(self.animal, "texto")

        self.animal.refresh_from_db()
        self.assertFalse(self.animal.instagram_publicado)
        self.assertIn("LOCAL", respuesta)

    @override_settings(ENV="TEST")
    def test_sin_cuenta_vinculada_avisa(self):

        make_animal_image(animal=self.animal)

        respuesta = FacebookApiService.publish(self.animal, "texto")

        self.assertIn("cuenta", respuesta.lower())
        self.animal.refresh_from_db()
        self.assertFalse(self.animal.instagram_publicado)

    @override_settings(ENV="TEST")
    def test_sin_fotos_avisa_en_vez_de_romper(self):

        from catus.models import FacebookAccount

        FacebookAccount.objects.create(facebook_token="x", business_account_id="1")

        respuesta = FacebookApiService.publish(self.animal, "texto")

        self.assertIn("fotos", respuesta.lower())


class WaitForMediaReadyTest(TestCase):
    """Espera a que Instagram termine de procesar la foto antes de publicarla."""

    def service_que_responde(self, *respuestas):

        service = mock.Mock()
        service.facebook.request.side_effect = list(respuestas)
        return service

    def test_sale_cuando_termina(self):

        service = self.service_que_responde({"status_code": "FINISHED"})

        self.assertTrue(FacebookApiService.wait_for_media_ready(service, "1", wait_seconds=0))

    def test_espera_mientras_procesa(self):

        service = self.service_que_responde(
            {"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"},
        )

        self.assertTrue(FacebookApiService.wait_for_media_ready(service, "1", wait_seconds=0))
        self.assertEqual(service.facebook.request.call_count, 2)

    def test_no_reintenta_cuando_instagram_ya_dijo_que_fallo(self):
        """Se reintentaba 30 veces un contenedor con estado ERROR: un minuto por foto."""

        service = self.service_que_responde(*[{"status_code": "ERROR"}] * 30)

        with self.assertRaises(MediaError):
            FacebookApiService.wait_for_media_ready(service, "1", wait_seconds=0)

        self.assertEqual(service.facebook.request.call_count, 1, "siguió reintentando")


class GetMediaUrlTest(TestCase):
    """Se pide después de publicar, cuando el post ya está arriba."""

    def test_devuelve_id_y_permalink(self):

        service = mock.Mock()
        service.facebook.request.return_value = {"id": "99", "permalink": "https://instagr.am/p/99"}

        datos = FacebookApiService.get_media_url(service, {"id": "99"})

        self.assertEqual(datos, {"id": "99", "url": "https://instagr.am/p/99"})

    def test_si_falla_el_permalink_igual_devuelve_el_post(self):
        """El post ya está publicado: si esto propagaba, el cron lo publicaba de nuevo."""

        service = mock.Mock()
        service.facebook.request.side_effect = Exception("error transitorio de Graph")

        datos = FacebookApiService.get_media_url(service, {"id": "99"})

        self.assertEqual(datos["id"], "99")
        self.assertEqual(datos["url"], "")

    def test_si_la_respuesta_viene_incompleta_no_rompe(self):

        service = mock.Mock()
        service.facebook.request.return_value = {}

        datos = FacebookApiService.get_media_url(service, {"id": "99"})

        self.assertEqual(datos["id"], "99")
