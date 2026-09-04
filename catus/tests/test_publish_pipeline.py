"""Tests de punta a punta de la máquina de estados del posteo en Instagram.

Hoy publicar un animal en Instagram son cinco pasos y tres son a mano: aprobarlo,
generar las imágenes en /tools/makeimages/ y apretar "Marcar como listo". Recién ahí el
cron `publish` lo levanta, y más tarde `update_status_in_ig` comenta que se adoptó.

Automatizar los pasos a mano cambia *quién* prende `instagram_listo_para_publicar`; no
debería cambiar ninguna de las reglas de acá abajo, que son las que hoy evitan que salga
un post de más o de menos en la cuenta real de la organización. Quedan escritas antes de
tocar nada: el día que la marca se ponga sola, lo que se rompa se ve acá.

Nada de esto habla con la API. `catus.services.facebook.Pyfb` es lo único que llega a
Graph y está reemplazado entero, así que cada pedido que la publicación hubiera mandado
queda anotado en `self.graph.pedidos` y se puede contar.
"""
import shutil
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from catus.management.commands.publish import Command as PublishCommand
from catus.management.commands.update_status_in_ig import Command as ComentarioCommand
from catus.models import Animal, FacebookAccount
from catus.services.facebook import FacebookApiService
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo


ESTADOS = ("D", "R", "A", "E")


class AnimalesAPublicarTest(TestCase):
    """Quién entra al cron `publish`, para las cuatro banderas que lo deciden.

    El filtro empezó mirando sólo `instagram_listo_para_publicar` y `instagram_publicado`,
    y con eso publicaba animales que nunca se habían aprobado y animales que se habían
    adoptado entre que alguien los marcó y corrió el cron.
    """

    def tomados(self):

        return list(PublishCommand().animales_a_publicar())

    def test_tabla_de_quien_entra(self):
        """Entra el aprobado, en adopción o reservado, marcado como listo y sin publicar."""

        for aprobado in (True, False):
            for estado in ESTADOS:
                for listo in (True, False):
                    for publicado in (True, False):

                        entra = aprobado and estado in ("D", "R") and listo and not publicado

                        with self.subTest(aprobado=aprobado, estado=estado, listo=listo, publicado=publicado):

                            animal = make_animal(
                                nombre="Willy",
                                aprobado=aprobado,
                                estado=estado,
                                instagram_listo_para_publicar=listo,
                                instagram_publicado=publicado,
                            )

                            self.assertEqual(animal in self.tomados(), entra)

                            animal.delete()

    def test_el_adoptado_entre_que_se_marco_y_corrio_el_cron_no_se_publica(self):
        """Se marcaba listo un lunes, se adoptaba el martes y el cron lo publicaba igual.

        Salía en Instagram un animal que ya tenía familia, con el formulario de
        pre-adopción abierto: llegaban postulaciones para un gato que no estaba.
        """

        adoptado = make_animal(
            nombre="Willy", aprobado=True, estado="A", instagram_listo_para_publicar=True,
        )

        self.assertNotIn(adoptado, self.tomados())

    def test_el_que_nunca_se_aprobo_no_se_publica(self):
        """El equipo aprueba antes de que algo salga a la calle; el cron se lo salteaba.

        Cualquiera se registra solo, así que una publicación sin aprobar puede ser
        cualquier cosa, y el cron la posteaba en la cuenta de la organización.
        """

        sin_aprobar = make_animal(
            nombre="Willy", aprobado=False, estado="D", instagram_listo_para_publicar=True,
        )

        self.assertNotIn(sin_aprobar, self.tomados())

    def test_el_reservado_todavia_se_publica(self):
        """La contraparte: reservado no es adoptado, la reserva se puede caer."""

        reservado = make_animal(
            nombre="Willy", aprobado=True, estado="R", instagram_listo_para_publicar=True,
        )

        self.assertIn(reservado, self.tomados())

    def test_los_toma_del_mas_viejo_al_mas_nuevo(self):

        primero = make_animal(nombre="Willy", aprobado=True, instagram_listo_para_publicar=True)
        segundo = make_animal(nombre="Rocky", aprobado=True, instagram_listo_para_publicar=True)

        self.assertEqual(self.tomados(), [primero, segundo])


class CorteDelWorker(BaseException):
    """Lo que le pasa al proceso cuando el worker lo corta: no hereda de Exception.

    En /tools/publish/ el worker corta a los 30 s, y una publicación con varias fotos
    llega justo. Hereda de BaseException a propósito: un corte así no lo agarra ningún
    `except Exception` del camino, que es exactamente lo que lo hace peligroso.
    """


class GraphFalso:
    """Contesta como el Graph de Facebook y anota cada pedido que se le hizo.

    `falla_si` recibe (url, data) y devuelve si ese pedido tiene que explotar: sirve para
    romper un animal del medio de la tanda, o un paso puntual de la publicación. `error`
    es lo que se levanta cuando eso pasa.
    """

    def __init__(self):

        self.pedidos = []
        self.falla_si = None
        self.error = Exception("Graph contestó que no")
        self.posts_en_la_cuenta = []
        self.publicados = 0
        self.comentados = 0

    def request(self, url, **data):

        self.pedidos.append((url, data))

        if self.falla_si is not None and self.falla_si(url, data):
            raise self.error

        if "fields=status_code" in url:
            return {"status_code": "FINISHED"}

        if "fields=permalink" in url:
            post_id = url.split("?")[0]
            return {"id": post_id, "permalink": "https://instagr.am/p/{}".format(post_id)}

        if "fields=caption,permalink" in url:
            if "after=" in url:
                return {"data": []}
            return {"data": self.posts_en_la_cuenta, "paging": {"cursors": {"after": "x"}}}

        if url.endswith("/media_publish"):
            self.publicados += 1
            return {"id": "post-{}".format(self.publicados)}

        if url.endswith("/comments"):
            self.comentados += 1
            return {"id": "comentario-{}".format(self.comentados)}

        return {"id": "contenedor-{}".format(len(self.pedidos))}


@override_settings(ENV="TEST")
class PipelineDeInstagram(TestCase):
    """Base: cuenta vinculada, MEDIA_ROOT descartable y pyfb reemplazado."""

    def setUp(self):

        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.cuenta = FacebookAccount.objects.create(facebook_token="x", business_account_id="1")
        self.usuario = make_user()

        self.graph = GraphFalso()
        self.patcher = mock.patch("catus.services.facebook.Pyfb")
        self.Pyfb = self.patcher.start()
        self.Pyfb.return_value.request.side_effect = self.graph.request

    def tearDown(self):

        self.patcher.stop()
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def foto(self, animal, posicion=1, con_imagen_de_instagram=True):

        imagen = make_animal_image(animal=animal, posicion=posicion)
        if con_imagen_de_instagram:
            imagen.image_for_instagram.save("insta.jpg", uploaded_photo(), save=True)
        return imagen

    def animal_listo(self, nombre="Willy", fotos=1, **kwargs):
        """Un animal tal como lo deja hoy el equipo justo antes de que corra el cron."""

        kwargs.setdefault("aprobado", True)
        kwargs.setdefault("estado", "D")
        kwargs.setdefault("instagram_listo_para_publicar", True)

        animal = make_animal(nombre=nombre, cargado_por=self.usuario, **kwargs)

        for posicion in range(1, fotos + 1):
            self.foto(animal, posicion=posicion)

        return animal

    def correr_publish(self):

        salida = StringIO()
        call_command("publish", stdout=salida, stderr=salida)
        return salida.getvalue()

    def correr_comentarios(self):

        #update_status_in_ig y get_post_for informan con print(), no con self.stdout
        salida = StringIO()
        with redirect_stdout(salida):
            call_command("update_status_in_ig", stdout=salida, stderr=salida)
        return salida.getvalue()

    def correr_update_post_id(self):

        salida = StringIO()
        with redirect_stdout(salida):
            call_command("update_post_id", stdout=salida, stderr=salida)
        return salida.getvalue()

    def subidas(self):
        """Los pedidos que crean contenedores de imagen: los que cuestan y se ven."""

        return [data for url, data in self.graph.pedidos if "image_url" in data]

    def publicaciones(self):

        return [data for url, data in self.graph.pedidos if url.endswith("/media_publish")]

    def carruseles(self):

        return [data for url, data in self.graph.pedidos if data.get("media_type") == "CAROUSEL"]

    def comentarios(self):

        return [(url, data) for url, data in self.graph.pedidos if url.endswith("/comments")]


class PublishCommandTest(PipelineDeInstagram):
    """El cron `publish` de punta a punta, contando lo que llega a Instagram."""

    def test_publica_el_animal_marcado_y_guarda_el_post(self):

        animal = self.animal_listo()

        self.correr_publish()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado)
        self.assertEqual(animal.instagram_post_id, "post-1")
        self.assertEqual(animal.instagram_media_url, "https://instagr.am/p/post-1")
        self.assertEqual(len(self.publicaciones()), 1)

    def test_correrlo_dos_veces_publica_una_sola_vez(self):
        """Que la corrida siguiente lo saltee es lo único que evita el post duplicado.

        Publicar apaga además `instagram_listo_para_publicar`. Antes quedaba prendida para
        siempre, y como en el admin los cuatro checks son editables, destildar "publicado"
        —el gesto obvio para rehacer un post— lo devolvía a la cola: la corrida siguiente
        publicaba de nuevo, pisaba `instagram_post_id` y el post viejo quedaba huérfano,
        sin forma de recibir después el comentario de adoptado.
        """

        animal = self.animal_listo()

        self.correr_publish()
        self.correr_publish()

        self.assertEqual(len(self.publicaciones()), 1, "publicó dos veces")

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_post_id, "post-1")
        self.assertFalse(animal.instagram_listo_para_publicar, "la marca tiene que apagarse al publicar")

    def test_un_fallo_en_el_medio_no_frena_a_los_que_siguen(self):
        """Instagram rechaza uno y la tanda tiene que seguir con los demás."""

        willy = self.animal_listo(nombre="Willy")
        rocky = self.animal_listo(nombre="Rocky")
        luna = self.animal_listo(nombre="Luna")

        self.graph.falla_si = lambda url, data: "Rocky" in data.get("caption", "")

        self.correr_publish()

        for animal in (willy, luna):
            animal.refresh_from_db()
            self.assertTrue(animal.instagram_publicado, "{} se quedó sin publicar".format(animal.nombre))

        rocky.refresh_from_db()
        self.assertFalse(rocky.instagram_publicado)
        self.assertIsNone(rocky.instagram_post_id)

    def test_una_excepcion_de_publish_tampoco_frena_la_tanda(self):
        """El otro fallo posible: revienta nuestro código, no la API.

        `publish()` devuelve el error como texto en vez de propagarlo, así que el
        try/except del comando sólo lo cubre a él: un error de base al guardar, un
        template roto, cualquier cosa después de haber posteado.
        """

        publish_real = FacebookApiService.publish

        def publish_que_revienta_con_rocky(animal, ig_text):

            if animal.nombre == "Rocky":
                raise Exception("se cortó la base al guardar")

            return publish_real(animal, ig_text)

        willy = self.animal_listo(nombre="Willy")
        rocky = self.animal_listo(nombre="Rocky")
        luna = self.animal_listo(nombre="Luna")

        with mock.patch.object(FacebookApiService, "publish", side_effect=publish_que_revienta_con_rocky):
            salida = self.correr_publish()

        for animal in (willy, luna):
            animal.refresh_from_db()
            self.assertTrue(animal.instagram_publicado, "{} se quedó sin publicar".format(animal.nombre))

        rocky.refresh_from_db()
        self.assertFalse(rocky.instagram_publicado)
        self.assertIn("Rocky", salida, "no avisó cuál falló")

    def test_guarda_el_post_aunque_falle_el_permalink(self):
        """El post ya está arriba y no se puede deshacer: primero se guarda, después el link.

        Cuando el pedido del permalink se llevaba puesta a la publicación entera, el
        animal quedaba como no publicado y la corrida siguiente lo posteaba de nuevo.
        El permalink es sólo un link y lo completa después `update_post_id`.
        """

        animal = self.animal_listo()
        self.graph.falla_si = lambda url, data: "fields=permalink" in url

        self.correr_publish()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado)
        self.assertEqual(animal.instagram_post_id, "post-1")
        self.assertEqual(animal.instagram_media_url, "")

        #y la corrida siguiente no lo vuelve a postear
        self.correr_publish()
        self.assertEqual(len(self.publicaciones()), 1)

    def test_si_se_corta_pidiendo_el_permalink_el_post_ya_esta_guardado(self):
        """El orden de las escrituras, que es lo que el test de arriba no llega a ver.

        Que el pedido del permalink no propague no alcanza: lo que evita el post
        duplicado es que el animal quede guardado *antes* de pedirlo. Si el proceso se
        muere en el medio —el worker cortando a los 30 s— con el orden viejo no se
        guardaba nada, y el post que ya estaba arriba de Instagram quedaba como no
        publicado, así que la corrida siguiente del cron lo posteaba de nuevo.
        """

        animal = self.animal_listo()
        self.graph.error = CorteDelWorker("el worker cortó a los 30 s")
        self.graph.falla_si = lambda url, data: "fields=permalink" in url

        with self.assertRaises(CorteDelWorker):
            FacebookApiService.publish(animal, "texto")

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado, "el post está en Instagram y nadie lo anotó")
        self.assertEqual(animal.instagram_post_id, "post-1")
        self.assertNotIn(animal, PublishCommand().animales_a_publicar(), "lo volvería a publicar")

    def test_si_falla_media_publish_no_queda_como_publicado(self):
        """La contraparte del test de arriba: si el post no salió, no hay nada que guardar.

        Marcarlo publicado acá lo dejaría afuera del cron para siempre sin haber salido.
        """

        animal = self.animal_listo()
        self.graph.falla_si = lambda url, data: url.endswith("/media_publish")

        self.correr_publish()

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_publicado)
        self.assertIsNone(animal.instagram_post_id)

        #sigue en la cola para la corrida siguiente
        self.assertIn(animal, PublishCommand().animales_a_publicar())

    def test_una_sola_foto_va_como_foto_unica(self):

        self.animal_listo(fotos=1)

        self.correr_publish()

        self.assertEqual(len(self.subidas()), 1)
        self.assertEqual(self.carruseles(), [], "armó un carrusel con una sola foto")
        self.assertIn("caption", self.subidas()[0], "la foto única lleva el texto del post")

    def test_dos_fotos_o_mas_van_en_carrusel(self):

        self.animal_listo(fotos=3)

        self.correr_publish()

        self.assertEqual(len(self.subidas()), 3)

        carruseles = self.carruseles()
        self.assertEqual(len(carruseles), 1)
        self.assertEqual(len(carruseles[0]["children"].split(",")), 3)
        self.assertIn("caption", carruseles[0], "el texto va en el carrusel, no en cada foto")

    def test_el_carrusel_corta_en_diez(self):
        """Instagram no acepta más de diez: subir la once tira error y no publica nada."""

        self.animal_listo(fotos=11)

        self.correr_publish()

        self.assertEqual(len(self.subidas()), 10)
        self.assertEqual(len(self.carruseles()[0]["children"].split(",")), 10)

    def test_solo_van_las_fotos_con_la_imagen_de_instagram_generada(self):
        """Lo que se sube es `image_for_instagram`, que hoy se genera a mano aparte.

        Es el paso que se quiere automatizar: si el día de mañana se genera sola, este
        test tiene que seguir pasando, y si no se genera, el animal no se publica.
        """

        animal = self.animal_listo(fotos=0)
        self.foto(animal, posicion=1, con_imagen_de_instagram=False)

        salida = self.correr_publish()

        self.assertEqual(self.graph.pedidos, [], "habló con Instagram igual")
        self.assertIn("makeimages", salida)

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_publicado)

    def test_el_que_nunca_se_aprobo_no_llega_a_la_api(self):
        """Lo mismo que en el filtro, pero mirando lo que importa: que no salga el post."""

        self.animal_listo(aprobado=False)

        self.correr_publish()

        self.assertEqual(self.graph.pedidos, [])

    def test_el_adoptado_no_llega_a_la_api(self):

        self.animal_listo(estado="A")

        self.correr_publish()

        self.assertEqual(self.graph.pedidos, [])

    @override_settings(ENV="LOCAL")
    def test_en_local_no_toca_la_api(self):
        """La máquina de desarrollo tiene el token de producción.

        Probar la integración desde local dejaba un post de verdad en la cuenta de la
        organización: antes se reemplazaba la foto por una URL fija, pero se publicaba.
        """

        animal = self.animal_listo()

        salida = self.correr_publish()

        self.Pyfb.assert_not_called()
        self.assertEqual(self.graph.pedidos, [])
        self.assertIn("LOCAL", salida)

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_publicado)
        self.assertIn(animal, PublishCommand().animales_a_publicar(), "lo sacó de la cola sin publicarlo")


class AnimalesAComentarTest(TestCase):
    """Quién recibe el comentario de adoptado, sin llegar a mandarlo."""

    def tomados(self):

        return list(ComentarioCommand().animales_a_comentar())

    def test_tabla_de_quien_recibe_el_comentario(self):
        """Adoptado, publicado, con post y sin comentario previo."""

        for estado in ESTADOS:
            for publicado in (True, False):
                for post_id in ("post-1", None):
                    for comment_id in ("comentario-1", None):

                        entra = estado == "A" and publicado and post_id is not None and comment_id is None

                        with self.subTest(estado=estado, publicado=publicado, post_id=post_id, comment_id=comment_id):

                            animal = make_animal(
                                nombre="Willy",
                                estado=estado,
                                instagram_publicado=publicado,
                                instagram_post_id=post_id,
                                instagram_comment_id=comment_id,
                            )

                            self.assertEqual(animal in self.tomados(), entra)

                            animal.delete()

    def test_el_reservado_no_recibe_el_comentario_de_adoptado(self):
        """El comentario dice "Ya fue adoptado" y también les caía a los reservados.

        Una reserva se puede caer, pero el comentario queda y `instagram_comment_id`
        hace que no se vuelva a mirar: el post quedaba mintiendo para siempre. Si después
        se adopta de verdad, lo toma una corrida posterior.
        """

        reservado = make_animal(
            nombre="Willy", estado="R", instagram_publicado=True, instagram_post_id="post-1",
        )

        self.assertNotIn(reservado, self.tomados())

    def test_el_adoptado_que_nunca_se_publico_no_recibe_comentario(self):

        sin_publicar = make_animal(nombre="Willy", estado="A", instagram_publicado=False)

        self.assertNotIn(sin_publicar, self.tomados())


class ComentarioAdoptadoTest(PipelineDeInstagram):
    """El cron `update_status_in_ig`, contando los comentarios que llegan a Instagram."""

    def animal_publicado(self, nombre="Willy", estado="A", post_id="post-1", **kwargs):

        return make_animal(
            nombre=nombre,
            cargado_por=self.usuario,
            estado=estado,
            aprobado=True,
            instagram_listo_para_publicar=True,
            instagram_publicado=True,
            instagram_post_id=post_id,
            instagram_media_url="https://instagr.am/p/{}".format(post_id),
            **kwargs
        )

    def test_comenta_el_adoptado_y_guarda_el_comment_id(self):

        animal = self.animal_publicado()

        self.correr_comentarios()

        self.assertEqual(len(self.comentarios()), 1)

        url, data = self.comentarios()[0]
        self.assertEqual(url, "post-1/comments")
        self.assertIn("adoptado", data["message"].lower())

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_comment_id, "comentario-1")

    def test_no_vuelve_a_comentar_en_la_corrida_siguiente(self):
        """`instagram_comment_id` es lo único que lo saca de la cola."""

        self.animal_publicado()

        self.correr_comentarios()
        self.correr_comentarios()

        self.assertEqual(len(self.comentarios()), 1, "comentó dos veces el mismo post")

    def test_el_reservado_no_recibe_comentario(self):

        self.animal_publicado(estado="R")

        self.correr_comentarios()

        self.assertEqual(self.comentarios(), [])

    def test_el_texto_concuerda_con_el_sexo(self):

        self.animal_publicado(nombre="Luna", sexo="H")

        self.correr_comentarios()

        url, data = self.comentarios()[0]
        self.assertIn("adoptada", data["message"].lower())

    def test_un_fallo_no_frena_a_los_que_siguen(self):

        willy = self.animal_publicado(nombre="Willy", post_id="post-willy")
        rocky = self.animal_publicado(nombre="Rocky", post_id="post-rocky")
        luna = self.animal_publicado(nombre="Luna", post_id="post-luna")

        self.graph.falla_si = lambda url, data: url.startswith("post-rocky")

        salida = self.correr_comentarios()

        for animal in (willy, luna):
            animal.refresh_from_db()
            self.assertIsNotNone(animal.instagram_comment_id, "{} se quedó sin comentario".format(animal.nombre))

        rocky.refresh_from_db()
        self.assertIsNone(rocky.instagram_comment_id)
        self.assertIn("Rocky", salida, "no avisó cuál falló")

    @override_settings(ENV="LOCAL")
    def test_en_local_no_comenta(self):
        """El mismo corte que publish(): desde local el comentario iba a un post real."""

        animal = self.animal_publicado()

        self.correr_comentarios()

        self.Pyfb.assert_not_called()
        self.assertEqual(self.graph.pedidos, [])

        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_comment_id)
        self.assertIn(animal, ComentarioCommand().animales_a_comentar(), "lo sacó de la cola sin comentar")


class UpdatePostIdTest(PipelineDeInstagram):
    """El cron que completa lo que quedó a medias después de publicar."""

    def test_completa_el_permalink_que_falto_al_publicar(self):
        """publish() guarda el post apenas sale y el permalink puede quedar vacío.

        Cuando este cron filtraba sólo por `instagram_post_id` nulo, el animal al que le
        faltaba nada más el link no entraba nunca y se quedaba sin permalink para siempre.
        """

        animal = make_animal(
            nombre="Willy", instagram_publicado=True, instagram_post_id="post-1", instagram_media_url="",
        )
        self.graph.posts_en_la_cuenta = [{
            "id": "post-1",
            "caption": "🐱 ¡Willy en Adopción Responsable! 🐱",
            "permalink": "https://instagr.am/p/post-1",
        }]

        self.correr_update_post_id()

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_media_url, "https://instagr.am/p/post-1")

    def test_no_le_pone_el_post_de_otro_animal_que_se_llama_igual(self):
        """FALLA: busca el post por el nombre en el caption y se queda con el último.

        `get_post_for` recorre todos los posts de la cuenta y le asigna al animal
        cualquiera cuyo caption contenga "<nombre> en adopción responsable", sin cortar
        en el primero: gana el último de la lista. Dos gatas llamadas Luna alcanzan, y
        Luna, Mía o Simba se repiten todo el tiempo.

        Y encima pisa un `instagram_post_id` que ya era correcto. Justamente el animal
        que entra acá es el que publicó bien pero se quedó sin permalink, o sea el que ya
        tiene su post_id bueno guardado: lo único que le falta es el link. Después, cuando
        se adopte, `update_status_in_ig` va a comentar "¡Ya fue adoptada!" en el post de
        la otra gata, que sigue buscando hogar.

        Lo que debería hacer: si el animal ya tiene `instagram_post_id`, pedirle el
        permalink a ese post en vez de adivinarlo por el nombre.
        """

        vieja = make_animal(
            nombre="Luna",
            instagram_publicado=True,
            instagram_post_id="post-viejo",
            instagram_media_url="https://instagr.am/p/post-viejo",
        )
        #la que acaba de publicar: el pedido del permalink falló y quedó sin link
        nueva = make_animal(
            nombre="Luna",
            instagram_publicado=True,
            instagram_post_id="post-nuevo",
            instagram_media_url="",
        )

        #Graph devuelve la media de la cuenta de la más nueva a la más vieja
        self.graph.posts_en_la_cuenta = [
            {
                "id": "post-nuevo",
                "caption": "🐱 ¡Luna en Adopción Responsable! 🐱",
                "permalink": "https://instagr.am/p/post-nuevo",
            },
            {
                "id": "post-viejo",
                "caption": "🐱 ¡Luna en Adopción Responsable! 🐱",
                "permalink": "https://instagr.am/p/post-viejo",
            },
        ]

        self.correr_update_post_id()

        nueva.refresh_from_db()
        self.assertEqual(nueva.instagram_post_id, "post-nuevo", "le pisó el post con el de la otra Luna")
        self.assertEqual(nueva.instagram_media_url, "https://instagr.am/p/post-nuevo")

        vieja.refresh_from_db()
        self.assertEqual(vieja.instagram_post_id, "post-viejo")

    def test_no_pisa_al_que_ya_tiene_todo(self):

        animal = make_animal(
            nombre="Willy",
            instagram_publicado=True,
            instagram_post_id="post-1",
            instagram_media_url="https://instagr.am/p/post-1",
        )
        self.graph.posts_en_la_cuenta = [{
            "id": "otro-post",
            "caption": "🐱 ¡Willy en Adopción Responsable! 🐱",
            "permalink": "https://instagr.am/p/otro-post",
        }]

        self.correr_update_post_id()

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_post_id, "post-1")
        self.assertEqual(animal.instagram_media_url, "https://instagr.am/p/post-1")


class CicloCompletoTest(PipelineDeInstagram):
    """El recorrido entero, que es lo que el día de mañana va a arrancar solo."""

    def test_de_marcado_a_publicado_a_adoptado(self):

        animal = self.animal_listo(fotos=2)

        self.correr_publish()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado)
        self.assertEqual(animal.instagram_post_id, "post-1")

        animal.set_estado("A")
        animal.save()

        self.correr_comentarios()

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_comment_id, "comentario-1")

        #y los dos crones vuelven a correr sin hacer nada
        self.correr_publish()
        self.correr_comentarios()

        self.assertEqual(len(self.publicaciones()), 1)
        self.assertEqual(len(self.comentarios()), 1)


@override_settings(INSTAGRAM_AUTO_ACTIVO=True)
class PosteoAutomaticoDePuntaAPunta(PipelineDeInstagram):
    """Los dos crones seguidos: `preparar_publicaciones` arma y `publish` postea.

    Es el recorrido que arranca solo al aprobar un animal, sin que nadie apriete nada.
    """

    def agendado(self, nombre="Willy", fotos=1, hace=timedelta(minutes=5), **kwargs):
        """Un animal como lo deja la aprobación: agendado, y con las fotos sin armar."""

        kwargs.setdefault("aprobado", True)
        kwargs.setdefault("estado", "D")
        kwargs.setdefault("instagram_programado_para", timezone.now() - hace)

        animal = make_animal(nombre=nombre, cargado_por=self.usuario, **kwargs)

        for posicion in range(1, fotos + 1):
            self.foto(animal, posicion=posicion, con_imagen_de_instagram=False)

        return animal

    def correr_preparar(self):

        salida = StringIO()
        call_command("preparar_publicaciones", stdout=salida, stderr=salida)

        return salida.getvalue()

    def correr_los_dos_crones(self):

        salida = self.correr_preparar()

        publicacion = StringIO()
        call_command("publish", stdout=publicacion, stderr=publicacion)

        return salida + publicacion.getvalue()

    def test_el_agendado_se_prepara_y_se_publica_solo(self):

        animal = self.agendado()

        self.correr_los_dos_crones()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_publicado)
        self.assertEqual(len(self.publicaciones()), 1)

    def test_frenar_el_posteo_lo_frena_para_siempre(self):
        """La regla que sostiene toda la demora: lo que una persona frena, no lo resucita
        ningún cron.

        `instagram_programado_para` no se limpiaba nunca. El equipo entraba a /tools/ y
        destildaba "listo para publicar" -el gesto de freno-, pero la agenda seguía vencida:
        la corrida siguiente de `preparar_publicaciones` levantaba al animal de nuevo, le
        volvía a prender la marca, y el posteo salía igual media hora más tarde.
        """

        animal = self.agendado()

        #la corrida que lo prepara y lo deja en la cola de `publish`
        self.correr_preparar()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_listo_para_publicar)
        self.assertFalse(animal.instagram_publicado)

        #el freno, tal como lo escribe /tools/saveform/ al destildar la marca
        Animal.objects.filter(id=animal.id).update(instagram_listo_para_publicar=False)

        #y los dos crones siguen corriendo, como todos los días
        self.correr_los_dos_crones()
        self.correr_los_dos_crones()

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar, "el cron le volvió a prender la marca")
        self.assertFalse(animal.instagram_publicado)
        self.assertEqual(self.publicaciones(), [], "salió un posteo que alguien había frenado")
