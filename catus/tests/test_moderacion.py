"""Tests de la revisión automática de publicaciones.

Dos reglas que no se pueden romper:
  1. Es una ayuda para el equipo. Pase lo que pase (API caída, sin crédito, respuesta
     rara) nunca puede impedir que se guarde ni que se publique un animal.
  2. Marcar de más hace daño: si el filtro se equivoca, alguien que rescató un animal
     no lo puede publicar. Ante la duda, aprueba.
"""
import json
from unittest import mock

from django.test import TestCase, override_settings

from catus.models import Animal
from catus.services.moderacion import ModeracionService
from catus.tests.factories import make_animal, make_animal_image, make_user


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
        self.rescatista = make_user(email="rescatista@catpuccino.test", automatic_approve=True)

    def guardar_animal(self, contenido_ia):
        """Reproduce la decisión de auto-aprobación que toma EditView al guardar."""

        animal = make_animal(nombre="Willy", cargado_por=self.rescatista, aprobado=False)
        make_animal_image(animal=animal)

        with con_respuesta(contenido_ia):
            revision = ModeracionService().revisar_y_guardar(animal)

        auto_aprobar = (
            animal.cargado_por is not None
            and animal.cargado_por.automatic_approve
            and revision != Animal.REVISION_REVISAR
        )

        if auto_aprobar:
            animal.aprobado = True
            animal.save()

        animal.refresh_from_db()
        return animal

    def test_una_publicacion_valida_se_auto_aprueba(self):

        self.assertTrue(self.guardar_animal(visto(["gato"])).aprobado)

    def test_una_sospechosa_queda_esperando_revision(self):

        animal = self.guardar_animal(visto([], "No se ve ningún animal."))

        self.assertFalse(animal.aprobado)
        self.assertTrue(animal.necesita_revision_humana())

    def test_si_la_ia_falla_se_auto_aprueba_igual(self):
        """Una caída de OpenAI no puede frenar el flujo normal del rescatista."""

        animal = make_animal(nombre="Willy", cargado_por=self.rescatista, aprobado=False)
        make_animal_image(animal=animal)

        with con_error():
            revision = ModeracionService().revisar_y_guardar(animal)

        self.assertEqual(revision, Animal.REVISION_ERROR)
        self.assertNotEqual(revision, Animal.REVISION_REVISAR)
