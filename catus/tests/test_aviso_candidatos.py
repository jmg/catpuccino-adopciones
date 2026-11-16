"""El aviso "ya tiene familia" a los demás candidatos de un animal adoptado
(services/aviso_candidatos.py).

En 90 días, 67 personas se postularon a animales que ya se habían adoptado y nunca supieron
nada. Lo que estos tests cuidan:

- le llega a quien tiene el formulario abierto (No asignado, En proceso) y a nadie más: ni a
  quien adoptó, ni a los frenados por BuenAdoptante, duplicados o descartados;
- no sale por adopciones anteriores al corte (AVISO_CANDIDATOS_DESDE), ni sin corte, y espera
  a que se sepa quién adoptó o a que pasen tres días;
- un mail por casilla, aunque se haya postulado a varios adoptados; nunca dos veces;
- el texto sirve aunque lo lea quien adoptó y no dice nada de esa persona;
- comparte el tope diario por casilla del mail de recibo, y un mail que falla no corta nada.
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from forms_builder.forms.models import FieldEntry, Form

from catus.models import EstadoFormulario
from catus.services import aviso_candidatos, throttle
from catus.test_login_throttle import fake_memcached
from catus.tests.factories import make_animal, make_estado_formulario, make_field, make_form_entry, make_user


def hace(dias):
    return timezone.now() - timedelta(days=dias)


def corte(dias_atras=30):
    return (timezone.localdate() - timedelta(days=dias_atras)).isoformat()


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test", HOST="adopciones.test",
                   SSL_HOST="https://adopciones.test", AVISO_CANDIDATOS_DESDE=corte())
class AvisoCandidatosBase(TestCase):

    def setUp(self):
        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)

        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.michi = make_animal(nombre="Michi", tipo="G", estado="A", fecha_adopcion=hace(4), cargado_por=self.rescatista)
        self.luna = make_animal(nombre="Luna", tipo="G", cargado_por=self.rescatista)
        self.firulais = make_animal(nombre="Firulais", tipo="P", cargado_por=self.rescatista)

        #como en forms.sql: la primera respuesta es el id del animal elegido
        self.form = Form.objects.create(title="Pre adopción", slug="formulario-de-pre-adopcion", response="Gracias")
        self.campos = {
            "animal": make_field(self.form, "Nombre del gato a adoptar"),
            "nombre": make_field(self.form, "Nombre y Apellido"),
            "email": make_field(self.form, "Email"),
        }

    def formulario(self, animal, nombre, email, estado="N", tipo="A"):

        entry = make_form_entry(self.form)
        for clave, valor in (("animal", str(animal.id)), ("nombre", nombre), ("email", email)):
            FieldEntry.objects.create(entry=entry, field_id=self.campos[clave].id, value=valor)

        return make_estado_formulario(animal, form_entry=entry, hash="hash-{}-{}".format(animal.id, email),
                                      tipo=tipo, estado=estado, persona_nombre=nombre)

    def avisar(self, aplicar=True):
        return aviso_candidatos.avisar(aplicar=aplicar)

    def destinatarios(self):
        return sorted(destino for mensaje in mail.outbox for destino in mensaje.to)

    def avisado(self, formulario):
        formulario.refresh_from_db()
        return formulario.aviso_cierre_el is not None


class AQuienTest(AvisoCandidatosBase):

    def test_avisa_a_los_formularios_abiertos_y_a_nadie_mas(self):

        ana = self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test", estado="N")
        beto = self.formulario(self.michi, "Beto Ruiz", "beto@ejemplo.test", estado="P")
        adoptante = self.formulario(self.michi, "Carla Paz", "carla@ejemplo.test", estado="A")
        cerrados = [self.formulario(self.michi, "Persona " + estado, "{}@ejemplo.test".format(estado.lower()), estado=estado)
                    for estado in ("D", "B", "U", "R", "T")]
        transito = self.formulario(self.michi, "Tránsito Uno", "transito@ejemplo.test", tipo="T")

        self.avisar()

        self.assertEqual(self.destinatarios(), ["ana@ejemplo.test", "beto@ejemplo.test"])
        self.assertTrue(self.avisado(ana))
        self.assertTrue(self.avisado(beto))
        for formulario in [adoptante, transito] + cerrados:
            self.assertFalse(self.avisado(formulario), formulario.estado)

    def test_no_avisa_al_formulario_vinculado_como_el_de_quien_adopto(self):
        """El rescatista eligió a la persona en "¿Quién lo adoptó?" pero el formulario
        quedó en otro estado (por ejemplo, vinculado desde el admin)."""

        carla = self.formulario(self.michi, "Carla Paz", "carla@ejemplo.test", estado="P")
        self.michi.estado_formulario = carla
        self.michi.save()

        self.avisar()

        self.assertEqual(mail.outbox, [])
        self.assertTrue(self.avisado(carla), "se saltea para siempre")

    def test_no_avisa_a_la_casilla_de_quien_adopto_aunque_haya_mandado_otro_formulario(self):

        adoptante = self.formulario(self.michi, "Carla Paz", "carla@ejemplo.test", estado="A")
        repetido = self.formulario(self.michi, "Carla Paz", "Carla@Ejemplo.test", estado="N")
        self.michi.estado_formulario = adoptante
        self.michi.save()

        self.avisar()

        self.assertEqual(mail.outbox, [])
        self.assertTrue(self.avisado(repetido))

    def test_un_mail_invalido_se_saltea_para_siempre(self):

        sin_mail = self.formulario(self.michi, "Ana Gómez", "no es un mail <script>")

        self.avisar()

        self.assertEqual(mail.outbox, [])
        self.assertTrue(self.avisado(sin_mail), "si no, se lo vuelve a mirar todos los días")

    def test_solo_animales_adoptados(self):

        reservado = make_animal(nombre="Reservado", estado="R", fecha_adopcion=hace(4))
        formulario = self.formulario(reservado, "Ana Gómez", "ana@ejemplo.test")

        self.avisar()

        self.assertEqual(mail.outbox, [])
        self.assertFalse(self.avisado(formulario))


class CuandoTest(AvisoCandidatosBase):

    def test_sin_corte_no_avisa_a_nadie(self):

        self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        for valor in (None, "", "2026-13-45", "mañana"):
            with self.subTest(valor=valor), override_settings(AVISO_CANDIDATOS_DESDE=valor):
                self.avisar()
                self.assertEqual(mail.outbox, [])

    def test_no_avisa_por_adopciones_anteriores_al_corte(self):
        """El primer día no tienen que salir mails por adopciones de hace meses."""

        viejo = make_animal(nombre="Viejo", estado="A", fecha_adopcion=hace(200), cargado_por=self.rescatista)
        formulario = self.formulario(viejo, "Ana Gómez", "ana@ejemplo.test")

        self.avisar()

        self.assertEqual(mail.outbox, [])
        self.assertFalse(self.avisado(formulario))

    def test_espera_tres_dias_si_no_se_sabe_quien_adopto(self):
        """Le da tiempo al rescatista a contestar "¿Quién lo adoptó?" en el panel."""

        self.michi.fecha_adopcion = hace(1)
        self.michi.save()
        ana = self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        self.avisar()
        self.assertEqual(mail.outbox, [])

        self.michi.fecha_adopcion = hace(4)
        self.michi.save()
        self.avisar()
        self.assertEqual(self.destinatarios(), ["ana@ejemplo.test"])
        self.assertTrue(self.avisado(ana))

    def test_si_ya_se_sabe_quien_adopto_no_espera(self):

        self.michi.fecha_adopcion = hace(0)
        self.michi.estado_formulario = self.formulario(self.michi, "Carla Paz", "carla@ejemplo.test", estado="A")
        self.michi.save()
        self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        self.avisar()

        self.assertEqual(self.destinatarios(), ["ana@ejemplo.test"])

    def test_nunca_dos_veces(self):

        self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        self.avisar()
        self.avisar()

        self.assertEqual(len(mail.outbox), 1)


class UnMailPorCasillaTest(AvisoCandidatosBase):

    def test_un_mail_aunque_se_haya_postulado_a_varios_adoptados(self):

        pelusa = make_animal(nombre="Pelusa", tipo="G", estado="A", fecha_adopcion=hace(5), cargado_por=self.rescatista)
        uno = self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")
        otro = self.formulario(pelusa, "Ana Gómez", "ANA@ejemplo.test")

        self.avisar()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Pelusa y Michi ya tienen familia")
        self.assertTrue(self.avisado(uno))
        self.assertTrue(self.avisado(otro))


class ElMailTest(AvisoCandidatosBase):

    def setUp(self):
        super().setUp()
        self.adoptante = self.formulario(self.michi, "Carla Paz", "carla@ejemplo.test", estado="A")
        self.michi.estado_formulario = self.adoptante
        self.michi.adoptante = "Carla Paz"
        self.michi.save()
        self.ana = self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        self.avisar()
        self.mensaje = mail.outbox[0]
        self.html = self.mensaje.alternatives[0][0]

    def test_es_neutro_y_no_dice_nada_de_quien_adopto(self):

        self.assertEqual(self.mensaje.subject, "Michi ya tiene familia")
        self.assertIn("Si esa familia sos vos, ¡felicitaciones!", self.html)
        for dato in ("Carla", "carla@", self.adoptante.hash):
            self.assertNotIn(dato, self.html)
            self.assertNotIn(dato, self.mensaje.body)

    def test_ofrece_otros_de_la_misma_especie_con_el_link_para_postularse(self):

        self.assertIn("Luna", self.html)
        self.assertNotIn("Firulais", self.html)
        self.assertIn("https://adopciones.test/postularme/", self.html)
        self.assertIn("?id={}".format(self.luna.id), self.html)
        #el link privado no es el hash que conocen el rescatista y el equipo
        self.assertNotIn(self.ana.hash, self.html)

    def test_el_nombre_del_animal_sale_escapado(self):

        mail.outbox = []
        otro = make_animal(nombre="<b>Tom</b>", tipo="G", estado="A", fecha_adopcion=hace(5))
        self.formulario(otro, "Beto Ruiz", "beto@ejemplo.test")

        self.avisar()

        self.assertIn("&lt;b&gt;Tom&lt;/b&gt;", mail.outbox[0].alternatives[0][0])
        self.assertNotIn("<b>Tom</b>", mail.outbox[0].alternatives[0][0])


class TopesYFallasTest(AvisoCandidatosBase):

    def test_comparte_el_tope_diario_del_mail_de_recibo(self):
        """La casilla la escribió quien completó el formulario: nada prueba que sea suya. Si
        ya recibió los recibos del día, el aviso queda para mañana."""

        import hashlib
        from catus.views.adoption import RECEIPTS_MAX_PER_DAY

        ana = self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")
        beto = self.formulario(self.michi, "Beto Ruiz", "beto@ejemplo.test")
        casilla = hashlib.sha256(b"ana@ejemplo.test").hexdigest()
        for _ in range(RECEIPTS_MAX_PER_DAY):
            throttle.hit("adoption-receipt", casilla, 24 * 60 * 60)

        resultado = self.avisar()

        self.assertEqual(self.destinatarios(), ["beto@ejemplo.test"])
        self.assertEqual(resultado["topados"], 1)
        self.assertFalse(self.avisado(ana), "se reintenta mañana")
        self.assertTrue(self.avisado(beto))

    def test_un_envio_que_falla_no_corta_a_los_demas_ni_deja_el_mail_en_el_log(self):

        ana = self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")
        beto = self.formulario(self.michi, "Beto Ruiz", "beto@ejemplo.test")
        enviar = aviso_candidatos.send_html_email

        def falla_con_ana(asunto, html, desde, para):
            if para == "ana@ejemplo.test":
                raise RuntimeError("SendGrid caído")
            return enviar(asunto, html, desde, para)

        with mock.patch.object(aviso_candidatos, "send_html_email", side_effect=falla_con_ana), \
                self.assertLogs("catus.services.aviso_candidatos", "WARNING") as logs:
            resultado = self.avisar()

        self.assertEqual(resultado["fallidos"], 1)
        self.assertEqual(self.destinatarios(), ["beto@ejemplo.test"])
        self.assertFalse(self.avisado(ana), "se reintenta en la próxima corrida")
        self.assertTrue(self.avisado(beto))
        self.assertNotIn("ana@", "\n".join(logs.output))

    @override_settings(ENV="LOCAL")
    def test_en_local_no_sale_nada(self):
        """Una copia local de la base de producción tiene mails de gente de verdad."""

        ana = self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        resultado = self.avisar()

        self.assertTrue(resultado["local"])
        self.assertEqual(mail.outbox, [])
        self.assertFalse(self.avisado(ana))


class ComandosTest(AvisoCandidatosBase):

    def correr(self, comando, *args):
        salida = StringIO()
        call_command(comando, *args, stdout=salida, stderr=StringIO())
        return salida.getvalue()

    def test_sin_aplicar_solo_cuenta_sin_nombres_ni_mails(self):

        ana = self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        salida = self.correr("avisar_candidatos")

        self.assertIn("1 casillas a avisar", salida)
        self.assertNotIn("ana@", salida)
        self.assertNotIn("Ana", salida)
        self.assertNotIn("Michi", salida)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(self.avisado(ana))

    def test_con_aplicar_manda(self):

        self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        salida = self.correr("avisar_candidatos", "--aplicar")

        self.assertIn("1 mails enviados", salida)
        self.assertEqual(self.destinatarios(), ["ana@ejemplo.test"])

    def test_el_cron_de_expiracion_tambien_avisa(self):
        """No hace falta otro cron: corre al final de expirar_animales."""

        self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        self.correr("expirar_animales")

        self.assertEqual(self.destinatarios(), ["ana@ejemplo.test"])

    def test_si_el_aviso_explota_la_expiracion_igual_queda(self):

        viejo = make_animal(nombre="Viejo", fecha_ingreso=hace(40), cargado_por=self.rescatista)

        with mock.patch.object(aviso_candidatos, "avisar", side_effect=RuntimeError("boom")), \
                self.assertLogs("catus.management.commands.expirar_animales", "WARNING"):
            self.correr("expirar_animales")

        viejo.refresh_from_db()
        self.assertEqual(viejo.estado, "E")

    def test_la_simulacion_de_la_expiracion_no_manda(self):

        self.formulario(self.michi, "Ana Gómez", "ana@ejemplo.test")

        salida = self.correr("expirar_animales", "--simular")

        self.assertIn("simulación", salida)
        self.assertEqual(mail.outbox, [])
