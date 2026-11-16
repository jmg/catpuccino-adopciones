"""El mail "¿Siguen en adopción?" al rescatista cuando el cron le expira animales, y la
página de sus botones (services/expiracion.py, views/expirados.py).

La pregunta estaba solo en el panel: la primera semana expiraron 254 animales, entraron 8
personas y se republicaron unos 6. Lo que estos tests cuidan:

- un mail por rescatista con los que expiraron en esa corrida, y nunca dos por la misma
  expiración (tampoco desde el lote de los ya expirados);
- que falle el mail no deshace ni frena la expiración, y el log no lleva el mail;
- los botones andan sin login, pero el GET no cambia nada (los escáneres de links de los
  correos abren cada link) y el link deja de servir si venció, si lo alteraron o si el
  animal ya cambió;
- la página no muestra nada de los candidatos.
"""
import re
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail, signing
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from catus.models import Animal
from catus.services import estados, expiracion
from catus.tests.factories import make_animal, make_estado_formulario, make_user


def hace(dias):
    return timezone.now() - timedelta(days=dias)


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test", SSL_HOST="https://adopciones.test",
                   AVISO_CANDIDATOS_DESDE=None)
class ExpiracionBase(TestCase):

    def setUp(self):
        self.rescatista = make_user(email="rescatista@catpuccino.test")

    def viejo(self, nombre="Willy", **kwargs):
        """Publicado hace más de un mes: la próxima corrida lo expira."""

        kwargs.setdefault("cargado_por", self.rescatista)
        return make_animal(nombre=nombre, fecha_ingreso=hace(40), **kwargs)

    def expirado(self, nombre="Willy", hace_dias=1, **kwargs):
        """Uno que ya expiró el cron."""

        kwargs.setdefault("cargado_por", self.rescatista)
        return make_animal(nombre=nombre, estado="E", fecha_ingreso=hace(40), expiro_el=hace(hace_dias), **kwargs)

    def correr(self, *args):
        salida = StringIO()
        call_command("expirar_animales", *args, stdout=salida, stderr=StringIO())
        return salida.getvalue()

    def html(self, mensaje):
        return mensaje.alternatives[0][0]

    def links(self, mensaje):
        return re.findall(r'href="https://adopciones\.test(/sigue-en-adopcion/[^"]+)"', self.html(mensaje))


class MailAlExpirarTest(ExpiracionBase):

    def test_un_mail_por_rescatista_con_los_que_expiraron_en_esta_corrida(self):

        otra = make_user(email="otra@catpuccino.test")
        willy, tom = self.viejo("Willy"), self.viejo("Tom")
        de_otra = self.viejo("Luna", cargado_por=otra)
        de_antes = self.expirado("Pelusa", hace_dias=10)

        self.correr()

        self.assertEqual(sorted(d for m in mail.outbox for d in m.to), ["otra@catpuccino.test", "rescatista@catpuccino.test"])
        mensaje = next(m for m in mail.outbox if m.to == ["rescatista@catpuccino.test"])
        self.assertIn("Willy", self.html(mensaje))
        self.assertIn("Tom", self.html(mensaje))
        self.assertNotIn("Luna", self.html(mensaje))
        self.assertNotIn("Pelusa", self.html(mensaje), "los de corridas anteriores no van en este mail")
        #dos botones por animal
        self.assertEqual(len(self.links(mensaje)), 4)

        for animal in (willy, tom, de_otra):
            animal.refresh_from_db()
            self.assertIsNotNone(animal.expiro_avisado_el)
        de_antes.refresh_from_db()
        self.assertIsNone(de_antes.expiro_avisado_el)

    def test_un_solo_animal_lo_nombra_en_el_asunto_sin_saltos_de_linea(self):
        """El nombre lo escribe el rescatista: con un salto de línea Django rechaza el mail."""

        self.viejo("Tom\n<b>Gris</b>")

        self.correr()

        self.assertEqual(mail.outbox[0].subject, "¿Tom <b>Gris</b> sigue en adopción?")
        self.assertIn("Tom\n&lt;b&gt;Gris&lt;/b&gt;", self.html(mail.outbox[0]))
        self.assertNotIn("<b>Gris</b>", self.html(mail.outbox[0]))

    def test_no_a_cuentas_dadas_de_baja_ni_sin_mail(self):

        baja = make_user(email="baja@catpuccino.test", is_active=False)
        sin_mail = make_user(email="", username="sin-mail")
        de_baja = self.viejo("Uno", cargado_por=baja)
        self.viejo("Dos", cargado_por=sin_mail)
        self.viejo("Huérfano", cargado_por=None)

        self.correr()

        self.assertEqual(mail.outbox, [])
        de_baja.refresh_from_db()
        self.assertEqual(de_baja.estado, "E", "igual expira")

    def test_si_el_mail_falla_la_expiracion_queda_y_el_log_no_lleva_el_mail(self):

        willy = self.viejo()

        with mock.patch.object(expiracion, "send_html_email", side_effect=RuntimeError("SendGrid caído")), \
                self.assertLogs("catus.services.expiracion", "WARNING") as logs:
            salida = self.correr()

        willy.refresh_from_db()
        self.assertEqual(willy.estado, "E")
        self.assertIsNone(willy.expiro_avisado_el, "queda para el lote de los ya expirados")
        self.assertIn("1 fallidos", salida)
        self.assertNotIn("rescatista@", "\n".join(logs.output))

    def test_con_muchos_animales_muestra_veinte_y_cuenta_el_resto(self):

        for numero in range(expiracion.MAX_ANIMALES_POR_MAIL + 2):
            self.viejo("Gato {}".format(numero))

        self.correr()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(self.links(mail.outbox[0])), 2 * expiracion.MAX_ANIMALES_POR_MAIL)
        self.assertIn("Y 2 más", self.html(mail.outbox[0]))
        self.assertEqual(Animal.objects.filter(expiro_avisado_el__isnull=False).count(), expiracion.MAX_ANIMALES_POR_MAIL + 2)

    @override_settings(ENV="LOCAL")
    def test_en_local_expira_pero_no_manda(self):

        willy = self.viejo()

        salida = self.correr()

        willy.refresh_from_db()
        self.assertEqual(willy.estado, "E")
        self.assertEqual(mail.outbox, [])
        self.assertIn("en LOCAL no se mandan mails", salida)


class AvisarYaExpiradosTest(ExpiracionBase):
    """expirar_animales --avisar-ya-expirados --desde: el lote de los que expiraron antes de
    que existiera el mail."""

    def desde(self, dias):
        return (timezone.localdate() - timedelta(days=dias)).isoformat()

    def test_sin_aplicar_solo_cuenta_por_rescatista_sin_nombres_ni_mails(self):

        self.expirado("Nombre Secreto")
        willy = self.expirado("Otro Secreto")

        salida = self.correr("--avisar-ya-expirados", "--desde", self.desde(5))

        self.assertIn("rescatista {}: 2 animales".format(self.rescatista.id), salida)
        self.assertNotIn("Secreto", salida)
        self.assertNotIn("@", salida)
        self.assertEqual(mail.outbox, [])
        willy.refresh_from_db()
        self.assertIsNone(willy.expiro_avisado_el)

    def test_con_aplicar_manda_por_los_expirados_desde_esa_fecha(self):

        reciente = self.expirado("Reciente", hace_dias=3)
        viejo = self.expirado("Viejo", hace_dias=60)
        a_mano = make_animal(nombre="A mano", estado="E", expiro_el=None, cargado_por=self.rescatista)
        no_republicar = self.expirado("No republicar", pregunta_adopcion_hasta=timezone.now() + timedelta(days=3650))
        no_aprobado = self.expirado("Sin aprobar", aprobado=False)

        self.correr("--avisar-ya-expirados", "--desde", self.desde(10), "--aplicar")

        self.assertEqual(len(mail.outbox), 1)
        html = self.html(mail.outbox[0])
        self.assertIn("Reciente", html)
        for animal in (viejo, a_mano, no_republicar, no_aprobado):
            self.assertNotIn(animal.nombre, html)
        reciente.refresh_from_db()
        self.assertIsNotNone(reciente.expiro_avisado_el)

    def test_nunca_dos_veces_por_la_misma_expiracion(self):
        """Ni corriendo el lote dos veces, ni por los que ya avisó el cron."""

        self.viejo("Del cron")
        self.correr()
        self.expirado("Del lote")
        mail.outbox = []

        self.correr("--avisar-ya-expirados", "--desde", self.desde(10), "--aplicar")
        self.correr("--avisar-ya-expirados", "--desde", self.desde(10), "--aplicar")

        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("Del cron", self.html(mail.outbox[0]))

    def test_el_que_vuelve_a_expirar_tiene_su_mail(self):

        willy = self.viejo()
        self.correr()
        estados.republicar(Animal.objects.get(id=willy.id))
        Animal.objects.filter(id=willy.id).update(fecha_ingreso=hace(40))

        self.correr()

        self.assertEqual(len(mail.outbox), 2)

    def test_sin_desde_no_hace_nada(self):

        self.expirado()

        with self.assertRaises(CommandError):
            self.correr("--avisar-ya-expirados", "--aplicar")

        self.assertEqual(mail.outbox, [])

    def test_no_expira_nada(self):

        viejo = self.viejo()

        self.correr("--avisar-ya-expirados", "--desde", self.desde(10), "--aplicar")

        viejo.refresh_from_db()
        self.assertEqual(viejo.estado, "D")


class RespuestaViewTest(ExpiracionBase):
    """Los botones del mail. Se prueba sin login: es como llega el rescatista desde el mail."""

    def setUp(self):
        super().setUp()
        self.animal = self.expirado("Willy")

    def url(self, animal=None, **kwargs):
        return expiracion.link(animal or self.animal, **kwargs)

    def get(self, url):
        return self.client.get(url)

    def responder(self, respuesta, url=None):
        return self.client.post(url or self.url(), {"respuesta": respuesta})

    def test_el_get_solo_muestra(self):
        """Los escáneres de links de Gmail y de los antivirus abren cada link del mail."""

        respuesta = self.get(self.url(respuesta=expiracion.SIGUE))
        self.get(self.url(respuesta=expiracion.ADOPTADO))

        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.content.decode()
        self.assertIn("¿Willy sigue en adopción?", html)
        self.assertEqual(html.count('name="respuesta"'), 2)
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "E")

    def test_el_boton_que_toco_en_el_mail_va_primero(self):

        html = self.get(self.url(respuesta=expiracion.ADOPTADO)).content.decode()
        self.assertLess(html.index('value="adoptado"'), html.index('value="sigue"'))

        html = self.get(self.url(respuesta=expiracion.SIGUE)).content.decode()
        self.assertLess(html.index('value="sigue"'), html.index('value="adoptado"'))

    def test_sigue_en_adopcion_lo_republica_por_otro_mes(self):

        url = self.url()
        respuesta = self.responder(expiracion.SIGUE, url)

        self.assertEqual(respuesta.status_code, 302)
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "D")
        self.assertIsNone(self.animal.expiro_el)
        self.assertGreater(self.animal.fecha_ingreso, hace(1))
        self.assertIn(self.animal, Animal.get_all_for_adoption())

        html = self.get(respuesta["Location"]).content.decode()
        self.assertIn("vuelve a estar en adopción", html)
        self.assertNotIn('name="respuesta"', html)

        #y la corrida de mañana no lo vuelve a sacar
        self.correr()
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "D")

    def test_ya_se_adopto_lo_marca_con_fecha_y_ofrece_el_panel(self):

        make_estado_formulario(self.animal, persona_nombre="Ana Gómez", tipo="A", hash="h-ana")

        respuesta = self.responder(expiracion.ADOPTADO)

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")
        self.assertIsNotNone(self.animal.fecha_adopcion)

        html = self.get(respuesta["Location"]).content.decode()
        self.assertIn("¿Quién lo adoptó?", html)
        self.assertIn('href="/accounts/profile/"', html)

        #el panel le pregunta quién, porque ahora tiene fecha
        self.client.force_login(self.rescatista)
        panel = self.client.get("/accounts/profile/").content.decode()
        self.assertIn('id="pregunta-adopcion-{}"'.format(self.animal.id), panel)

    def test_no_muestra_nada_de_los_candidatos(self):

        make_estado_formulario(self.animal, persona_nombre="Ana Gómez", tipo="A", hash="h-ana")

        for url in (self.url(), "{}?hecho=adoptado".format(self.url())):
            self.assertNotIn("Ana", self.get(url).content.decode())

        self.responder(expiracion.ADOPTADO)
        self.assertNotIn("Ana", self.get(self.url() + "?hecho=adoptado").content.decode())

    def test_un_link_alterado_inventado_o_vencido_no_sirve(self):

        bueno = expiracion.token(self.animal)
        otra_sal = signing.dumps({"a": self.animal.id, "u": self.rescatista.id, "e": 0}, salt="otra-cosa")

        for token in (bueno[:-2] + "xx", otra_sal, str(self.animal.id), "x"):
            with self.subTest(token=token):
                url = "/sigue-en-adopcion/{}/".format(token)
                respuesta = self.get(url)
                self.assertEqual(respuesta.status_code, 404)
                self.assertIn("Este link ya no sirve", respuesta.content.decode())
                self.responder(expiracion.SIGUE, url)

        with mock.patch.object(expiracion, "VIGENCIA_DIAS", -1):
            self.assertEqual(self.get(self.url()).status_code, 404)
            self.responder(expiracion.SIGUE)

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "E")

    def test_deja_de_servir_si_el_animal_ya_cambio(self):
        """Lo republicó desde el panel: el botón "Ya se adoptó" del mail viejo no lo pisa."""

        url = self.url()
        estados.republicar(self.animal)

        html = self.get(url).content.decode()
        self.responder(expiracion.ADOPTADO, url)

        self.assertIn("ya está en adopción", html)
        self.assertNotIn('name="respuesta"', html)
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "D")

    def test_el_link_de_una_expiracion_anterior_no_sirve_para_la_nueva(self):

        url = self.url()
        Animal.objects.filter(id=self.animal.id).update(expiro_el=timezone.now())

        self.responder(expiracion.SIGUE, url)

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "E")

    def test_no_sirve_si_el_animal_paso_a_otra_cuenta_o_la_cuenta_se_dio_de_baja(self):

        url = self.url()

        self.animal.cargado_por = make_user(email="otra@catpuccino.test")
        self.animal.save()
        self.assertEqual(self.get(url).status_code, 404)

        self.animal.cargado_por = self.rescatista
        self.animal.save()
        self.rescatista.is_active = False
        self.rescatista.save()
        self.assertEqual(self.get(url).status_code, 404)

    def test_una_respuesta_que_no_existe_no_cambia_nada(self):

        self.responder("borrar")

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "E")
