"""Tests de los comandos de management, que corren por cron sin nadie mirando."""
import io
import json
import shutil
import tempfile
from datetime import timedelta
from urllib.error import HTTPError
from io import StringIO
from unittest import mock

from PIL import Image

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from catus.management.commands.automatic_approve import Command as AutomaticApproveCommand
from catus.management.commands.publish import Command as PublishCommand
from catus.models import Animal
from catus.services.facebook import FacebookApiService
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo


def error_de_graph(code, message, subcode=None, user_msg=None):
    """El motivo tal como le llega al cron cuando Graph rechaza una publicación.

    Se arma con un error de verdad -pyfb pide con urlopen, así que un 400 de Graph llega
    como HTTPError con el JSON en el cuerpo- y se lo pasa por el mismo show_error que usa
    el pipeline. El test del corte por límite escribía el motivo a mano ("Error 4:
    Application request limit reached"), un texto que no manda nadie: pasaba aunque el
    detector no reconociera ni uno solo de los errores que llegan de verdad.
    """

    error = {"message": message, "type": "OAuthException", "code": code}

    if subcode is not None:
        error["error_subcode"] = subcode

    if user_msg is not None:
        #el que Facebook traduce a la locale de la app, y el que show_error prefiere
        error["error_user_msg"] = user_msg

    cuerpo = json.dumps({"error": error}).encode("utf-8")

    respuesta = HTTPError(
        "https://graph.facebook.com/v4.0/17841400000000000/media_publish",
        400, "Bad Request", {}, io.BytesIO(cuerpo),
    )

    return FacebookApiService.show_error(respuesta)


class OptimizeImagesTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def run_command(self, *args):

        salida = StringIO()
        call_command("optimize_images", *args, stdout=salida, stderr=StringIO())
        return salida.getvalue()

    def test_achica_las_fotos_de_los_animales_en_adopcion(self):

        animal = make_animal(estado="D", aprobado=True)
        imagen = make_animal_image(animal=animal, size=(3000, 2000))

        self.run_command()

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            #se achica, pero sin bajar del cuadrado que recorta Instagram
            self.assertLess(max(foto.size), 3000)
            self.assertGreaterEqual(min(foto.size), 1200)

    def test_un_max_width_mas_chico_achica_de_verdad(self):
        """El piso de 1200 se comía el flag.

        Como el piso no miraba el ancho pedido, --max-width 600 sobre una 3000x2000 daba
        1800x1200: lo mismo que sin el flag. Ahora el lado corto baja hasta lo que se pidió.
        """

        animal = make_animal(estado="D", aprobado=True)
        imagen = make_animal_image(animal=animal, size=(3000, 2000))

        self.run_command("--max-width", "600")

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertEqual(foto.size, (900, 600))

    def test_no_toca_las_fotos_que_ya_estan_bien(self):
        """Optimizaba todo sin preguntar: cada corrida reencodaba a calidad 70 y renombraba
        el archivo, así que las URLs que ya habían salido por mail quedaban rotas."""

        animal = make_animal(estado="D", aprobado=True)
        imagen = make_animal_image(animal=animal, size=(600, 400))
        nombre = imagen.image.name

        self.run_command()

        imagen.refresh_from_db()
        self.assertEqual(imagen.image.name, nombre)
        with Image.open(imagen.image.path) as foto:
            self.assertEqual(foto.size, (600, 400))

    def test_por_defecto_no_toca_los_adoptados(self):

        adoptado = make_animal(estado="A", aprobado=True)
        imagen = make_animal_image(animal=adoptado, size=(3000, 2000))

        self.run_command()

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertEqual(foto.size, (3000, 2000))

    def test_con_todos_tambien_los_adoptados(self):

        adoptado = make_animal(estado="A", aprobado=True)
        imagen = make_animal_image(animal=adoptado, size=(3000, 2000))

        self.run_command("--todos")

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertLess(max(foto.size), 3000)

    def test_sin_animales_no_rompe(self):

        salida = self.run_command()

        self.assertIn("0", salida)

    def test_informa_cuantas_proceso(self):

        animal = make_animal(estado="D", aprobado=True)
        make_animal_image(animal=animal, size=(2000, 1500))

        salida = self.run_command()

        self.assertIn("Fotos optimizadas: 1", salida)


@override_settings(ENV="TEST")
class CronDePublicacion(TestCase):
    """Base de los tests del cron `publish`: nada de esto habla con la API.

    `FacebookApiService.publish` está reemplazado en cada test, así que lo que se cuenta
    es cuántas veces el comando lo hubiera llamado. MEDIA_ROOT descartable porque las
    imágenes de Instagram son archivos de verdad.
    """

    def setUp(self):

        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):

        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def animal_listo(self, nombre="Willy", con_imagen=True, **kwargs):
        """Un animal tal como llega al cron: aprobado, en adopción y con la imagen armada."""

        kwargs.setdefault("aprobado", True)
        kwargs.setdefault("estado", "D")
        kwargs.setdefault("instagram_listo_para_publicar", True)

        animal = make_animal(nombre=nombre, **kwargs)

        imagen = make_animal_image(animal=animal, posicion=1)
        if con_imagen:
            imagen.image_for_instagram.save("insta.jpg", uploaded_photo(), save=True)

        return animal

    def cola(self):

        return list(PublishCommand().animales_de_esta_corrida())

    def correr(self):

        salida = StringIO()
        call_command("publish", stdout=salida, stderr=salida)
        return salida.getvalue()

    def publicados(self, corrida):
        """Corre el cron con `corrida` como publicación y devuelve a quiénes intentó.

        Cuántos animales se intentaron es lo que dice si la corrida se cortó: lo que se
        cuenta son los que llegaron a la API, no los que terminaron publicados.
        """

        intentados = []

        def publicar(animal, ig_text):
            intentados.append(animal.nombre)
            return corrida(animal, ig_text)

        with mock.patch.object(FacebookApiService, "publish", side_effect=publicar):
            self.correr()

        return intentados

    def publicar_ok(self, animal, ig_text):
        """Lo que deja publish() cuando Instagram acepta: el post guardado en el animal."""

        Animal.objects.filter(id=animal.id).update(
            instagram_publicado=True, instagram_post_id="post-{}".format(animal.id),
        )
        return "Publicado!"


class ColaDePublicacionTest(CronDePublicacion):
    """Quién entra a la corrida, ahora que la marca de "listo" la puede poner el sistema."""

    def test_no_publica_lo_que_la_ia_marco_para_revisar(self):
        """El cron no miraba `revision_ia_estado`.

        Mientras un humano apretaba "marcar como listo" zafaba, pero con el posteo
        automático lo que la revisión automática marcó para mirar a mano salía derecho a
        la cuenta pública del refugio.
        """

        animal = self.animal_listo(revision_ia_estado=Animal.REVISION_REVISAR)

        self.assertNotIn(animal, self.cola())

    def test_lo_que_la_ia_no_pudo_revisar_se_publica_igual(self):
        """La invariante de moderacion.py: 'E' es un fallo nuestro, no sospecha de nadie.

        Sólo 'R' retiene. Si 'E' o 'P' frenaran la publicación, quedarse sin crédito en la
        API de OpenAI dejaría al refugio sin poder publicar.
        """

        no_se_pudo = self.animal_listo(nombre="Willy", revision_ia_estado=Animal.REVISION_ERROR)
        sin_revisar = self.animal_listo(nombre="Rocky", revision_ia_estado=Animal.REVISION_PENDIENTE)
        aprobada = self.animal_listo(nombre="Luna", revision_ia_estado=Animal.REVISION_OK)

        cola = self.cola()

        for animal in (no_se_pudo, sin_revisar, aprobada):
            self.assertIn(animal, cola, "{} se quedó sin publicar".format(animal.nombre))

    def test_sin_la_imagen_de_instagram_no_entra_a_la_corrida(self):
        """Entraba igual, publish() devolvía el motivo por stdout y nadie lo leía.

        El animal se quedaba en la cola quemando una corrida atrás de otra para siempre,
        sin que quedara nada en ningún lado diciendo qué le faltaba.
        """

        animal = self.animal_listo(con_imagen=False)

        with mock.patch.object(FacebookApiService, "publish") as publish:
            salida = self.correr()

        publish.assert_not_called()

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_publicado)
        self.assertIn("makeimages", animal.instagram_error, "no dice qué le falta")
        self.assertIn("makeimages", salida)

    def test_cuando_aparecen_las_imagenes_se_borra_el_aviso(self):
        """Si no, el animal publica bien pero mientras tanto muestra que le falta algo que ya está."""

        #agendado para más tarde: así el aviso es lo único que le pasa en las dos corridas
        animal = self.animal_listo(
            con_imagen=False, instagram_programado_para=timezone.now() + timedelta(hours=1),
        )

        self.correr()

        animal.refresh_from_db()
        self.assertIn("makeimages", animal.instagram_error)

        imagen = animal.animalimage_set.first()
        imagen.image_for_instagram.save("insta.jpg", uploaded_photo(), save=True)

        self.correr()

        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_error)

    def test_no_publica_antes_de_la_hora_agendada(self):
        """La demora entre aprobar y postear es la única ventana para cancelar.

        `aprobado=True` no garantiza que un humano haya mirado: automatic_approve deja
        aprobando solos a los rescatistas con historial.
        """

        animal = self.animal_listo(instagram_programado_para=timezone.now() + timedelta(hours=1))

        self.assertNotIn(animal, self.cola())

    @override_settings(INSTAGRAM_AUTO_ACTIVO=True)
    def test_cuando_llega_la_hora_agendada_se_publica(self):

        animal = self.animal_listo(instagram_programado_para=timezone.now() - timedelta(minutes=1))

        self.assertIn(animal, self.cola())


class FlagDelPosteoAutomaticoTest(CronDePublicacion):
    """Apagar INSTAGRAM_AUTO_ACTIVO frena el pipeline automático, no al equipo.

    El flag arranca apagado a propósito, pero ninguno de los dos crones lo miraba: lo que
    ya estaba agendado salía igual, así que apagarlo no era una forma de frenar nada.
    """

    def agendado(self, **kwargs):

        kwargs.setdefault("instagram_programado_para", timezone.now() - timedelta(minutes=5))
        return self.animal_listo(**kwargs)

    def test_con_el_flag_apagado_lo_agendado_no_sale(self):
        """Es el gesto de freno más grande que hay: tiene que alcanzar para lo ya agendado."""

        self.assertEqual(self.cola(), [], "publicó lo agendado con el posteo automático apagado")

    def test_con_el_flag_apagado_no_llega_a_la_api(self):

        self.agendado()

        with mock.patch.object(FacebookApiService, "publish") as publish:
            self.correr()

        publish.assert_not_called()

    @override_settings(INSTAGRAM_AUTO_ACTIVO=True)
    def test_con_el_flag_prendido_lo_agendado_sale(self):

        animal = self.agendado()

        self.assertIn(animal, self.cola())

    def test_con_el_flag_apagado_lo_marcado_a_mano_sale_igual(self):
        """`publish` no es sólo del pipeline automático: también publica lo que el equipo
        marca a mano desde /tools/makeimages/, que es como se publicó siempre. Apagar el
        posteo automático no puede dejar al equipo sin poder publicar."""

        animal = self.animal_listo(instagram_programado_para=None)

        self.assertIn(animal, self.cola())


class CandadoDePublicacionTest(CronDePublicacion):
    """Que dos corridas del cron no dejen dos posts iguales en la cuenta."""

    def test_dos_corridas_al_mismo_tiempo_no_duplican_el_post(self):
        """publish() marca instagram_publicado recién al final, después de subir las fotos.

        Con un carrusel eso son minutos, y el cron corre cada pocos: la corrida siguiente
        veía el mismo animal con publicado=False y lo posteaba de nuevo. Acá la segunda
        corrida arranca justo adentro de la publicación de la primera, que es la ventana
        que quedaba abierta.
        """

        animal = self.animal_listo()
        intentos = []

        def publicar_lento(animal_a_publicar, ig_text):

            intentos.append(animal_a_publicar.id)

            if len(intentos) == 1:
                #el cron de nuevo, mientras esta corrida todavía está subiendo fotos
                self.correr()

            return self.publicar_ok(animal_a_publicar, ig_text)

        with mock.patch.object(FacebookApiService, "publish", side_effect=publicar_lento):
            self.correr()

        self.assertEqual(intentos, [animal.id], "publicó dos veces el mismo animal")

    def test_el_que_esta_publicando_otra_corrida_no_entra(self):
        """El reclamo escribe instagram_ultimo_intento: mientras esté fresco, es de otra."""

        animal = self.animal_listo(instagram_intentos=1, instagram_ultimo_intento=timezone.now())

        self.assertNotIn(animal, self.cola())

    def test_el_reclamo_cuenta_el_intento_antes_de_subir_nada(self):

        animal = self.animal_listo()

        with mock.patch.object(FacebookApiService, "publish", side_effect=self.publicar_ok):
            self.correr()

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_intentos, 1)
        self.assertIsNotNone(animal.instagram_ultimo_intento)


class ReintentosDePublicacionTest(CronDePublicacion):
    """Que un animal que falla no se reintente para siempre y en silencio."""

    def falla_con(self, motivo="Error 100: la imagen no se pudo bajar"):

        return mock.patch.object(FacebookApiService, "publish", return_value=motivo)

    def test_guarda_el_motivo_de_la_falla_en_el_animal(self):
        """El error se escribía por stdout, que en un cron no lo mira nadie."""

        animal = self.animal_listo()

        with self.falla_con():
            self.correr()

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_publicado)
        self.assertIn("la imagen no se pudo bajar", animal.instagram_error)

    def test_espera_cada_vez_mas_entre_intento_e_intento(self):
        """Sin backoff, el mismo animal roto se reintentaba en cada corrida del cron."""

        hace_una_hora = timezone.now() - timedelta(hours=1)

        #un intento espera media hora; tres, dos horas
        un_intento = self.animal_listo(
            nombre="Willy", instagram_intentos=1, instagram_ultimo_intento=hace_una_hora,
        )
        tres_intentos = self.animal_listo(
            nombre="Rocky", instagram_intentos=3, instagram_ultimo_intento=hace_una_hora,
        )

        cola = self.cola()

        self.assertIn(un_intento, cola, "esperó de más para reintentar")
        self.assertNotIn(tres_intentos, cola, "reintentó antes de tiempo")

    def test_despues_del_tope_se_deja_de_intentar(self):

        animal = self.animal_listo(
            instagram_intentos=PublishCommand.MAX_INTENTOS,
            instagram_ultimo_intento=timezone.now() - timedelta(days=7),
        )

        self.assertNotIn(animal, self.cola())

    def test_el_ultimo_intento_deja_dicho_que_se_rindio(self):
        """Rendirse en silencio es lo mismo que perder el animal: tiene que verse."""

        animal = self.animal_listo(
            instagram_intentos=PublishCommand.MAX_INTENTOS - 1,
            instagram_ultimo_intento=timezone.now() - timedelta(days=1),
        )

        with self.falla_con():
            self.correr()

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_intentos, PublishCommand.MAX_INTENTOS)
        self.assertIn("Se dejó de intentar", animal.instagram_error)
        self.assertNotIn(animal, self.cola())

    def test_cuando_sale_bien_se_limpia_el_error(self):
        """Si no, el animal queda para siempre mostrando el error de un intento viejo."""

        animal = self.animal_listo(
            instagram_error="Error 100: la imagen no se pudo bajar",
            instagram_intentos=1,
            instagram_ultimo_intento=timezone.now() - timedelta(hours=2),
        )

        with mock.patch.object(FacebookApiService, "publish", side_effect=self.publicar_ok):
            self.correr()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado)
        self.assertIsNone(animal.instagram_error)


class TopeDePublicacionesTest(CronDePublicacion):
    """El límite de la API: 25 publicaciones cada 24 h por cuenta."""

    def test_no_publica_mas_que_el_tope_por_corrida(self):
        """El tope era 999, o sea ninguno: con el posteo automático la cola es el día entero."""

        for numero in range(PublishCommand.MAX_POR_CORRIDA + 2):
            self.animal_listo(nombre="Willy {}".format(numero))

        self.assertEqual(len(self.publicados(self.publicar_ok)), PublishCommand.MAX_POR_CORRIDA)

    def test_no_pasa_el_limite_diario_de_instagram(self):
        """Los ya publicados en las últimas 24 h ocupan lugar; los de anteayer no."""

        for numero in range(PublishCommand.MAX_POR_DIA):
            make_animal(
                nombre="Publicado {}".format(numero),
                instagram_publicado=True,
                instagram_ultimo_intento=timezone.now() - timedelta(hours=2),
            )

        animal = self.animal_listo()

        self.assertEqual(self.cola(), [], "se pasó del límite de la cuenta")

        Animal.objects.filter(instagram_publicado=True).update(
            instagram_ultimo_intento=timezone.now() - timedelta(hours=25),
        )

        self.assertIn(animal, self.cola())

    def test_el_error_de_limite_corta_la_corrida(self):
        """Cuando Instagram corta por límite, corta para toda la cuenta.

        Seguir con los que quedan es gastar pedidos al pedo y sumarle un intento fallado a
        cada uno, que después los deja esperando el backoff.
        """

        self.animal_listo(nombre="Willy")
        segundo = self.animal_listo(nombre="Rocky")

        def se_paso_del_limite(animal, ig_text):
            return error_de_graph(4, "(#4) Application request limit reached")

        self.assertEqual(self.publicados(se_paso_del_limite), ["Willy"])

        segundo.refresh_from_db()
        self.assertEqual(segundo.instagram_intentos, 0, "le contó un intento que nunca hizo")

    def test_el_corte_lo_decide_el_codigo_y_no_la_prosa_del_mensaje(self):
        """El mismo límite, con el mensaje escrito de otra forma.

        El corte se decidía buscando "limit reached" adentro del texto, pero el texto lo
        escribe Facebook: lo traduce a la locale de la app y lo reescribe cuando quiere. Con
        el mismo error, contestado en castellano, la corrida seguía con toda la cola:
        pedidos al pedo y un intento fallado para cada animal. El código no cambia.
        """

        self.animal_listo(nombre="Willy")
        segundo = self.animal_listo(nombre="Rocky")

        def se_paso_del_limite(animal, ig_text):
            return error_de_graph(
                4,
                "Application request limit reached",
                user_msg="Alcanzaste el máximo de publicaciones permitidas. Probá más tarde.",
            )

        self.assertEqual(self.publicados(se_paso_del_limite), ["Willy"], "no reconoció el corte")

        segundo.refresh_from_db()
        self.assertEqual(segundo.instagram_intentos, 0, "le contó un intento que nunca hizo")

    def test_un_error_del_animal_no_corta_la_corrida(self):
        """La contraparte: lo que falla por este animal no puede frenar a los que siguen.

        Instagram no pudo bajar la foto de uno; los demás no tienen nada que ver.
        """

        self.animal_listo(nombre="Willy")
        self.animal_listo(nombre="Rocky")

        def no_pudo_bajar_la_imagen(animal, ig_text):
            return error_de_graph(
                100,
                "The image you are trying to publish could not be downloaded",
                subcode=2207003,
            )

        self.assertEqual(self.publicados(no_pudo_bajar_la_imagen), ["Willy", "Rocky"])


class FallaGlobalTest(CronDePublicacion):
    """Un fallo que no es del animal no le puede quemar el intento.

    Con el token vencido o sin cuenta vinculada falla todo lo que se intente publicar: los
    cinco intentos de cada animal de la cola se gastaban en dos corridas sin que nadie
    hubiera publicado nada mal, y después no había forma de rehabilitarlos desde la app.
    """

    def token_vencido(self, animal, ig_text):

        return error_de_graph(
            190, "Error validating access token: Session has expired", subcode=463,
        )

    def sin_cuenta(self, animal, ig_text):
        """Lo que devuelve FacebookApiService.publish cuando no hay FacebookAccount.

        Ni siquiera llega a Graph, así que no trae código: es el otro fallo global.
        """

        return "No hay ninguna cuenta de Instagram vinculada."

    def test_el_token_vencido_corta_la_corrida(self):

        self.animal_listo(nombre="Willy")
        self.animal_listo(nombre="Rocky")

        self.assertEqual(self.publicados(self.token_vencido), ["Willy"])

    def test_el_token_vencido_no_le_quema_el_intento_a_nadie(self):

        primero = self.animal_listo(nombre="Willy")
        segundo = self.animal_listo(nombre="Rocky")

        self.publicados(self.token_vencido)

        for animal in (primero, segundo):
            animal.refresh_from_db()
            self.assertEqual(
                animal.instagram_intentos, 0,
                "{} pagó con un intento un problema que no era suyo".format(animal.nombre),
            )

    def test_sin_cuenta_vinculada_tampoco(self):

        animal = self.animal_listo()

        self.publicados(self.sin_cuenta)

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_intentos, 0)

    def test_el_animal_vuelve_a_la_cola_de_la_corrida_siguiente(self):
        """Devolver el intento sin devolver la fecha lo deja esperando un backoff que no
        se ganó: para el cron seguiría siendo uno que "está publicando otra corrida"."""

        animal = self.animal_listo()

        self.publicados(self.token_vencido)

        self.assertIn(animal, self.cola(), "quedó esperando por un intento que no hizo")

    def test_el_motivo_queda_escrito_igual(self):
        """Devolverle el intento no puede dejarlo mudo: el token vencido se arregla en
        /tools/, y ahí se ve por lo que quedó escrito en el animal."""

        animal = self.animal_listo()

        self.publicados(self.token_vencido)

        animal.refresh_from_db()
        self.assertIn("190", animal.instagram_error)
        self.assertNotIn("Se dejó de intentar", animal.instagram_error)


class AutomaticApproveTest(TestCase):
    """El comando que le da aprobación automática a los rescatistas con historial."""

    def correr(self):

        salida = StringIO()
        call_command("automatic_approve", stdout=salida, stderr=StringIO())
        return salida.getvalue()

    def rescatista_con(self, aprobados, email="rescatista@catpuccino.test", **kwargs):

        user = make_user(email=email, **kwargs)

        for numero in range(aprobados):
            make_animal(nombre="Willy {}".format(numero), cargado_por=user, aprobado=True)

        return user

    def test_un_solo_animal_aprobado_no_alcanza(self):
        """Alcanzaba con uno, así que del segundo en adelante se aprobaban solos.

        Con el posteo automático eso es publicar en la cuenta de la organización sin que
        nadie haya mirado nunca más de una publicación de ese rescatista, y cualquiera se
        registra solo.
        """

        user = self.rescatista_con(1)

        self.correr()

        user.refresh_from_db()
        self.assertFalse(user.automatic_approve)

    def test_con_suficientes_aprobados_pasa_a_automatico(self):
        """La contraparte: el equipo usa esto, no se puede sacar."""

        user = self.rescatista_con(AutomaticApproveCommand.MINIMO_APROBADOS)

        self.correr()

        user.refresh_from_db()
        self.assertTrue(user.automatic_approve)

    def test_al_que_ya_la_tenia_y_no_llega_al_minimo_se_la_saca(self):
        """Subir el mínimo no servía de nada para los que ya estaban adentro.

        El comando sólo miraba `automatic_approve=False`, así que todo el padrón viejo
        —que la había recibido cuando alcanzaba con UN animal aprobado— se la quedaba para
        siempre. Justo los que importan: con el posteo automático, aprobado=True agenda la
        publicación en la cuenta de la organización.
        """

        user = self.rescatista_con(1)
        user.automatic_approve = True
        user.save()

        self.correr()

        user.refresh_from_db()
        self.assertFalse(user.automatic_approve, "conservó la aprobación automática con 1 animal")

    def test_al_que_la_tiene_y_sigue_llegando_no_se_le_toca(self):
        """La contraparte: revocar de más le rompe el flujo al equipo todos los días."""

        user = self.rescatista_con(AutomaticApproveCommand.MINIMO_APROBADOS)
        user.automatic_approve = True
        user.save()

        self.correr()

        user.refresh_from_db()
        self.assertTrue(user.automatic_approve)

    def test_los_que_no_estan_aprobados_no_cuentan(self):

        user = make_user()

        for numero in range(10):
            make_animal(nombre="Willy {}".format(numero), cargado_por=user, aprobado=False)

        self.correr()

        user.refresh_from_db()
        self.assertFalse(user.automatic_approve)

    def test_avisa_por_logger_y_no_por_print(self):
        """Informaba con print(): en un cron no lo lee nadie y no queda registro."""

        self.rescatista_con(AutomaticApproveCommand.MINIMO_APROBADOS)

        with self.assertLogs("catus.management.commands.automatic_approve", level="INFO") as registro:
            self.correr()

        self.assertTrue(
            any("aprobados" in linea for linea in registro.output),
            "no dejó registro de por qué pasó a aprobación automática",
        )
