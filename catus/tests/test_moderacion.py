"""Tests de la revisión automática de publicaciones.

Dos reglas que no se pueden romper:
  1. Es una ayuda para el equipo. Pase lo que pase (API caída, sin crédito, respuesta
     rara) nunca puede impedir que se guarde ni que se publique un animal.
  2. Marcar de más hace daño: si el filtro se equivoca, alguien que rescató un animal
     no lo puede publicar. Ante la duda, aprueba.
"""
import json
import shutil
import tempfile
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from catus.models import Animal, RevisionIALlamada
from catus.services.moderacion import ModeracionService
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo
from catus.views.animal import EditView


def visto(animales, descripcion="Se ve un gato.", texto_sospechoso=False, inapropiado=False):
    """Lo que devuelve el modelo: describe lo que ve, no juzga."""

    return json.dumps({
        "animales": animales,
        "descripcion": descripcion,
        "texto_sospechoso": texto_sospechoso,
        "inapropiado": inapropiado,
    })


def con_respuesta(contenido):

    return mock.patch.object(ModeracionService, "_preguntar", return_value=contenido)


def con_error(error=None):

    return mock.patch.object(
        ModeracionService, "_preguntar", side_effect=error or RuntimeError("API caída"),
    )


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST")
class DecidirTest(TestCase):
    """La política vive en código, no en el prompt: acá se prueba sin tocar la API.

    Se separó así porque pedirle al modelo que juzgara hacía que copiara las reglas
    en vez de mirar la foto, y marcaba como sospechosas fotos de gatos normales.
    """

    def setUp(self):
        self.service = ModeracionService()
        self.gato = make_animal(nombre="Willy", tipo="G")
        self.perro = make_animal(nombre="Rocco", tipo="P")

    def decidir(self, animal, **kwargs):

        datos = json.loads(visto(**kwargs)) if "animales" in kwargs else json.loads(visto(["gato"]))
        return self.service.decidir(animal, datos)

    def test_un_gato_declarado_gato_pasa(self):

        estado, _ = self.service.decidir(self.gato, json.loads(visto(["gato"])))

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_un_perro_declarado_perro_pasa(self):

        estado, _ = self.service.decidir(self.perro, json.loads(visto(["perro"])))

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_sin_animales_se_manda_a_revisar(self):

        estado, motivo = self.service.decidir(self.gato, json.loads(visto([], "Es una captura de pantalla.")))

        self.assertEqual(estado, Animal.REVISION_REVISAR)
        self.assertIn("animal", motivo.lower())

    def test_texto_de_spam_se_manda_a_revisar(self):

        estado, motivo = self.service.decidir(
            self.gato, json.loads(visto(["gato"], texto_sospechoso=True)),
        )

        self.assertEqual(estado, Animal.REVISION_REVISAR)
        self.assertIn("spam", motivo.lower())

    def test_contenido_inapropiado_se_manda_a_revisar(self):

        estado, motivo = self.service.decidir(
            self.gato, json.loads(visto(["gato"], inapropiado=True)),
        )

        self.assertEqual(estado, Animal.REVISION_REVISAR)
        self.assertIn("inapropiado", motivo.lower())

    def test_equivocarse_de_especie_no_frena_la_publicacion(self):
        """Errar el desplegable es un error de tipeo, no spam. Se avisa, no se bloquea."""

        estado, motivo = self.service.decidir(self.gato, json.loads(visto(["perro"])))

        self.assertEqual(estado, Animal.REVISION_OK)
        self.assertIn("perro", motivo.lower())

    def test_un_animal_que_no_se_distingue_pasa(self):
        """Foto oscura o de lejos: el modelo dice "otro". No es motivo para frenar."""

        estado, _ = self.service.decidir(self.gato, json.loads(visto(["otro"])))

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_varios_animales_en_la_foto_pasan(self):

        estado, _ = self.service.decidir(self.gato, json.loads(visto(["gato", "perro"])))

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_lo_inapropiado_gana_sobre_todo_lo_demas(self):

        estado, motivo = self.service.decidir(
            self.gato, json.loads(visto(["gato"], inapropiado=True, texto_sospechoso=True)),
        )

        self.assertEqual(estado, Animal.REVISION_REVISAR)
        self.assertIn("inapropiado", motivo.lower())


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST")
class RevisarTest(TestCase):

    def setUp(self):
        self.service = ModeracionService()
        self.animal = make_animal(nombre="Willy", tipo="G", datos="Gatito en adopción.")
        make_animal_image(animal=self.animal)

    def test_aprueba_una_publicacion_valida(self):

        with con_respuesta(visto(["gato"], "Se ve un gato atigrado.")):
            estado, motivo = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_OK)
        self.assertIn("gato", motivo.lower())

    def test_entiende_la_respuesta_envuelta_en_markdown(self):

        with con_respuesta("```json\n" + visto(["gato"]) + "\n```"):
            estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_entiende_json_con_texto_alrededor(self):

        with con_respuesta("Acá va: " + visto([]) + " listo"):
            estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_REVISAR)

    def test_una_respuesta_vacia_no_rompe(self):
        """openai devuelve content=None cuando el modelo se rehúsa a describir una imagen.

        Antes esto explotaba en la propia línea de log (contenido[:200] sobre None), que
        estaba fuera del try: el rescatista veía un 500 con el animal ya guardado.
        """

        with con_respuesta(None):
            estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_ERROR)

    def test_una_respuesta_vacia_tampoco_rompe_al_guardar(self):

        with con_respuesta(None):
            estado = self.service.revisar_y_guardar(self.animal)

        self.assertEqual(estado, Animal.REVISION_ERROR)

    def test_animales_con_forma_rara_es_error_y_no_sospecha(self):
        """Distinción que importa: si el modelo manda basura donde va la lista, es
        "no se pudo revisar", no "sospechoso". Marcarlo como sospechoso frenaría la
        publicación de un animal legítimo por culpa de nuestro propio parseo."""

        for basura in [1, {"a": 1}, True]:
            with con_respuesta(json.dumps({"animales": basura, "descripcion": "x"})):
                estado, _ = self.service.revisar(self.animal)

            self.assertEqual(
                estado, Animal.REVISION_ERROR,
                "animales={!r} debería dar error, no sospecha".format(basura),
            )

    def test_un_animal_como_texto_suelto_se_entiende(self):
        """Si manda "gato" en vez de ["gato"], se entiende igual."""

        with con_respuesta(json.dumps({"animales": "gato", "descripcion": "Un gato."})):
            estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_una_descripcion_mal_formada_no_descarta_un_veredicto_valido(self):
        """La descripción es cosmética: si la lista de animales vino bien, se aprueba
        igual. Perder una revisión válida por un campo de texto sería peor."""

        with con_respuesta(json.dumps({"animales": ["gato"], "descripcion": ["a", "b"]})):
            estado, motivo = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_OK)
        self.assertIsInstance(motivo, str)
        #y no imprime el repr de la estructura en la pantalla del equipo
        self.assertNotIn("[", motivo)

    def test_una_lista_json_en_vez_de_objeto_es_error(self):

        with con_respuesta('[{"animales": ["gato"]}]'):
            estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_ERROR)

    def test_una_respuesta_ininteligible_no_marca_el_animal(self):
        """Ante la duda no se penaliza: queda como error, no como sospechoso."""

        with con_respuesta("no tengo idea"):
            estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_ERROR)

    def test_si_la_api_falla_no_levanta_excepcion(self):

        with con_error():
            estado, motivo = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_ERROR)
        self.assertTrue(motivo)

    def test_sin_credito_tampoco_rompe(self):

        with con_error(RuntimeError("insufficient_quota: no credits")):
            estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_ERROR)

    def test_un_animal_sin_fotos_no_se_marca_como_sospechoso(self):

        estado, _ = self.service.revisar(make_animal(nombre="Sin fotos"))

        self.assertEqual(estado, Animal.REVISION_ERROR)

    @override_settings(MODERACION_IA_ACTIVA=False)
    def test_desactivada_no_llama_a_la_api(self):

        with mock.patch.object(ModeracionService, "_preguntar") as preguntar:
            estado, _ = self.service.revisar(self.animal)

        preguntar.assert_not_called()
        self.assertEqual(estado, Animal.REVISION_ERROR)

    @override_settings(OPENIA_API_KEY="")
    def test_sin_key_no_llama_a_la_api(self):

        with mock.patch.object(ModeracionService, "_preguntar") as preguntar:
            self.service.revisar(self.animal)

        preguntar.assert_not_called()

    def test_guarda_el_resultado_en_el_animal(self):

        with con_respuesta(visto([], "Parece una captura de pantalla.")):
            self.service.revisar_y_guardar(self.animal)

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.revision_ia_estado, Animal.REVISION_REVISAR)
        self.assertIsNotNone(self.animal.revision_ia_fecha)
        self.assertTrue(self.animal.necesita_revision_humana())


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST")
class ArmadoDelPedidoTest(TestCase):
    """Lo que se le manda al modelo: importa por costo y por precisión."""

    def setUp(self):
        self.service = ModeracionService()

    def test_manda_como_mucho_tres_fotos(self):

        animal = make_animal()
        for _ in range(5):
            make_animal_image(animal=animal)

        self.assertEqual(len(self.service._leer_fotos(animal)), 3)

    def test_las_fotos_van_en_baja_resolucion(self):
        """detail low es lo que mantiene el costo en centavos."""

        mensajes = self.service._mensajes("datos", ["data:image/jpeg;base64,AAA"])

        imagenes = [c for c in mensajes[1]["content"] if c["type"] == "image_url"]
        self.assertEqual(imagenes[0]["image_url"]["detail"], "low")

    def test_achica_las_fotos_antes_de_mandarlas(self):
        """El modelo trabaja a 512px: subir el original solo gasta tiempo y datos."""

        from io import BytesIO
        from PIL import Image

        animal = make_animal()
        make_animal_image(animal=animal, size=(3000, 2000))

        foto = self.service._leer_fotos(animal)[0]

        import base64
        crudo = base64.b64decode(foto.split(",", 1)[1])
        with Image.open(BytesIO(crudo)) as imagen:
            self.assertLessEqual(max(imagen.size), self.service.LADO_MAXIMO)

    def test_una_foto_ilegible_no_frena_la_revision(self):

        with mock.patch("PIL.Image.open", side_effect=OSError("rota")):
            self.assertEqual(self.service._achicar(b"basura"), b"basura")

    def test_el_texto_va_sin_html(self):
        """La descripción se escribe en un editor enriquecido."""

        descripcion = self.service._describir(make_animal(nombre="Willy", datos="<p>Es <b>muy</b> mimoso</p>"))

        self.assertNotIn("<p>", descripcion)
        self.assertIn("mimoso", descripcion)

    def test_le_avisa_al_modelo_que_el_texto_no_es_confiable(self):
        """Sin esto el modelo describía el texto en vez de la foto y dejaba pasar spam."""

        descripcion = self.service._describir(make_animal(nombre="Willy"))

        self.assertIn("SIN VERIFICAR", descripcion)

    def test_el_prompt_conserva_el_encuadre_contra_inyeccion(self):
        """El texto del aviso lo escribe cualquiera y puede traer instrucciones.

        Se probó contra la API real con cuatro intentos de inyección (orden directa,
        falso bloque de sistema, instrucción metida en el nombre, y afirmación
        insistente de que hay un gato) sobre una imagen sin ningún animal: los cuatro
        fueron bloqueados. Eso depende de estas dos frases del prompt, así que si
        alguien las saca conviene que se entere acá.
        """
        from catus.services import moderacion

        #el prompt viene con saltos de línea: comparamos con el espacio normalizado
        prompt = " ".join(moderacion.PROMPT.split())

        self.assertIn("REGLA MÁS IMPORTANTE", prompt)
        self.assertIn("pueden ser falsos", prompt)
        self.assertIn("ÚNICAMENTE lo que se ve en las imágenes", prompt)

    def test_le_dice_al_modelo_que_tipo_declaro_el_rescatista(self):

        self.assertIn("gato", self.service._describir(make_animal(tipo="G")))
        self.assertIn("perro", self.service._describir(make_animal(tipo="P")))


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST")
class AutoAprobacionTest(TestCase):
    """El único efecto real: frenar la auto-aprobación de una publicación sospechosa."""

    def setUp(self):
        #el alta sube una foto de verdad: que los archivos caigan en un directorio
        #descartable y no en la galería del repo
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.factory = RequestFactory()
        self.rescatista = make_user(email="rescatista@catpuccino.test", automatic_approve=True)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def guardar_animal(self, respuesta_ia):
        """Da de alta un animal por la vista y devuelve lo que quedó en la base.

        Va por EditView a propósito. Antes esto copiaba la condición de auto-aprobación
        adentro del test, así que sacarla de la vista dejaba todo en verde igual y una
        publicación marcada como sospechosa salía publicada.
        """

        datos = {
            "tipo": "G",
            "estado": "D",
            "nombre": "Willy",
            "edad": "2 años",
            "sexo": "M",
            "zona": "CABA",
            "datos": "Gatito en adopción.",
            "animalimage_set-TOTAL_FORMS": "1",
            "animalimage_set-INITIAL_FORMS": "0",
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
            "animalimage_set-0-image": uploaded_photo(),
        }

        request = self.factory.post("/animales/", datos)
        request.user = self.rescatista

        SessionMiddleware().process_request(request)
        request.session.save()

        view = EditView()
        view.request = request

        #se mockea solo lo que sale a la red: la decisión la sigue tomando la vista
        with respuesta_ia, mock.patch("catus.views.animal.MailService"):
            view.req(is_post=True)

        animal = Animal.objects.filter(nombre="Willy").first()
        self.assertIsNotNone(animal, "el alta no guardó el animal: el POST del test quedó viejo")

        return animal

    def test_una_publicacion_valida_se_auto_aprueba(self):

        self.assertTrue(self.guardar_animal(con_respuesta(visto(["gato"]))).aprobado)

    def test_una_sospechosa_queda_esperando_revision(self):

        animal = self.guardar_animal(con_respuesta(visto([], "No se ve ningún animal.")))

        self.assertFalse(animal.aprobado, "una publicación marcada como sospechosa se publicó sola")
        self.assertTrue(animal.necesita_revision_humana())

    def test_si_la_ia_falla_se_auto_aprueba_igual(self):
        """Una caída de OpenAI no puede frenar el flujo normal del rescatista."""

        animal = self.guardar_animal(con_error())

        self.assertEqual(animal.revision_ia_estado, Animal.REVISION_ERROR)
        self.assertTrue(animal.aprobado, "una falla nuestra le frenó la publicación al rescatista")


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST")
class LimiteDiarioTest(TestCase):
    """El registro es abierto y cada alta cuesta plata: sin tope, cualquiera puede
    vaciarle la cuenta de OpenAI al refugio."""

    def setUp(self):
        self.service = ModeracionService()
        self.usuario = make_user(email="alguien@ejemplo.test")

    def cargar_revisados(self, cantidad, usuario=None):
        """Anota llamadas pagas ya gastadas por esa persona.

        Se anotan como filas de RevisionIALlamada y no como animales con
        revision_ia_fecha: contar animales no ve las re-revisiones de uno mismo.
        """

        for i in range(cantidad):
            self.service._contar_llamada(usuario or self.usuario)

    def test_deja_pasar_dentro_del_cupo(self):

        self.cargar_revisados(3)

        self.assertFalse(self.service.paso_el_limite(self.usuario))

    def test_frena_al_llegar_al_tope(self):

        self.cargar_revisados(self.service.get_limite_diario())

        self.assertTrue(self.service.paso_el_limite(self.usuario))

    def test_el_tope_es_por_persona(self):

        otro = make_user(email="otro@ejemplo.test")
        self.cargar_revisados(self.service.get_limite_diario())

        self.assertFalse(self.service.paso_el_limite(otro))

    def test_no_cuenta_las_de_ayer(self):

        from django.utils import timezone
        from datetime import timedelta

        ayer = timezone.now() - timedelta(days=2)
        for i in range(self.service.get_limite_diario()):
            RevisionIALlamada.objects.create(pedido_por=self.usuario, created_at=ayer)

        self.assertFalse(self.service.paso_el_limite(self.usuario))

    def test_pasarse_del_tope_no_bloquea_la_publicacion(self):
        """Quedar sin revisar es el mismo estado que tenían todos antes de esto."""

        self.cargar_revisados(self.service.get_limite_diario())
        animal = make_animal(nombre="Nuevo", cargado_por=self.usuario)
        make_animal_image(animal=animal)

        with mock.patch.object(ModeracionService, "_preguntar") as preguntar:
            estado, _ = self.service.revisar(animal)

        preguntar.assert_not_called()
        self.assertEqual(estado, Animal.REVISION_ERROR)
        self.assertNotEqual(estado, Animal.REVISION_REVISAR)

    @override_settings(MODERACION_IA_MAX_POR_DIA=0)
    def test_se_puede_desactivar_el_tope(self):

        self.cargar_revisados(50)

        self.assertFalse(self.service.paso_el_limite(self.usuario))

    def test_un_animal_sin_dueno_no_rompe(self):

        self.assertFalse(self.service.paso_el_limite(None))


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST")
class BooleanosDelModeloTest(TestCase):
    """gpt-4o-mini a veces manda los booleanos como texto."""

    def setUp(self):
        self.service = ModeracionService()
        self.animal = make_animal(nombre="Willy", tipo="G")

    def test_false_como_texto_no_manda_a_revisar(self):
        """En Python "false" es verdadero: sin convertirlo, mandaba a revisión humana
        una publicación perfectamente sana."""

        datos = {"animales": ["gato"], "descripcion": "Un gato.",
                 "texto_sospechoso": "false", "inapropiado": "false"}

        estado, _ = self.service.decidir(self.animal, datos)

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_true_como_texto_si_manda_a_revisar(self):

        datos = {"animales": ["gato"], "descripcion": "x", "inapropiado": "true"}

        estado, _ = self.service.decidir(self.animal, datos)

        self.assertEqual(estado, Animal.REVISION_REVISAR)

    def test_no_y_si_tambien_se_entienden(self):

        self.assertFalse(self.service._es_verdadero("no"))
        self.assertFalse(self.service._es_verdadero("No"))
        self.assertTrue(self.service._es_verdadero("sí"))
        self.assertTrue(self.service._es_verdadero(True))
        self.assertFalse(self.service._es_verdadero(None))


class EntornoTest(TestCase):
    """Desde una máquina de desarrollo no se mandan fotos reales con la key real."""

    @override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="k", ENV="LOCAL")
    def test_en_local_no_llama_a_la_api(self):

        animal = make_animal(nombre="Willy")
        make_animal_image(animal=animal)

        with mock.patch.object(ModeracionService, "_preguntar") as preguntar:
            estado, _ = ModeracionService().revisar(animal)

        preguntar.assert_not_called()
        self.assertEqual(estado, Animal.REVISION_ERROR)

    @override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="k", ENV="PROD")
    def test_en_produccion_si(self):

        self.assertTrue(ModeracionService().esta_activa())


class TiempoAcotadoTest(TestCase):
    """El alta del animal espera esto sincrónicamente y el worker corta a los 30s."""

    def test_no_reintenta(self):

        self.assertEqual(ModeracionService.REINTENTOS, 0)

    def test_el_peor_caso_entra_en_el_worker(self):
        """timeout x (reintentos + 1) tiene que quedar bien por debajo de 30s."""

        service = ModeracionService()
        peor_caso = service.TIMEOUT * (service.REINTENTOS + 1)

        self.assertLess(peor_caso, 15, "el alta puede pasarse del timeout del worker")


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST")
class SinAnimalPorPalabrasTest(TestCase):
    """El prompt pide lista vacía cuando no hay animales, pero el modelo a veces lo
    dice con palabras. Sin normalizar eso, ["ninguno"] contaba como "hay un animal"
    y la publicación se auto-aprobaba igual."""

    def setUp(self):
        self.service = ModeracionService()
        self.animal = make_animal(nombre="Willy", tipo="G")

    def test_las_formas_de_decir_que_no_hay_animal_se_entienden(self):

        for crudo in [[], ["ninguno"], ["ninguna"], [""], ["  "], ["none"], ["null"],
                      ["no"], ["nada"], ["sin animales"], ["N/A"], ["NINGUNO"]]:
            estado, _ = self.service.decidir(
                self.animal, {"animales": crudo, "descripcion": "Es una captura."},
            )

            self.assertEqual(
                estado, Animal.REVISION_REVISAR,
                "animales={!r} se auto-aprobó".format(crudo),
            )

    def test_un_animal_de_verdad_sigue_pasando(self):

        for crudo in [["gato"], ["perro"], ["otro"], ["gato", "perro"]]:
            estado, _ = self.service.decidir(self.animal, {"animales": crudo})

            self.assertEqual(estado, Animal.REVISION_OK, "animales={!r}".format(crudo))

    def test_una_negacion_mezclada_con_un_animal_no_lo_tapa(self):

        estado, _ = self.service.decidir(self.animal, {"animales": ["ninguno", "gato"]})

        self.assertEqual(estado, Animal.REVISION_OK)


class TextoDeRefugioTest(TestCase):
    """Un refugio argentino pone el alias y el CVU para donaciones en la descripción.

    Con la definición de spam anterior ("pide plata o datos bancarios") el modelo
    marcaba esas publicaciones y frenaba la auto-aprobación. Verificado contra la API
    real: 1 de 5 textos legítimos quedaba frenado; después del cambio, 0 de 5, y los
    2 de spam real se siguen frenando.
    """

    def test_el_prompt_aclara_que_pedir_donaciones_no_es_spam(self):

        from catus.services import moderacion

        prompt = " ".join(moderacion.PROMPT.split())

        self.assertIn("NO es spam", prompt)
        self.assertIn("donaciones", prompt)
        self.assertNotIn("pide plata o datos bancarios", prompt)


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST",
                   MODERACION_IA_MAX_POR_DIA=3)
class LimiteDiarioPorLlamadasTest(TestCase):
    """El tope cuenta llamadas pagas, no animales revisados.

    Antes se contaban los animales con revision_ia_fecha reciente, pero
    revisar_y_guardar pisa esa fecha sobre la MISMA fila: editando en bucle un
    mismo animal (cambiarle el nombre ya dispara la re-revisión) el conteo se
    quedaba en 1 para siempre y las llamadas pagas a OpenAI eran ilimitadas. Con
    el registro abierto, eso es la cuenta del refugio vaciada con un script.
    """

    def setUp(self):
        self.service = ModeracionService()
        self.usuario = make_user(email="editor@ejemplo.test")
        self.animal = make_animal(nombre="Willy", tipo="G", cargado_por=self.usuario)
        make_animal_image(animal=self.animal)

    def revisar_editando(self, veces, animal=None, preguntar=None):
        """Simula que alguien edita el mismo animal una y otra vez."""

        animal = animal or self.animal

        for i in range(veces):
            #lo que dispara la re-revisión desde la vista es que cambie algo revisable
            animal.nombre = "Willy {}".format(i)
            self.service.revisar_y_guardar(animal)

    def test_reeditar_el_mismo_animal_no_da_llamadas_pagas_infinitas(self):
        """Una sola fila editada N+1 veces tiene que dejar de llamar a la API."""

        tope = self.service.get_limite_diario()

        with mock.patch.object(
            ModeracionService, "_preguntar", return_value=visto(["gato"]),
        ) as preguntar:
            self.revisar_editando(tope + 3)

        self.assertEqual(
            preguntar.call_count, tope,
            "editando el mismo animal se gastaron {} llamadas pagas con un tope de {}".format(
                preguntar.call_count, tope,
            ),
        )

    def test_pasarse_editando_no_bloquea_ni_marca_al_animal(self):
        """Pasarse del tope no es sospecha: el animal queda cargado y sin revisar,
        que es el mismo estado que tenían todos antes de que esto existiera."""

        tope = self.service.get_limite_diario()

        with mock.patch.object(ModeracionService, "_preguntar", return_value=visto(["gato"])):
            self.revisar_editando(tope + 2)

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.revision_ia_estado, Animal.REVISION_ERROR)
        self.assertFalse(
            self.animal.necesita_revision_humana(),
            "quedarse sin cupo le frenó la publicación a un rescatista",
        )

    def test_el_cupo_gastado_es_de_esa_persona(self):
        """Que alguien queme su cupo editando no puede dejar sin revisión a otro."""

        otro = make_user(email="otra@ejemplo.test")
        suyo = make_animal(nombre="Rocco", tipo="P", cargado_por=otro)
        make_animal_image(animal=suyo)

        with mock.patch.object(
            ModeracionService, "_preguntar", return_value=visto(["gato"]),
        ) as preguntar:
            self.revisar_editando(self.service.get_limite_diario() + 2)
            preguntar.reset_mock()

            self.service.revisar_y_guardar(suyo)

        self.assertEqual(preguntar.call_count, 1)


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="test-key", ENV="TEST",
                   MODERACION_IA_MAX_POR_DIA=3)
class CupoEnBaseTest(TestCase):
    """El cupo se cuenta en base y no en django.core.cache.

    El proyecto no configura CACHES, así que el backend real es LocMemCache: por
    proceso y en memoria. En producción hay varios workers de gunicorn, así que el
    tope de verdad era MAX_POR_DIA por worker, y cada deploy lo ponía en cero. El
    conteo en base que quedaba de piso contaba ANIMALES, así que no veía las
    re-revisiones de un mismo animal y no tapaba nada: con el registro abierto, eso
    es la cuenta de OpenAI del refugio vaciada con un script.
    """

    def setUp(self):
        self.service = ModeracionService()
        self.usuario = make_user(email="editor@ejemplo.test")
        self.animal = make_animal(nombre="Willy", tipo="G", cargado_por=self.usuario)
        make_animal_image(animal=self.animal)

    def revisar_editando(self, veces):
        """Simula que alguien edita el mismo animal una y otra vez."""

        for i in range(veces):
            #lo que dispara la re-revisión desde la vista es que cambie algo revisable
            self.animal.nombre = "Willy {}".format(i)
            self.service.revisar_y_guardar(self.animal)

    def test_el_cupo_sobrevive_al_reinicio_del_proceso(self):
        """Vaciar la memoria del proceso no devuelve llamadas pagas.

        Un deploy, un reinicio o simplemente el pedido cayendo en otro worker de
        gunicorn dejaba el contador en cero y el cupo volvía a empezar.
        """

        tope = self.service.get_limite_diario()

        with mock.patch.object(
            ModeracionService, "_preguntar", return_value=visto(["gato"]),
        ) as preguntar:
            self.revisar_editando(tope + 2)

            #esto es un deploy, un reinicio, o el pedido cayendo en otro worker
            cache.clear()
            preguntar.reset_mock()

            self.revisar_editando(3)

        self.assertEqual(
            preguntar.call_count, 0,
            "después de reiniciar el proceso se gastaron {} llamadas pagas de más".format(
                preguntar.call_count,
            ),
        )

    def test_cada_llamada_deja_su_fila(self):
        """Una fila por llamada, con su usuario: es lo que hace que el conteo vea las
        re-revisiones de un mismo animal, que también se pagan."""

        with mock.patch.object(ModeracionService, "_preguntar", return_value=visto(["gato"])):
            self.revisar_editando(2)

        self.assertEqual(RevisionIALlamada.objects.filter(pedido_por=self.usuario).count(), 2)

    def test_el_cupo_cuesta_dos_queries(self):
        """El alta del animal espera la revisión de forma sincrónica y el worker corta
        a los 30s: contar el cupo tiene que ser un count con índice y un insert."""

        with CaptureQueriesContext(connection) as queries:
            self.service.paso_el_limite(self.usuario)
            self.service._contar_llamada(self.usuario)

        self.assertEqual(len(queries), 2, [q["sql"] for q in queries])

    def test_el_conteo_del_cupo_tiene_indice(self):
        """El count corre adentro del POST del alta, que el worker corta a los 30s:
        sin índice por (persona, fecha) es un scan de una tabla que sólo crece."""

        indices = [tuple(campos) for campos in RevisionIALlamada._meta.index_together]

        self.assertIn(("pedido_por", "created_at"), indices)

    def test_si_no_se_puede_anotar_la_llamada_el_animal_se_revisa_igual(self):
        """Contar es lo de menos: la revisión no puede devolverle un error a quien
        está publicando un animal."""

        with mock.patch.object(
            RevisionIALlamada.objects, "create", side_effect=RuntimeError("base caída"),
        ):
            with con_respuesta(visto(["gato"])):
                estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_si_no_se_puede_leer_el_cupo_el_animal_se_revisa_igual(self):

        with mock.patch.object(
            RevisionIALlamada.objects, "filter", side_effect=RuntimeError("base caída"),
        ):
            with con_respuesta(visto(["gato"])):
                estado, _ = self.service.revisar(self.animal)

        self.assertEqual(estado, Animal.REVISION_OK)

    def test_pasarse_del_tope_no_marca_al_animal(self):
        """Un fallo NUESTRO no se reporta como sospecha de ELLOS: quedarse sin cupo
        da 'no se pudo revisar', que no le frena la publicación a nadie."""

        with mock.patch.object(ModeracionService, "_preguntar", return_value=visto(["gato"])):
            self.revisar_editando(self.service.get_limite_diario() + 1)

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.revision_ia_estado, Animal.REVISION_ERROR)
        self.assertFalse(self.animal.necesita_revision_humana())
