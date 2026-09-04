"""Tests de la publicación en Instagram.

Nada acá habla con la API de verdad: el stub de pyfb falla si alguien lo intenta.
Lo que se prueba son las decisiones previas, que son las que dejaron posts de más
o de menos en la cuenta real.
"""
import io
import json
import shutil
import tempfile
from contextlib import redirect_stdout
from datetime import timedelta
from email.message import Message
from unittest import mock
from urllib.error import HTTPError

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from catus.management.commands.publish import Command as PublishCommand
from catus.models import Animal
from catus.services.facebook import FacebookApiService, MediaError
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo


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

    def test_no_devuelve_true_sin_que_instagram_lo_confirme(self):
        """En el último intento, con status_code None, dormía un segundo y devolvía True.

        O sea que publicaba a ciegas un contenedor que Instagram todavía no había
        terminado de procesar, y el error aparecía recién en media_publish (o no aparecía
        y salía un post roto).
        """

        service = self.service_que_responde(*[{}] * 30)

        with self.assertRaises(Exception) as capturado:
            FacebookApiService.wait_for_media_ready(service, "17999", wait_seconds=0)

        mensaje = str(capturado.exception)
        self.assertIn("17999", mensaje, "no dice de qué contenedor habla")
        self.assertIn("publicó", mensaje, "no dice que no se publicó")

    def test_el_que_se_queda_procesando_tampoco_se_publica(self):

        service = self.service_que_responde(*[{"status_code": "IN_PROGRESS"}] * 30)

        with self.assertRaises(Exception):
            FacebookApiService.wait_for_media_ready(service, "1", wait_seconds=0)

    def test_pide_los_dos_campos_para_saber_el_motivo(self):
        """Pedía fields=status_code y en el ERROR leía response["status"], que nunca venía.

        El motivo de Instagram se perdía siempre y el error quedaba en "Unknown error".
        """

        service = self.service_que_responde({
            "status_code": "ERROR", "status": "Error: The media could not be fetched",
        })

        with self.assertRaises(MediaError) as capturado:
            FacebookApiService.wait_for_media_ready(service, "1", wait_seconds=0)

        url = service.facebook.request.call_args[0][0]
        self.assertIn("status_code", url)
        self.assertIn(",status", url, "sin pedir status el motivo no viene")
        self.assertIn("could not be fetched", str(capturado.exception))

    def test_el_peor_caso_lo_aguanta_un_cron(self):
        """Eran 30 intentos de 2 s: hasta un minuto por foto.

        Un carrusel de 10 fotos son 11 contenedores (uno por foto más el del carrusel),
        así que la publicación de un solo animal se iba a más de diez minutos.
        """

        dormidas = []
        service = mock.Mock()
        service.facebook.request.return_value = {"status_code": "IN_PROGRESS"}

        with mock.patch("catus.services.facebook.time.sleep", side_effect=dormidas.append):
            with self.assertRaises(Exception):
                FacebookApiService.wait_for_media_ready(service, "1")

        espera = sum(dormidas)
        self.assertLessEqual(espera, 25, "un solo contenedor ya tarda demasiado")
        self.assertLessEqual(espera * 11, 4 * 60, "un carrusel de 10 fotos no entra en un cron")


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


@override_settings(ENV="TEST")
class PublishImagenDeInstagramTest(TestCase):
    """Qué fotos se suben: sólo las que tienen la imagen de Instagram ya generada.

    Lo que se postea no es `image` sino `image_for_instagram`, que se genera aparte en
    /tools/makeimages/ y es null hasta entonces. Una foto agregada después de esa pasada
    no la tiene y el `.url` reventaba recién adentro de publish_one_image /
    publish_multiple_images, o sea después de haber subido contenedores a Instagram: el
    animal nunca se publicaba y el cron volvía a quemar contenedores en cada corrida.
    """

    def setUp(self):
        from catus.models import FacebookAccount

        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.animal = make_animal(nombre="Willy", cargado_por=make_user())
        FacebookAccount.objects.create(facebook_token="x", business_account_id="1")

        #el borde: pyfb es lo único que habla con Graph, así que se reemplaza entero y
        #queda anotado cada pedido que la publicación hubiera mandado
        self.pedidos = []
        self.patcher = mock.patch("catus.services.facebook.Pyfb")
        Pyfb = self.patcher.start()
        Pyfb.return_value.request.side_effect = self.responder

    def tearDown(self):
        self.patcher.stop()
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def responder(self, url, **data):
        """Contesta como Graph: contenedor, estado del contenedor, post y permalink."""

        self.pedidos.append((url, data))

        if "fields=status_code" in url:
            return {"status_code": "FINISHED"}
        if "fields=permalink" in url:
            return {"id": "post-1", "permalink": "https://instagr.am/p/post-1"}
        if "/media_publish" in url:
            return {"id": "post-1"}
        return {"id": "contenedor-{}".format(len(self.pedidos))}

    def foto(self, posicion, con_imagen_de_instagram):

        imagen = make_animal_image(animal=self.animal, posicion=posicion)
        if con_imagen_de_instagram:
            imagen.image_for_instagram.save("insta.jpg", uploaded_photo(), save=True)
        return imagen

    def subidas(self):
        """Los pedidos que crean contenedores de imagen (los que cuestan)."""

        return [data for url, data in self.pedidos if "image_url" in data]

    def carruseles(self):

        return [data for url, data in self.pedidos if data.get("media_type") == "CAROUSEL"]

    def test_fotos_sin_imagen_de_instagram_no_llegan_a_la_api(self):
        """El rescatista agregó fotos después de /tools/makeimages/: no hay qué subir.

        Sin el filtro se subían igual y el ValueError de image_for_instagram saltaba con
        contenedores ya creados en Instagram, sin publicar nada y sin decir qué faltaba.
        """

        self.foto(posicion=1, con_imagen_de_instagram=False)
        self.foto(posicion=2, con_imagen_de_instagram=False)

        respuesta = FacebookApiService.publish(self.animal, "texto")

        self.assertIn("Willy", respuesta)
        self.assertIn("makeimages", respuesta, "no dice qué le falta al animal")
        self.assertEqual(self.pedidos, [], "habló con Instagram igual")

        self.animal.refresh_from_db()
        self.assertFalse(self.animal.instagram_publicado)

    def test_con_las_imagenes_generadas_publica_normalmente(self):
        """La contraparte: filtrar de más dejaría de publicar animales que sí están listos."""

        self.foto(posicion=1, con_imagen_de_instagram=True)
        self.foto(posicion=2, con_imagen_de_instagram=True)

        respuesta = FacebookApiService.publish(self.animal, "texto")

        self.assertEqual(respuesta, "Publicado!")
        self.assertEqual(len(self.subidas()), 2)
        self.assertEqual(len(self.carruseles()), 1, "dos fotos van en carrusel")

        self.animal.refresh_from_db()
        self.assertTrue(self.animal.instagram_publicado)
        self.assertEqual(self.animal.instagram_post_id, "post-1")

    def test_una_sola_foto_generada_se_publica_como_foto_unica(self):
        """El filtro también decide entre foto única y carrusel.

        De tres fotos, dos agregadas después de generar las imágenes, lo publicable es
        una sola: contando las tres se armaba un carrusel que reventaba en la segunda.
        """

        self.foto(posicion=1, con_imagen_de_instagram=True)
        self.foto(posicion=2, con_imagen_de_instagram=False)
        self.foto(posicion=3, con_imagen_de_instagram=False)

        respuesta = FacebookApiService.publish(self.animal, "texto")

        self.assertEqual(respuesta, "Publicado!")
        self.assertEqual(len(self.subidas()), 1, "subió fotos sin imagen de Instagram")
        self.assertEqual(self.carruseles(), [], "armó un carrusel con una sola foto")

        self.animal.refresh_from_db()
        self.assertTrue(self.animal.instagram_publicado)


def error_de_graph(cuerpo, codigo_http=400):
    """Un 400 de Graph tal como llega: pyfb pide con urlopen, que levanta HTTPError."""

    headers = Message()
    headers["Content-Type"] = "application/json"
    headers["x-fb-trace-id"] = "AbCdEfGhIjK"

    if isinstance(cuerpo, str):
        cuerpo = cuerpo.encode("utf-8")

    return HTTPError(
        "https://graph.facebook.com/v5.0/17841400000000000/media",
        codigo_http,
        "Bad Request",
        headers,
        io.BytesIO(cuerpo),
    )


TOKEN_VENCIDO = json.dumps({"error": {
    "message": "Error validating access token: Session has expired",
    "type": "OAuthException",
    "code": 190,
    "error_subcode": 463,
}})

TOPE_DIARIO = json.dumps({"error": {
    "message": "The user is above the limit of 25 posts in 24 hours",
    "type": "OAuthException",
    "code": 9,
}})


class ShowErrorTest(TestCase):
    """El motivo por el que Instagram rechazó el posteo.

    Es lo único que ve el equipo: publish() devuelve esto como texto y termina en el log
    del cron o en la pantalla de /tools/publish/. Devolvía la lista de headers HTTP, así
    que el token vencido, el tope diario de posteos y la cuenta mal vinculada se veían los
    tres exactamente igual y no había con qué distinguirlos.
    """

    def test_devuelve_el_motivo_que_manda_graph(self):

        mensaje = FacebookApiService.show_error(error_de_graph(TOKEN_VENCIDO))

        self.assertIsInstance(mensaje, str, "devolvía e.info().items(), o sea los headers")
        self.assertIn("190", mensaje, "no dice el código de Graph")
        self.assertIn("Session has expired", mensaje, "no dice el motivo")

    def test_no_devuelve_los_headers_http(self):

        mensaje = FacebookApiService.show_error(error_de_graph(TOKEN_VENCIDO))

        self.assertNotIn("x-fb-trace-id", mensaje)
        self.assertNotIn("Content-Type", mensaje)

    def test_el_token_vencido_y_el_tope_diario_no_se_ven_igual(self):
        """Son dos problemas distintos: uno lo arregla refresh_token, el otro esperar."""

        vencido = FacebookApiService.show_error(error_de_graph(TOKEN_VENCIDO))
        tope = FacebookApiService.show_error(error_de_graph(TOPE_DIARIO))

        self.assertNotEqual(vencido, tope)
        self.assertIn("25 posts", tope)

    def test_el_subcodigo_tambien_sale(self):
        """190/463 es el token vencido; 190 solo puede ser que lo revocaron a mano."""

        mensaje = FacebookApiService.show_error(error_de_graph(TOKEN_VENCIDO))

        self.assertIn("463", mensaje)

    def test_un_cuerpo_vacio_no_rompe(self):
        """Esto corre en el camino de error: si revienta acá se pierde el error de verdad."""

        mensaje = FacebookApiService.show_error(error_de_graph(b""))

        self.assertIsInstance(mensaje, str)
        self.assertIn("400", mensaje)

    def test_un_cuerpo_que_no_es_json_no_rompe(self):
        """Un 502 del proxy contesta HTML, no el JSON de Graph."""

        mensaje = FacebookApiService.show_error(error_de_graph(b"<html>502 Bad Gateway</html>", 502))

        self.assertIsInstance(mensaje, str)

    def test_leerlo_dos_veces_no_rompe(self):
        """El cuerpo de un HTTPError se lee UNA sola vez: la segunda viene vacío."""

        error = error_de_graph(TOKEN_VENCIDO)

        primero = FacebookApiService.show_error(error)
        segundo = FacebookApiService.show_error(error)

        self.assertIn("Session has expired", primero)
        self.assertIsInstance(segundo, str)

    def test_un_error_nuestro_sigue_saliendo_como_texto(self):
        """No todo lo que llega acá viene de Graph."""

        mensaje = FacebookApiService.show_error(Exception("se cortó la base al guardar"))

        self.assertEqual(mensaje, "se cortó la base al guardar")


@override_settings(ENV="TEST")
class PublicacionConGraphFalso(TestCase):
    """Base para lo que se mira mirando los pedidos que salieron a Instagram.

    Mismo borde que el resto: pyfb es lo único que llega a Graph y está reemplazado
    entero, así que nada de esto habla con la API.
    """

    def setUp(self):
        from catus.models import FacebookAccount

        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        FacebookAccount.objects.create(facebook_token="x", business_account_id="1")
        self.usuario = make_user()

        self.pedidos = []
        self.falla_si = None
        self.patcher = mock.patch("catus.services.facebook.Pyfb")
        Pyfb = self.patcher.start()
        Pyfb.return_value.request.side_effect = self.responder

    def tearDown(self):

        self.patcher.stop()
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def responder(self, url, **data):

        self.pedidos.append((url, data))

        if self.falla_si is not None and self.falla_si(url, data):
            raise Exception("Graph contestó que no")

        if "fields=status_code" in url:
            return {"status_code": "FINISHED"}
        if "fields=permalink" in url:
            return {"id": "post-1", "permalink": "https://instagr.am/p/post-1"}
        if "/media_publish" in url:
            return {"id": "post-1"}
        return {"id": "contenedor-{}".format(len(self.pedidos))}

    def animal_con_fotos(self, cantidad, **kwargs):

        kwargs.setdefault("instagram_listo_para_publicar", True)
        animal = make_animal(nombre="Willy", cargado_por=self.usuario, **kwargs)

        for posicion in range(1, cantidad + 1):
            imagen = make_animal_image(animal=animal, posicion=posicion)
            imagen.image_for_instagram.save("insta.jpg", uploaded_photo(), save=True)

        return animal

    def subidas(self):
        """Los pedidos que crean contenedores de imagen."""

        return [data for url, data in self.pedidos if "image_url" in data]

    def carruseles(self):

        return [data for url, data in self.pedidos if data.get("media_type") == "CAROUSEL"]


class PublishApagaLaMarcaTest(PublicacionConGraphFalso):
    """Qué queda escrito en el animal cuando el post sale."""

    def test_al_publicar_se_apaga_listo_para_publicar(self):
        """Quedaba (listo=True, publicado=True) para siempre: dos marcas que se pisan."""

        animal = self.animal_con_fotos(1)

        FacebookApiService.publish(animal, "texto")

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado)
        self.assertFalse(animal.instagram_listo_para_publicar, "la marca quedó prendida")

    def test_destildar_publicado_en_el_admin_no_lo_publica_de_nuevo(self):
        """En el admin los cuatro checks son editables y ese es el gesto obvio para rehacer.

        Con la marca de listo prendida, la corrida siguiente del cron publicaba el animal
        DE NUEVO y pisaba instagram_post_id: el post viejo quedaba huérfano en la cuenta y
        sin forma de recibir después el comentario de adoptado, así que seguía diciendo
        "en adopción" para siempre.
        """

        animal = self.animal_con_fotos(1)

        FacebookApiService.publish(animal, "texto")

        #lo que hace el admin con list_editable: destilda "publicado" y guarda
        animal.refresh_from_db()
        animal.instagram_publicado = False
        animal.save()

        self.assertNotIn(
            animal, list(PublishCommand().animales_a_publicar()),
            "el cron lo vuelve a publicar y pisa el post que ya estaba arriba",
        )

    def test_el_que_no_se_publico_conserva_la_marca(self):
        """La contraparte: apagarla en un fallo lo sacaría de la cola sin haber salido."""

        animal = self.animal_con_fotos(1)
        self.falla_si = lambda url, data: "/media_publish" in url

        FacebookApiService.publish(animal, "texto")

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_publicado)
        self.assertTrue(animal.instagram_listo_para_publicar, "lo sacó de la cola sin publicarlo")
        self.assertIn(animal, list(PublishCommand().animales_a_publicar()))

    def test_al_publicar_se_limpia_la_agenda(self):
        """La agenda del posteo automático quedaba puesta y vencida para siempre.

        La escribe la aprobación y nadie la borraba nunca, así que el animal publicado
        seguía figurando como "le toca al cron" para todo lo que mira esa fecha.
        """

        animal = self.animal_con_fotos(
            1, instagram_programado_para=timezone.now() - timedelta(minutes=1),
        )

        FacebookApiService.publish(animal, "texto")

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado)
        self.assertIsNone(animal.instagram_programado_para, "la agenda vencida quedó puesta")

    @override_settings(INSTAGRAM_AUTO_ACTIVO=True)
    def test_destildar_publicado_no_lo_devuelve_al_pipeline_automatico(self):
        """El post duplicado volviendo por la puerta de al lado.

        Destildar "publicado" en el admin es el gesto obvio para rehacer un post. Con la
        agenda vencida todavía puesta, el animal volvía a caer en la cola de
        `preparar_publicaciones`, que le prendía la marca de listo de nuevo, y `publish`
        lo posteaba por segunda vez pisando instagram_post_id: el post viejo quedaba
        huérfano en la cuenta, sin forma de recibir después el comentario de adoptado.
        """

        animal = self.animal_con_fotos(
            1, instagram_programado_para=timezone.now() - timedelta(minutes=1),
        )

        FacebookApiService.publish(animal, "texto")

        #lo que hace el admin con list_editable: destilda "publicado" y guarda
        animal.refresh_from_db()
        animal.instagram_publicado = False
        animal.save()

        salida = io.StringIO()
        call_command("preparar_publicaciones", stdout=salida, stderr=salida)
        call_command("publish", stdout=salida, stderr=salida)

        animal.refresh_from_db()
        self.assertFalse(
            animal.instagram_listo_para_publicar,
            "el cron lo volvió a marcar como listo por la agenda vencida",
        )
        self.assertIsNone(animal.instagram_programado_para)
        self.assertEqual(
            len([url for url, data in self.pedidos if "/media_publish" in url]), 1,
            "salió un segundo post del mismo animal",
        )


class CarruselTest(PublicacionConGraphFalso):
    """Cómo se arma el carrusel: Instagram acepta entre 2 y 10 items."""

    def test_los_hijos_van_marcados_como_items_del_carrusel(self):
        """Sin is_carousel_item el contenedor no es un hijo sino una foto suelta."""

        animal = self.animal_con_fotos(3)

        FacebookApiService.publish(animal, "texto")

        hijos = self.subidas()
        self.assertEqual(len(hijos), 3)

        for hijo in hijos:
            self.assertEqual(hijo.get("is_carousel_item"), "true")

        self.assertNotIn("is_carousel_item", self.carruseles()[0], "el carrusel no es hijo de nadie")

    def test_la_foto_unica_no_va_marcada_como_hija(self):

        animal = self.animal_con_fotos(1)

        FacebookApiService.publish(animal, "texto")

        self.assertEqual(self.carruseles(), [])
        self.assertNotIn("is_carousel_item", self.subidas()[0])

    def test_avisa_cuando_deja_fotos_afuera(self):
        """El truncado estaba escondido en un images[0:10] y contestaba "Publicado!" igual.

        Con 11 fotos, la 11 desaparecía del post sin que apareciera en ningún lado: ni en
        la pantalla de /tools/publish/ ni en el log del cron.
        """

        animal = self.animal_con_fotos(11)

        with self.assertLogs("catus.services.facebook", level="WARNING") as registrado:
            respuesta = FacebookApiService.publish(animal, "texto")

        self.assertEqual(len(self.subidas()), 10, "subió más de las que acepta Instagram")

        self.assertNotEqual(respuesta, "Publicado!", "no avisó que dejó una foto afuera")
        self.assertIn("11", respuesta)
        self.assertIn("10", respuesta)

        self.assertTrue(
            any("11" in linea for linea in registrado.output),
            "el truncado no quedó en el log",
        )

    def test_con_diez_o_menos_no_avisa_nada(self):
        """La contraparte: el camino feliz no tiene que cambiar de texto."""

        animal = self.animal_con_fotos(2)

        self.assertEqual(FacebookApiService.publish(animal, "texto"), "Publicado!")


class LogsTest(PublicacionConGraphFalso):
    """Que una corrida del cron se pueda reconstruir después.

    Todo esto se enteraba de las cosas con print(): la salida se la quedaba el cron y de
    una corrida sólo se sabía lo que crasheaba y llegaba a Sentry.
    """

    def test_el_fallo_de_la_api_queda_en_el_log(self):

        animal = self.animal_con_fotos(1)
        self.falla_si = lambda url, data: "/media_publish" in url

        with self.assertLogs("catus.services.facebook", level="WARNING") as registrado:
            FacebookApiService.publish(animal, "texto")

        self.assertIn("Willy", "\n".join(registrado.output), "no dice cuál animal falló")

    def test_el_fallo_esperado_de_la_api_no_va_como_error(self):
        """Los eventos ERROR de Sentry se llevan puesta la cookie de sesión."""

        animal = self.animal_con_fotos(1)
        self.falla_si = lambda url, data: "/media_publish" in url

        with self.assertLogs("catus.services.facebook", level="WARNING") as registrado:
            FacebookApiService.publish(animal, "texto")

        for registro in registrado.records:
            self.assertEqual(registro.levelname, "WARNING")
            self.assertIsNone(registro.exc_info, "se lleva el stacktrace y la cookie a Sentry")

    def test_no_escribe_en_stdout(self):
        """print() en un cron es salida que no se guarda en ningún lado."""

        animal = self.animal_con_fotos(2)

        salida = io.StringIO()
        with redirect_stdout(salida):
            FacebookApiService.publish(animal, "texto")
            FacebookApiService.get_post_for([], animal)

        self.assertEqual(salida.getvalue(), "")


class GetPostForTest(TestCase):
    """A qué post de la cuenta corresponde cada animal (lo usa el cron update_post_id)."""

    def post(self, id, nombre):

        return {
            "id": id,
            "caption": "🐱 ¡{} en Adopción Responsable! 🐱\n\nSexo: Hembra".format(nombre),
            "permalink": "https://instagr.am/p/{}".format(id),
        }

    def test_no_pisa_el_post_que_el_animal_ya_tenia(self):
        """Asignaba sin mirar si el animal ya tenía instagram_post_id.

        Y el animal que entra a este cron es justamente el que publicó bien pero se quedó
        sin permalink: su post_id ya era el correcto.
        """

        animal = make_animal(nombre="Luna", instagram_publicado=True, instagram_post_id="post-nuevo")

        FacebookApiService.get_post_for([self.post("post-viejo", "Luna")], animal)

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_post_id, "post-nuevo")
        self.assertFalse(animal.instagram_media_url, "le puso el permalink de la otra Luna")

    def test_le_completa_el_permalink_al_post_que_ya_tenia(self):

        animal = make_animal(nombre="Luna", instagram_publicado=True, instagram_post_id="post-nuevo")

        FacebookApiService.get_post_for(
            [self.post("post-viejo", "Luna"), self.post("post-nuevo", "Luna")], animal,
        )

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_post_id, "post-nuevo")
        self.assertEqual(animal.instagram_media_url, "https://instagr.am/p/post-nuevo")

    def test_corta_en_el_primer_post_que_matchea(self):
        """Recorría los 50 posts sin cortar, así que ganaba el último: el más viejo.

        Graph devuelve la media de la cuenta del más nuevo al más viejo.
        """

        animal = make_animal(nombre="Luna", instagram_publicado=True)

        FacebookApiService.get_post_for(
            [self.post("post-nuevo", "Luna"), self.post("post-viejo", "Luna")], animal,
        )

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_post_id, "post-nuevo")

    def test_el_nombre_solo_no_alcanza_para_matchear(self):
        """"¡Bella Luna en Adopción Responsable!" contiene "luna en adopción responsable"."""

        animal = make_animal(nombre="Luna", instagram_publicado=True)

        FacebookApiService.get_post_for(
            [self.post("post-bella", "Bella Luna"), self.post("post-luna", "Luna")], animal,
        )

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_post_id, "post-luna")

    def test_si_no_encuentra_nada_no_le_inventa_un_post(self):

        animal = make_animal(nombre="Luna", instagram_publicado=True)

        FacebookApiService.get_post_for([self.post("post-rocky", "Rocky")], animal)

        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_post_id)

    def test_un_post_sin_caption_no_lo_rompe(self):
        """post.get("caption", "") devuelve None si la clave está y vale null."""

        animal = make_animal(nombre="Luna", instagram_publicado=True)

        posts = [
            {"id": "post-sin-texto", "caption": None, "permalink": "https://instagr.am/p/x"},
            self.post("post-luna", "Luna"),
        ]

        FacebookApiService.get_post_for(posts, animal)

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_post_id, "post-luna")


class ReclamoAntesDeTocarGraphTest(PublicacionConGraphFalso):
    """El candado contra el post duplicado, adentro de publish().

    Vivía en el cron (`publish.py::reclamar`), que se defiende de otra corrida del cron y
    de nada más. El botón "Publicar" de /tools/publish/ llama derecho a publish(), así que
    apretarlo mientras una corrida estaba subiendo las fotos del mismo animal —un carrusel
    son minutos— dejaba dos posts iguales en la cuenta de la organización, y el segundo
    pisaba instagram_post_id: el primero quedaba huérfano, sin forma de recibir después el
    comentario de adoptado. publish() es el embudo por el que pasan los dos caminos.
    """

    def setUp(self):
        super().setUp()

        self.mientras_sube = None
        self.respuesta_del_boton = None

    def responder(self, url, **data):

        #el hook corre en el medio de la subida de las fotos, que es donde entra el otro
        if self.mientras_sube is not None and "image_url" in data:
            hook, self.mientras_sube = self.mientras_sube, None
            hook()

        return super().responder(url, **data)

    def publicaciones(self):
        """Los media_publish: uno por post que quedó en la cuenta."""

        return [url for url, data in self.pedidos if "/media_publish" in url]

    def correr_el_cron(self):

        salida = io.StringIO()
        call_command("publish", stdout=salida, stderr=salida)

        return salida.getvalue()

    def test_el_boton_de_tools_no_publica_lo_que_el_cron_esta_subiendo(self):

        animal = self.animal_con_fotos(2)

        def apretar_el_boton():
            #la vista levanta su propia copia del animal, como cualquier request
            self.respuesta_del_boton = FacebookApiService.publish(
                Animal.objects.get(id=animal.id), "texto",
            )

        self.mientras_sube = apretar_el_boton

        self.assertEqual(FacebookApiService.publish(animal, "texto"), "Publicado!")

        self.assertEqual(len(self.publicaciones()), 1, "salieron dos posts del mismo animal")
        self.assertIn(
            "publicando", (self.respuesta_del_boton or "").lower(),
            "el botón no avisó que ya lo estaba publicando otro",
        )

    def test_apretar_dos_veces_el_boton_no_duplica_el_post(self):
        """La pantalla tarda lo que tarda Instagram y el segundo click es gratis."""

        animal = self.animal_con_fotos(1)

        primera = FacebookApiService.publish(animal, "texto")
        segunda = FacebookApiService.publish(Animal.objects.get(id=animal.id), "texto")

        self.assertEqual(primera, "Publicado!")
        self.assertNotEqual(segunda, "Publicado!", "publicó de nuevo un animal ya publicado")
        self.assertEqual(len(self.publicaciones()), 1, "salieron dos posts del mismo animal")

    def test_el_cron_sigue_publicando(self):
        """La contraparte: un candado que también frena al cron no deja publicar nada.

        El cron reclama al animal antes de llamar a publish(), así que el reclamo de
        publish() tiene que dejarlo pasar igual.
        """

        animal = self.animal_con_fotos(1)

        self.correr_el_cron()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado, "el cron no pudo publicar")
        self.assertEqual(len(self.publicaciones()), 1)

    def test_el_reclamo_no_le_suma_intentos_al_cron(self):
        """Los dos reclamos no se pisan: el de publish() no toca los contadores del cron.

        instagram_intentos es lo que arma el backoff y el corte a los 5 intentos: contar
        dos por corrida le comería la mitad de los reintentos a cada animal.
        """

        animal = self.animal_con_fotos(1)

        self.correr_el_cron()

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_intentos, 1, "la corrida contó más de un intento")

    def test_si_falla_se_suelta_el_reclamo(self):
        """Marcarlo publicado y dejarlo así lo sacaría de la cola sin haber salido.

        El animal tiene que poder volver a intentarse, que es lo que hace el cron en la
        corrida siguiente.
        """

        animal = self.animal_con_fotos(1)
        self.falla_si = lambda url, data: "/media_publish" in url

        FacebookApiService.publish(animal, "texto")

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_publicado, "quedó marcado como publicado sin haber salido")

        self.falla_si = None
        self.assertEqual(FacebookApiService.publish(animal, "texto"), "Publicado!")
