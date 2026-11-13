"""Integración con BuenAdoptante (catus/services/buenadoptante.py).

Cada formulario de pre-adopción se registra en BuenAdoptante antes de llegarle al
rescatista; con 1★ o 2★ se frena (lo ve solo el equipo). Si BuenAdoptante no contesta, el
formulario pasa como siempre y el cron enviar_buenadoptante lo manda después, avisando si
la persona resultó mal calificada. Las adopciones concretadas también se mandan, y el
panel le pregunta al rescatista quién adoptó.
"""
import json
from datetime import timedelta
from io import StringIO
from unittest import mock

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from forms_builder.forms.models import FieldEntry, Form

from catus.models import ActividadBuenAdoptante, Animal, EstadoFormulario
from catus.services.buenadoptante import BuenAdoptanteService
from catus.test_login_throttle import fake_memcached
from catus.tests.factories import make_animal, make_estado_formulario, make_field, make_form_entry, make_user

ACTIVO = dict(
    ENV="TEST", SEND_MAIL="sitio@catpuccino.test", HOST="adopciones.catpuccino.test",
    BUENADOPTANTE_ACTIVO=True, BUENADOPTANTE_API_KEY="ba_test_clave", BUENADOPTANTE_API_URL="https://ba.test",
    BUENADOPTANTE_BLOQUEAR_HASTA=2, BUENADOPTANTE_DRY_RUN=False,
)


def respuesta_api(nivel=0, status=200, match="found", flags=None, alerts=None):
    """Lo que contesta POST /api/v1/search en modo exacto (ver /api/v1/docs)."""

    cuerpo = {
        "mode": "exact",
        "match": match,
        "risk": {"worstRating": {"ratingLevel": nivel}, "flags": flags or [], "alerts": alerts or []},
        "saved": {"action": "added_to_profile", "activityId": "act-123"},
        "profile": {"url": "https://ba.test/adopter/p-1", "ratingLevel": nivel},
    }
    respuesta = mock.Mock(status_code=status)
    respuesta.json.return_value = cuerpo if status == 200 else {"error": {"code": "algo"}}
    return respuesta


class FormularioDePreadopcion:
    """Arma el formulario público de gatos con los campos que lee la integración."""

    def armar(self):
        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.gato = make_animal(nombre="Michi", tipo="G", sexo="H", edad="2 años", cargado_por=self.rescatista)
        form = Form.objects.create(title="Pre adopción", slug="formulario-de-pre-adopcion", response="Recibido, gracias")
        self.campos = {
            "animal": make_field(form, "Gato a adoptar"),
            "nombre": make_field(form, "Nombre y Apellido"),
            "email": make_field(form, "Email"),
            "celular": make_field(form, "Celular"),
            "instagram": make_field(form, "Instagram"),
            "motivo": make_field(form, "1. ¿Por qué motivo querés adoptar un gato?", field_type=2),
        }
        self.form = form

    def enviar(self, instagram="https://www.instagram.com/ana.gomez/", nombre="Ana Gómez"):
        post = {
            self.campos["animal"].slug: str(self.gato.id),
            self.campos["nombre"].slug: nombre,
            self.campos["email"].slug: "ana@ejemplo.test",
            self.campos["celular"].slug: "11 5555-1234",
            self.campos["instagram"].slug: instagram,
            self.campos["motivo"].slug: "Porque me encantan los gatos",
        }
        return self.client.post("/pre-adopcion/?id={}".format(self.gato.id), post, HTTP_X_FORWARDED_FOR="190.2.3.4")


@override_settings(**ACTIVO)
class EnvioDelFormularioTest(FormularioDePreadopcion, TestCase):

    def setUp(self):
        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.armar()

    def enviar_con(self, respuesta=None, error=None):

        with mock.patch("catus.services.buenadoptante.requests.post", return_value=respuesta, side_effect=error) as post, \
                mock.patch("catus.views.adoption.send_html_email") as mails:
            response = self.client_post()
        return response, post, mails

    def client_post(self):
        return self.enviar()

    def destinatarios(self, mails):
        return [llamada[0][3] for llamada in mails.call_args_list]

    def test_un_adoptante_peligroso_no_le_llega_al_rescatista(self):

        response, _, mails = self.enviar_con(respuesta_api(nivel=1))

        estado = EstadoFormulario.objects.get()
        self.assertEqual(estado.estado, "B")
        pagina = response.content.decode()
        self.assertIn("No pudimos recibir tu formulario", pagina)
        self.assertNotIn("BuenAdoptante", pagina, "el mensaje a la persona no nombra a BuenAdoptante")
        self.assertEqual(self.destinatarios(mails), [["sitio@catpuccino.test"]], "solo el equipo se entera")

        actividad = ActividadBuenAdoptante.objects.get()
        self.assertTrue(actividad.bloqueo)
        self.assertEqual(actividad.nivel, 1)

    def test_un_adoptante_malo_tambien_se_frena(self):

        self.enviar_con(respuesta_api(nivel=2))

        self.assertEqual(EstadoFormulario.objects.get().estado, "B")

    def test_con_calificacion_regular_le_llega_al_rescatista(self):

        _, _, mails = self.enviar_con(respuesta_api(nivel=3))

        estado = EstadoFormulario.objects.get()
        self.assertEqual(estado.estado, "N")
        self.assertIn("rescatista@catpuccino.test", [d for lista in self.destinatarios(mails) for d in lista])
        actividad = ActividadBuenAdoptante.objects.get()
        self.assertEqual((actividad.estado, actividad.nivel, actividad.bloqueo), ("OK", 3, False))
        self.assertEqual(actividad.perfil_url, "https://ba.test/adopter/p-1")

    def test_sin_calificar_pasa(self):

        self.enviar_con(respuesta_api(nivel=0, match="not_found"))

        self.assertEqual(EstadoFormulario.objects.get().estado, "N")

    def test_si_buenadoptante_no_contesta_el_formulario_pasa_y_queda_pendiente(self):

        response, _, mails = self.enviar_con(error=requests.Timeout())

        self.assertEqual(EstadoFormulario.objects.get().estado, "N")
        self.assertIn("Recibido, gracias", response.content.decode())
        self.assertTrue(mails.called, "el rescatista tiene que recibir el formulario igual")
        actividad = ActividadBuenAdoptante.objects.get()
        self.assertEqual((actividad.estado, actividad.intentos), ("P", 1))

    def test_buenadoptante_caido_no_frena_aunque_conteste_un_error(self):

        for status in (500, 503, 429, 401):
            EstadoFormulario.objects.all().delete()
            ActividadBuenAdoptante.objects.all().delete()
            self.enviar_con(respuesta_api(status=status))
            self.assertEqual(EstadoFormulario.objects.get().estado, "N", status)
            self.assertEqual(ActividadBuenAdoptante.objects.get().estado, "P", status)

    def test_lo_que_se_manda(self):

        _, post, _ = self.enviar_con(respuesta_api(nivel=4))

        llamada = post.call_args
        self.assertEqual(llamada[0][0], "https://ba.test/api/v1/search")
        self.assertEqual(llamada[1]["headers"]["Authorization"], "Bearer ba_test_clave")
        self.assertTrue(llamada[1]["headers"]["User-Agent"].startswith("CatpuccinoAdopciones/"),
                        "su filtro anti-bots frena a los clientes sin nombre propio (403 1010)")
        self.assertTrue(llamada[1]["timeout"], "sin timeout el formulario podría quedar colgado")
        cuerpo = llamada[1]["json"]
        estado = EstadoFormulario.objects.get()

        self.assertEqual(cuerpo["mode"], "exact")
        self.assertEqual(cuerpo["person"]["fullName"], "Ana Gómez")
        self.assertEqual(cuerpo["person"]["email"], "ana@ejemplo.test")
        self.assertEqual(cuerpo["person"]["phone"], "11 5555-1234")
        self.assertEqual(cuerpo["person"]["socials"], [{"platform": "instagram", "handle": "ana.gomez"}])
        self.assertEqual(cuerpo["activity"]["activityType"], "adoption_request")
        self.assertEqual(cuerpo["activity"]["externalId"], "catpuccino-solicitud-{}".format(estado.hash))
        self.assertEqual(cuerpo["activity"]["species"], "cat")
        self.assertEqual(cuerpo["activity"]["animalName"], "Michi")
        self.assertEqual(cuerpo["activity"]["formContent"]["1. ¿Por qué motivo querés adoptar un gato?"], "Porque me encantan los gatos")

    @override_settings(BUENADOPTANTE_ACTIVO=False)
    def test_apagado_no_llama_a_nadie(self):

        _, post, mails = self.enviar_con(respuesta_api(nivel=1))

        self.assertFalse(post.called)
        self.assertEqual(EstadoFormulario.objects.get().estado, "N")
        self.assertFalse(ActividadBuenAdoptante.objects.exists())

    @override_settings(BUENADOPTANTE_BLOQUEAR_HASTA=0)
    def test_con_el_bloqueo_en_cero_solo_se_registra(self):

        self.enviar_con(respuesta_api(nivel=1))

        self.assertEqual(EstadoFormulario.objects.get().estado, "N")

    def test_el_formulario_avisa_que_se_comparte(self):

        pagina = self.client.get("/pre-adopcion/").content.decode()

        self.assertIn("También se comparten con", pagina)

    def test_sin_nombre_y_apellido_no_se_recibe(self):
        """Con una sola palabra BuenAdoptante rechaza la consulta entera (full_name_required)
        y el formulario pasaba sin revisar: pasaba en 12 de 314 formularios en 90 días."""

        for nombre in ("Lu", "  Ana  ", "ana@ejemplo.test", "Ana 1234"):
            with self.subTest(nombre=nombre), \
                    mock.patch("catus.services.buenadoptante.requests.post") as post, \
                    mock.patch("catus.views.adoption.send_html_email") as mails:
                pagina = self.enviar(nombre=nombre).content.decode()

                self.assertFalse(EstadoFormulario.objects.exists())
                self.assertFalse(post.called)
                self.assertFalse(mails.called)
                self.assertIn("Poné tu nombre y apellido", pagina)

    def test_el_navegador_controla_el_nombre_antes_de_enviar(self):

        pagina = self.client.get("/pre-adopcion/").content.decode()

        self.assertIn('form.elements["{}"]'.format(self.campos["nombre"].slug), pagina)
        self.assertIn("esNombreYApellido(nombre.value)", pagina)


class NombreYApellidoTest(TestCase):

    def test_casos(self):
        from catus.views.adoption import es_nombre_y_apellido

        for nombre, valido in (("Ana Pérez", True), ("María José Pérez", True), ("Ña Ñu", True), ("  ana   pérez ", True),
                               ("Lu", False), ("", False), (None, False), ("Ana 1234", False),
                               ("ana@ejemplo.test", False), ("Ana ana@ejemplo.test", False), ("11 4000-7001", False)):
            with self.subTest(nombre=nombre):
                self.assertEqual(es_nombre_y_apellido(nombre), valido)


class PersonaDelFormularioTest(TestCase):

    def test_redes(self):

        servicio = BuenAdoptanteService()
        casos = {
            "@ana.gomez": "ana.gomez",
            "https://instagram.com/ana_gomez?igsh=xyz": "ana_gomez",
            "ana gomez": "",
            "no tengo": "",
            "No": "",
            "": "",
        }
        for valor, esperado in casos.items():
            self.assertEqual(servicio._handle(valor, "instagram.com"), esperado, valor)

    def test_sin_nada_que_identifique_no_se_manda(self):

        from catus.services.buenadoptante import Rechazo

        rescatista = make_user(email="r@catpuccino.test")
        gato = make_animal(nombre="Michi", cargado_por=rescatista)
        form = Form.objects.create(title="Pre adopción", slug="pre")
        entry = make_form_entry(form)
        FieldEntry.objects.create(entry=entry, field_id=make_field(form, "Nombre y Apellido").id, value="Ana")
        estado = make_estado_formulario(animal=gato, hash="h1", tipo="A", form_entry=entry)
        actividad = ActividadBuenAdoptante(estado_formulario=estado, tipo="adoption_request", external_id="x")

        with self.assertRaises(Rechazo):
            BuenAdoptanteService().cuerpo(actividad)

    def test_las_respuestas_largas_entran_en_el_tope(self):

        contenido = BuenAdoptanteService().contenido({"a": "x" * 2000, "b": "y" * 2000, **{str(i): "z" * 1999 for i in range(40)}})

        self.assertLessEqual(len(json.dumps(contenido).encode()), 45 * 1024)
        self.assertEqual(len(contenido), 42)


@override_settings(**ACTIVO)
class CronTest(TestCase):

    def setUp(self):
        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.gato = make_animal(nombre="Michi", tipo="G", sexo="H", edad="2 años", cargado_por=self.rescatista)
        form = Form.objects.create(title="Pre adopción", slug="pre")
        entry = make_form_entry(form)
        for etiqueta, valor in (("Nombre y Apellido", "Ana Gómez"), ("Email", "ana@ejemplo.test")):
            FieldEntry.objects.create(entry=entry, field_id=make_field(form, etiqueta).id, value=valor)
        self.estado = make_estado_formulario(animal=self.gato, hash="hash-1", tipo="A", form_entry=entry)

    def correr(self, respuesta):

        with mock.patch("catus.services.buenadoptante.requests.post", return_value=respuesta) as post, \
                mock.patch("catus.management.commands.enviar_buenadoptante.send_html_email") as mails:
            call_command("enviar_buenadoptante", stdout=StringIO())
        return post, mails

    def test_si_el_reintento_encuentra_un_mal_adoptante_avisa_y_no_frena(self):

        ActividadBuenAdoptante.objects.create(estado_formulario=self.estado, animal=self.gato, tipo="adoption_request",
                                              external_id="catpuccino-solicitud-hash-1", intentos=1,
                                              ultimo_intento=timezone.now() - timedelta(hours=1))

        _, mails = self.correr(respuesta_api(nivel=1))

        self.estado.refresh_from_db()
        self.assertEqual(self.estado.estado, "N", "el formulario ya había llegado: no se frena")
        self.assertEqual(len(mails.call_args_list), 1)
        self.assertIn("rescatista@catpuccino.test", mails.call_args[0][3])
        actividad = ActividadBuenAdoptante.objects.get()
        self.assertTrue(actividad.avisado)

        _, mails = self.correr(respuesta_api(nivel=1))
        self.assertFalse(mails.called, "se avisa una sola vez")

    def test_manda_la_adopcion_con_el_animal(self):

        self.gato.estado = "A"
        self.gato.fecha_adopcion = timezone.now()
        self.gato.save()
        BuenAdoptanteService().registrar_adopcion(self.estado, self.gato)

        post, _ = self.correr(respuesta_api(nivel=4))

        actividad = post.call_args[1]["json"]["activity"]
        self.assertEqual(actividad["activityType"], "adoption")
        self.assertEqual(actividad["externalId"], "catpuccino-adopcion-hash-1-{}".format(self.gato.id))
        self.assertEqual((actividad["species"], actividad["sex"], actividad["age"]), ("cat", "female", "2 años"))
        self.assertNotIn("formContent", actividad)
        self.assertEqual(ActividadBuenAdoptante.objects.get().estado, "OK")

    def test_espera_entre_reintentos(self):

        ActividadBuenAdoptante.objects.create(estado_formulario=self.estado, tipo="adoption_request",
                                              external_id="catpuccino-solicitud-hash-1", intentos=2,
                                              ultimo_intento=timezone.now() - timedelta(minutes=5))

        post, _ = self.correr(respuesta_api(nivel=4))

        self.assertFalse(post.called, "a los 5 minutos del segundo intento todavía no toca")

    def test_un_rechazo_no_se_reintenta(self):

        ActividadBuenAdoptante.objects.create(estado_formulario=self.estado, tipo="adoption_request",
                                              external_id="catpuccino-solicitud-hash-1")

        self.correr(respuesta_api(status=422))

        self.assertEqual(ActividadBuenAdoptante.objects.get().estado, "E")


@override_settings(**ACTIVO)
class QuienLoAdoptoTest(TestCase):

    def setUp(self):
        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.otro = make_user(email="otro@catpuccino.test")
        self.gato = make_animal(nombre="Michi", tipo="G", estado="R", cargado_por=self.rescatista)
        self.hermano = make_animal(nombre="Tom", tipo="G", estado="D", cargado_por=self.rescatista)
        self.ajeno = make_animal(nombre="Ajeno", tipo="G", estado="D", cargado_por=self.otro)
        hace = timezone.now() - timedelta(days=10)
        self.ana = make_estado_formulario(animal=self.gato, hash="ana", tipo="A", persona_nombre="Ana Gómez", fecha_ingreso=hace)
        self.beto = make_estado_formulario(animal=self.hermano, hash="beto", tipo="A", persona_nombre="Beto Ruiz", fecha_ingreso=hace)
        self.ajena = make_estado_formulario(animal=self.ajeno, hash="ajena", tipo="A", persona_nombre="Ana Ajena", fecha_ingreso=hace)
        self.frenado = make_estado_formulario(animal=self.gato, hash="frenado", tipo="A", persona_nombre="Frenado", estado="B", fecha_ingreso=hace)
        self.client.force_login(self.rescatista)

    def marcar(self, animal, formulario_id=""):
        return self.client.post("/animal/marcaradoptado/", {"animal_id": animal.id, "estado_formulario_id": formulario_id})

    def test_marcar_adoptado_eligiendo_a_la_persona(self):

        self.marcar(self.gato, self.ana.id)

        self.gato.refresh_from_db()
        self.ana.refresh_from_db()
        self.assertEqual((self.gato.estado, self.gato.estado_formulario_id, self.gato.adoptante), ("A", self.ana.id, "Ana Gómez"))
        self.assertEqual(self.ana.estado, "A")
        actividad = ActividadBuenAdoptante.objects.get()
        self.assertEqual((actividad.tipo, actividad.animal_id, actividad.estado), ("adoption", self.gato.id, "P"))

    def test_puede_ser_alguien_que_pidio_otro_animal_del_mismo_rescatista(self):

        self.marcar(self.gato, self.beto.id)

        self.gato.refresh_from_db()
        self.assertEqual(self.gato.estado_formulario_id, self.beto.id)

    def test_no_se_puede_vincular_el_formulario_de_otro_rescatista(self):

        self.marcar(self.gato, self.ajena.id)

        self.gato.refresh_from_db()
        self.assertEqual(self.gato.estado, "A")
        self.assertIsNone(self.gato.estado_formulario_id)
        self.assertFalse(ActividadBuenAdoptante.objects.exists())

    def test_sin_elegir_a_nadie_queda_adoptado_como_antes(self):

        self.marcar(self.gato)

        self.gato.refresh_from_db()
        self.assertEqual(self.gato.estado, "A")
        self.assertFalse(ActividadBuenAdoptante.objects.exists())

    def test_decir_quien_adopto_no_pisa_la_fecha_de_adopcion(self):

        antes = timezone.now() - timedelta(days=20)
        Animal.objects.filter(id=self.gato.id).update(estado="A", fecha_adopcion=antes)

        self.marcar(self.gato, self.ana.id)

        self.gato.refresh_from_db()
        self.assertEqual(self.gato.fecha_adopcion, antes)

    def test_buscar_entre_sus_formularios(self):

        respuesta = json.loads(self.client.get("/animal/buscarformularios/", {"animal_id": self.gato.id, "q": "ana"}).content)

        self.assertEqual([r["id"] for r in respuesta["resultados"]], [self.ana.id], "ni el de otro rescatista ni el frenado")

    def test_no_se_puede_buscar_con_el_animal_de_otro(self):

        respuesta = json.loads(self.client.get("/animal/buscarformularios/", {"animal_id": self.ajeno.id, "q": "ana"}).content)

        self.assertEqual(respuesta["resultados"], [])

    def test_el_panel_pregunta_por_los_que_tienen_formularios(self):

        contexto = self.client.get("/accounts/profile/").context

        self.assertIn(self.gato, contexto["animales_por_confirmar"], "reservado y con formularios")
        self.assertIn(self.hermano, contexto["animales_por_confirmar"], "con formularios de hace más de una semana")
        candidatos = contexto["candidatos_json"][str(self.gato.id)]
        self.assertEqual([c["id"] for c in candidatos], [self.ana.id], "el frenado no es candidato")

    def test_el_panel_pregunta_quien_adopto_a_los_ya_adoptados(self):

        Animal.objects.filter(id=self.gato.id).update(estado="A", fecha_adopcion=timezone.now() - timedelta(days=3))

        response = self.client.get("/accounts/profile/")

        self.assertEqual([a.id for a in response.context["adoptados_sin_adoptante"]], [self.gato.id])
        self.assertIn("fue adoptado. ¿Quién lo adoptó?", response.content.decode())

    def test_todavia_no_posterga_la_pregunta(self):

        self.client.post("/animal/posponerpreguntaadopcion/", {"animal_id": self.gato.id})

        self.gato.refresh_from_db()
        self.assertGreater(self.gato.pregunta_adopcion_hasta, timezone.now() + timedelta(days=13))
        contexto = self.client.get("/accounts/profile/").context
        self.assertNotIn(self.gato, contexto["animales_por_confirmar"])

    def test_cerrar_la_tarjeta_posterga_todas_sus_preguntas(self):
        """La × de la tarjeta manda todos sus animales juntos (ocultarPreguntas). Con un id
        ajeno metido a mano, ese no se toca."""

        self.assertIn('onclick="ocultarPreguntas()"', self.client.get("/accounts/profile/").content.decode())

        self.client.post("/animal/posponerpreguntaadopcion/",
                         {"animal_ids": [self.gato.id, self.hermano.id, self.ajeno.id], "para_siempre": "0"})

        for animal in (self.gato, self.hermano, self.ajeno):
            animal.refresh_from_db()
        en_dos_semanas = timezone.now() + timedelta(days=13)
        self.assertGreater(self.gato.pregunta_adopcion_hasta, en_dos_semanas)
        self.assertGreater(self.hermano.pregunta_adopcion_hasta, en_dos_semanas)
        self.assertIsNone(self.ajeno.pregunta_adopcion_hasta)
        respuesta = self.client.get("/accounts/profile/")
        self.assertEqual(respuesta.context["animales_por_confirmar"], [])
        self.assertNotIn('id="pregunta-adopcion"', respuesta.content.decode())

    def test_el_rescatista_no_ve_los_frenados(self):

        contexto = self.client.get("/accounts/profile/").context

        self.assertNotIn(self.frenado, list(contexto["estado_forms"]))
        self.assertEqual(self.client.get("/formularios/frenado/").status_code, 403)

    def test_el_equipo_si_ve_los_frenados(self):

        equipo = make_user(email="equipo@catpuccino.test", is_superuser=True, is_staff=True)
        self.client.force_login(equipo)

        self.assertEqual(self.client.get("/formularios/frenado/").status_code, 200)

    def test_marcar_el_formulario_adoptado_registra_la_adopcion(self):

        respuesta = self.client.post("/formularios/ana/", {"estado": "A", "gato": self.gato.id})

        self.assertEqual(json.loads(respuesta.content)["status"], "ok")
        self.gato.refresh_from_db()
        self.assertEqual(self.gato.estado_formulario_id, self.ana.id)
        self.assertTrue(ActividadBuenAdoptante.objects.filter(tipo="adoption", estado_formulario=self.ana).exists())
