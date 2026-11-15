"""Postularse a otro animal con las respuestas de un formulario ya enviado.

Pedido del equipo (2026-11-15): quien completó el formulario de pre-adopción puede mandarlo
también para otro animal sin escribirlo de nuevo. No hay cuentas de adoptante: se entra con un
link privado (services/postulacion.py). Lo que estos tests cuidan:

- el link no se puede adivinar ni alterar, vence, y no es el hash que conocen el rescatista y
  el equipo;
- la página no entrega nada de lo que la persona contestó;
- no se puede postular dos veces al mismo animal, ni a uno de otra especie, ni a más de
  MAX_POR_DIA por día;
- el formulario nuevo le llega al rescatista como cualquier otro, y dice que es una copia.
"""
from datetime import timedelta
from unittest import mock

from django.core import signing
from django.test import TestCase, override_settings
from django.utils import timezone
from forms_builder.forms.models import FieldEntry, Form

from catus.models import EstadoFormulario
from catus.services import postulacion
from catus.test_login_throttle import fake_memcached
from catus.tests.factories import make_animal, make_estado_formulario, make_field, make_form_entry, make_user
from catus.tests.test_buenadoptante import ACTIVO, respuesta_api

VISITANTE = "190.2.3.4"


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test", HOST="adopciones.test")
class PostulacionBase(TestCase):

    def setUp(self):
        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)

        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.otra_rescatista = make_user(email="otra@catpuccino.test")
        self.michi = make_animal(nombre="Michi", tipo="G", cargado_por=self.rescatista)
        self.luna = make_animal(nombre="Luna", tipo="G", cargado_por=self.otra_rescatista)
        self.tom = make_animal(nombre="Tom", tipo="G", cargado_por=self.otra_rescatista)
        self.firulais = make_animal(nombre="Firulais", tipo="P", cargado_por=self.rescatista)

        #como en forms.sql: la primera respuesta es el id del animal elegido
        self.form = Form.objects.create(title="Pre adopción", slug="formulario-de-pre-adopcion", response="Recibido, gracias")
        self.campos = {
            "animal": make_field(self.form, "Nombre del gato a adoptar"),
            "nombre": make_field(self.form, "Nombre y Apellido"),
            "email": make_field(self.form, "Email"),
            "celular": make_field(self.form, "Celular"),
            "motivo": make_field(self.form, "1. ¿Por qué querés adoptar?"),
        }
        self.original = self.formulario_enviado(self.michi)

    def formulario_enviado(self, animal, hash="hash-original"):

        entry = make_form_entry(self.form)
        for clave, valor in (("animal", str(animal.id)), ("nombre", "Ana Gómez"), ("email", "ana@ejemplo.test"),
                             ("celular", "11 5555-4444"), ("motivo", "Porque Michi me robó el corazón")):
            FieldEntry.objects.create(entry=entry, field_id=self.campos[clave].id, value=valor)

        return make_estado_formulario(animal, form_entry=entry, hash=hash, tipo="A", persona_nombre="Ana Gómez")

    def url(self, estado=None):
        return postulacion.link(estado or self.original)


class TokenTest(PostulacionBase):

    def test_el_link_lleva_al_formulario_original(self):
        self.assertEqual(postulacion.formulario_del_token(postulacion.token(self.original)), self.original)

    def test_no_es_el_hash_que_conocen_el_rescatista_y_el_equipo(self):
        self.assertNotIn(self.original.hash, self.url())
        self.assertIsNone(postulacion.formulario_del_token(self.original.hash))

    def test_un_link_alterado_o_inventado_no_sirve(self):
        token = postulacion.token(self.original)

        for texto in (token[:-2] + "xx", signing.dumps(self.original.id, salt="otra-cosa"), str(self.original.id), "", None):
            with self.subTest(texto=texto):
                self.assertIsNone(postulacion.formulario_del_token(texto))

    def test_vence(self):
        token = postulacion.token(self.original)

        with mock.patch.object(postulacion, "VIGENCIA_DIAS", -1):
            self.assertIsNone(postulacion.formulario_del_token(token))

    def test_el_link_de_una_copia_lleva_al_original(self):
        copia = postulacion.postular(self.original, self.luna.id)

        self.assertEqual(postulacion.formulario_del_token(postulacion.token(copia)), self.original)

    def test_un_formulario_de_transito_o_frenado_no_tiene_link(self):
        transito = make_estado_formulario(None, form_entry=make_form_entry(self.form), hash="t", tipo="T")
        self.assertIsNone(postulacion.link(transito))
        self.assertIsNone(postulacion.formulario_del_token(signing.dumps(transito.id, salt=postulacion.SAL)))

        token = postulacion.token(self.original)
        EstadoFormulario.objects.filter(id=self.original.id).update(estado="B")
        self.original.refresh_from_db()
        self.assertIsNone(postulacion.link(self.original))
        self.assertIsNone(postulacion.formulario_del_token(token))

    def test_si_frenaron_una_copia_el_link_deja_de_servir(self):
        """Si no, cada intento nuevo le mandaría otro aviso de "formulario frenado" al equipo."""

        copia = postulacion.postular(self.original, self.luna.id)
        EstadoFormulario.objects.filter(id=copia.id).update(estado="B")

        self.assertIsNone(postulacion.formulario_del_token(postulacion.token(self.original)))


class PostularTest(PostulacionBase):

    def test_crea_un_formulario_nuevo_con_las_mismas_respuestas(self):
        copia = postulacion.postular(self.original, self.luna.id)

        self.assertEqual(copia.gato, self.luna)
        self.assertEqual(copia.copiado_de, self.original)
        self.assertEqual(copia.tipo, "A")
        self.assertEqual(copia.estado, "N")
        self.assertEqual(copia.persona_nombre, "Ana Gómez")
        self.assertNotEqual(copia.hash, self.original.hash)
        self.assertNotEqual(copia.form_entry_id, self.original.form_entry_id)

        respuestas = list(copia.form_entry.fields.order_by("id").values_list("field_id", "value"))
        originales = list(self.original.form_entry.fields.order_by("id").values_list("field_id", "value"))
        #la primera respuesta es el animal: es lo único que cambia
        self.assertEqual(respuestas[0], (self.campos["animal"].id, str(self.luna.id)))
        self.assertEqual(respuestas[1:], originales[1:])

    def test_no_toca_el_formulario_original(self):
        postulacion.postular(self.original, self.luna.id)

        self.original.refresh_from_db()
        self.assertEqual(self.original.gato, self.michi)
        self.assertEqual(self.original.form_entry.fields.order_by("id").first().value, str(self.michi.id))

    def test_las_copias_apuntan_siempre_al_original(self):
        copia = postulacion.postular(self.original, self.luna.id)
        otra = postulacion.postular(postulacion.original_de(copia), self.tom.id)

        self.assertEqual(otra.copiado_de, self.original)

    def test_no_dos_veces_al_mismo_animal(self):
        postulacion.postular(self.original, self.luna.id)

        for animal in (self.luna, self.michi):
            with self.subTest(animal=animal.nombre), self.assertRaises(postulacion.NoSePuede):
                postulacion.postular(self.original, animal.id)

        self.assertEqual(EstadoFormulario.objects.count(), 2)

    def test_solo_a_animales_en_adopcion_de_la_misma_especie(self):
        sin_aprobar = make_animal(nombre="Nuevo", tipo="G", aprobado=False)
        adoptado = make_animal(nombre="Feliz", tipo="G", estado="A")

        for animal_id in (self.firulais.id, sin_aprobar.id, adoptado.id, 999999, "", None, "1 OR 1=1"):
            with self.subTest(animal_id=animal_id), self.assertRaises(postulacion.NoSePuede):
                postulacion.postular(self.original, animal_id)

        self.assertEqual(EstadoFormulario.objects.count(), 1)

    def test_hay_un_maximo_por_dia(self):
        otros = [make_animal(nombre="Gato {}".format(n), tipo="G") for n in range(postulacion.MAX_POR_DIA + 1)]

        for animal in otros[:postulacion.MAX_POR_DIA]:
            postulacion.postular(self.original, animal.id)

        self.assertEqual(postulacion.cupo(self.original), 0)
        with self.assertRaises(postulacion.NoSePuede):
            postulacion.postular(self.original, otros[-1].id)

        #al otro día vuelve a poder
        EstadoFormulario.objects.filter(copiado_de=self.original).update(fecha_ingreso=timezone.now() - timedelta(hours=25))
        self.assertEqual(postulacion.cupo(self.original), postulacion.MAX_POR_DIA)
        postulacion.postular(self.original, otros[-1].id)

    def test_la_lista_no_ofrece_los_animales_a_los_que_ya_se_postulo(self):
        postulacion.postular(self.original, self.luna.id)

        self.assertEqual(list(postulacion.animales_disponibles(self.original)), [self.tom])


class PaginaTest(PostulacionBase):

    def postular(self, animal, **extra):
        with mock.patch("catus.views.adoption.send_html_email") as mails:
            respuesta = self.client.post(self.url(), {"animal_id": animal.id}, HTTP_X_FORWARDED_FOR=VISITANTE, **extra)
        return respuesta, mails

    def test_muestra_a_quien_se_postulo_y_a_quien_puede_postularse(self):
        pagina = self.client.get(self.url()).content.decode()

        self.assertIn("Hola, Ana.", pagina)
        self.assertIn("Luna", pagina)
        self.assertIn("Tom", pagina)
        self.assertIn("?id={}".format(self.luna.id), pagina)
        #a Michi ya se postuló, y Firulais es un perro
        self.assertNotIn("?id={}".format(self.michi.id), pagina)
        self.assertNotIn("Firulais", pagina)

    def test_no_entrega_nada_de_lo_que_la_persona_contesto(self):
        """El link puede reenviarse o filtrarse: no tiene que dar el mail, el celular ni las
        respuestas de nadie."""

        for url in (self.url(), self.url() + "?id={}".format(self.luna.id)):
            with self.subTest(url=url):
                pagina = self.client.get(url).content.decode()

                for dato in ("ana@ejemplo.test", "5555", "Gómez", "robó el corazón", self.original.hash):
                    self.assertNotIn(dato, pagina)

    def test_elegir_un_animal_pide_confirmar_antes_de_mandar_nada(self):
        respuesta = self.client.get(self.url() + "?id={}".format(self.luna.id))
        pagina = respuesta.content.decode()

        self.assertIn("¿Te postulás a Luna?", pagina)
        self.assertIn('name="animal_id" value="{}"'.format(self.luna.id), pagina)
        self.assertEqual(EstadoFormulario.objects.count(), 1)

    def test_un_link_que_no_sirve_no_muestra_nada(self):
        respuesta = self.client.get("/postularme/cualquier-cosa/")

        self.assertEqual(respuesta.status_code, 404)
        self.assertIn("Este link ya no sirve", respuesta.content.decode())
        self.assertNotIn("Luna", respuesta.content.decode())

    def test_postularse_le_manda_el_formulario_a_quien_publico_al_otro_animal(self):
        respuesta, mails = self.postular(self.luna)

        #de vuelta a su página (el token lleva la hora: no es el mismo texto de un pedido a otro)
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta["Location"].endswith("/?ok={}".format(self.luna.id)))
        self.assertEqual(postulacion.formulario_del_token(respuesta["Location"].split("/")[2]), self.original)
        copia = EstadoFormulario.objects.get(copiado_de=self.original)
        self.assertEqual(copia.gato, self.luna)

        #al equipo y a la rescatista de Luna (no al de Michi), y la confirmación a la persona
        al_rescatista, a_la_persona = [llamada.args for llamada in mails.call_args_list]
        self.assertEqual(sorted(al_rescatista[3]), ["catpuccino.ok@gmail.com", "otra@catpuccino.test"])
        self.assertIn("Luna", al_rescatista[0])
        self.assertIn("/formularios/{}/".format(copia.hash), al_rescatista[1])
        self.assertIn("Usó las respuestas de un formulario anterior", al_rescatista[1])
        self.assertIn("robó el corazón", al_rescatista[1])
        self.assertEqual(a_la_persona[3], "ana@ejemplo.test")
        self.assertIn("/postularme/", a_la_persona[1])

    def test_despues_de_postularse_lo_dice_y_ya_no_lo_ofrece(self):
        respuesta, _ = self.postular(self.luna)
        pagina = self.client.get(respuesta["Location"]).content.decode()

        self.assertIn("tu formulario para <b>Luna</b> ya le llegó", pagina)
        self.assertNotIn("?id={}".format(self.luna.id), pagina)
        self.assertIn("Hoy te podés postular a {} más".format(postulacion.MAX_POR_DIA - 1), pagina)

    def test_no_se_puede_postular_a_cualquier_animal_con_un_post_armado_a_mano(self):
        for animal in (self.michi, self.firulais):
            with self.subTest(animal=animal.nombre):
                respuesta, mails = self.postular(animal)

                self.assertEqual(respuesta.status_code, 200)
                self.assertIn("ya no está en adopción", respuesta.content.decode())
                mails.assert_not_called()

        self.assertEqual(EstadoFormulario.objects.count(), 1)

    def test_con_un_link_que_no_sirve_no_se_postula_a_nadie(self):
        with mock.patch("catus.views.adoption.send_html_email") as mails:
            respuesta = self.client.post("/postularme/inventado/", {"animal_id": self.luna.id})

        self.assertEqual(respuesta.status_code, 404)
        mails.assert_not_called()
        self.assertEqual(EstadoFormulario.objects.count(), 1)

    def test_el_tope_del_dia_se_ve_en_la_pagina(self):
        otros = [make_animal(nombre="Gato {}".format(n), tipo="G") for n in range(postulacion.MAX_POR_DIA)]
        for animal in otros:
            postulacion.postular(self.original, animal.id)

        pagina = self.client.get(self.url()).content.decode()
        self.assertIn("Por hoy llegaste al máximo", pagina)
        self.assertNotIn("?id={}".format(self.luna.id), pagina)

        respuesta, mails = self.postular(self.luna)
        self.assertIn("Por hoy ya te postulaste", respuesta.content.decode())
        mails.assert_not_called()

    def test_el_rescatista_ve_en_el_formulario_que_es_una_copia(self):
        copia = postulacion.postular(self.original, self.luna.id)
        self.client.force_login(self.otra_rescatista)

        pagina = self.client.get("/formularios/{}/".format(copia.hash)).content.decode()

        self.assertIn("Usó las respuestas de un formulario anterior", pagina)
        #y en el original no dice nada
        self.client.force_login(self.rescatista)
        self.assertNotIn("Usó las respuestas", self.client.get("/formularios/{}/".format(self.original.hash)).content.decode())


@override_settings(**ACTIVO)
class ConBuenAdoptanteTest(PostulacionBase):
    """Cada postulación pasa por BuenAdoptante igual que un formulario recién completado: si
    no, postularse a otro animal sería la forma de saltearse el control."""

    def postular_con(self, respuesta, animal=None):
        with mock.patch("catus.services.buenadoptante.requests.post", return_value=respuesta) as consulta, \
                mock.patch("catus.views.adoption.send_html_email") as mails:
            pagina = self.client.post(self.url(), {"animal_id": (animal or self.luna).id}, HTTP_X_FORWARDED_FOR=VISITANTE)
        return pagina, consulta, [llamada.args[3] for llamada in mails.call_args_list]

    def test_la_postulacion_se_consulta_y_le_llega_al_rescatista(self):
        pagina, consulta, destinatarios = self.postular_con(respuesta_api(nivel=5))

        self.assertEqual(pagina.status_code, 302)
        consulta.assert_called_once()
        self.assertEqual(EstadoFormulario.objects.get(copiado_de=self.original).estado, "N")
        self.assertTrue(any("otra@catpuccino.test" in d for d in destinatarios))

    def test_si_buenadoptante_la_frena_no_le_llega_al_rescatista_y_el_link_deja_de_servir(self):
        pagina, _, destinatarios = self.postular_con(respuesta_api(nivel=1))

        self.assertEqual(EstadoFormulario.objects.get(copiado_de=self.original).estado, "B")
        self.assertFalse(any("otra@catpuccino.test" in d for d in destinatarios))
        self.assertNotIn("ana@ejemplo.test", destinatarios)
        #no dice por qué: la misma página que un link vencido
        self.assertEqual(pagina.status_code, 404)
        self.assertIn("Este link ya no sirve", pagina.content.decode())

        #y no se puede seguir probando con otros animales
        pagina, consulta, destinatarios = self.postular_con(respuesta_api(nivel=1), animal=self.tom)
        self.assertEqual(pagina.status_code, 404)
        consulta.assert_not_called()
        self.assertEqual(destinatarios, [])
        self.assertEqual(EstadoFormulario.objects.filter(copiado_de=self.original).count(), 1)


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test", HOST="adopciones.test")
class LinkAlEnviarElFormularioTest(TestCase):
    """De dónde saca la persona su link: de la página de "formulario enviado" y del mail."""

    def setUp(self):
        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)

        self.michi = make_animal(nombre="Michi", tipo="G", cargado_por=make_user(email="rescatista@catpuccino.test"))
        form = Form.objects.create(title="Pre adopción", slug="formulario-de-pre-adopcion", response="Recibido, gracias")
        self.campos = {
            "animal": make_field(form, "Nombre del gato a adoptar"),
            "nombre": make_field(form, "Nombre y Apellido"),
            "email": make_field(form, "Email"),
        }

    def enviar(self, **extra):
        post = {
            self.campos["animal"].slug: str(self.michi.id),
            self.campos["nombre"].slug: "Ana Gómez",
            self.campos["email"].slug: "ana@ejemplo.test",
        }
        post.update(extra)
        with mock.patch("catus.views.adoption.send_html_email") as mails:
            respuesta = self.client.post("/pre-adopcion/?id={}".format(self.michi.id), post, HTTP_X_FORWARDED_FOR=VISITANTE)
        return respuesta.content.decode(), mails

    def test_la_pagina_de_enviado_y_el_mail_traen_el_link(self):
        pagina, mails = self.enviar()

        estado = EstadoFormulario.objects.get()
        self.assertEqual(postulacion.formulario_del_token(pagina.split("/postularme/")[1].split("/")[0]), estado)
        self.assertIn("Postularme a otro animal", pagina)
        #queda guardado en el navegador, después de borrar las respuestas
        self.assertLess(pagina.index("clearForm();"), pagina.index('localStorage.setItem("catpuccino-postularme-gato"'))

        confirmacion = mails.call_args_list[-1].args
        self.assertEqual(confirmacion[3], "ana@ejemplo.test")
        self.assertIn("https://adopciones.test/postularme/", confirmacion[1])

    def test_un_envio_que_no_se_guarda_no_trae_link(self):
        from catus.views import adoption

        pagina, _ = self.enviar(**{adoption.HONEYPOT_FIELD: "https://spam.example"})

        self.assertEqual(EstadoFormulario.objects.count(), 0)
        self.assertNotIn("/postularme/", pagina)
        self.assertNotIn("catpuccino-postularme-gato\", JSON", pagina)
