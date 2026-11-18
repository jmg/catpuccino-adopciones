"""Que ningún animal quede sin veredicto de la revisión con IA (services/revision_pendiente.py).

La regla que pidió el usuario el 18/11/2026: lo que está bien lo aprueba la IA y lo que marca le
llega por mail a quien revisa. El caso que lo motivó: el 1532 se cargó con la revisión apagada,
quedó en 'E' ("no se pudo revisar"), su cuenta era nueva y esperó nueve días a una persona sin
que nadie se enterara.
"""
import json
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from catus.models import Animal, CatusUser
from catus.services import revision_pendiente
from catus.services.mail import MailService
from catus.services.moderacion import ModeracionService
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo
from catus.views.animal import AprobarView, EditView

SITIO = dict(
    ENV="TEST", HOST="adopciones.test", SSL_HOST="https://adopciones.test", SEND_MAIL="sitio@catpuccino.test",
    MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="k", INSTAGRAM_AUTO_ACTIVO=True,
    AVISOS_DE_REVISION_A=["revision@catpuccino.test"],
)


def hace(horas):
    return timezone.now() - timedelta(hours=horas)


def veredicto(estado, motivo="Se ve un gato."):
    """La revisión devuelve esto; lo que se prueba acá es qué se hace con el veredicto."""

    return mock.patch.object(ModeracionService, "revisar", return_value=(estado, motivo))


def sin_poder_revisar():
    return veredicto(Animal.REVISION_ERROR, "No se pudo consultar el servicio: APIConnectionError")


def gato_de_ia(estado, motivo="Se ve un gato."):
    """Lo que devuelve el modelo, para los tests que pasan por la vista con la revisión de verdad."""

    animales = ["gato"] if estado == Animal.REVISION_OK else []
    return mock.patch.object(ModeracionService, "_preguntar", return_value=json.dumps({
        "animales": animales, "descripcion": motivo, "texto_sospechoso": False, "inapropiado": False,
    }))


def pendiente_sin_revisar(**kwargs):
    """Como quedó el 1532: cargado por una cuenta nueva, sin aprobar, la revisión en 'E'."""

    if "cargado_por" not in kwargs:
        kwargs["cargado_por"] = (CatusUser.objects.filter(email="nueva@catpuccino.test").first()
                                 or make_user(email="nueva@catpuccino.test"))
    kwargs.setdefault("aprobado", False)
    kwargs.setdefault("revision_ia_estado", Animal.REVISION_ERROR)
    kwargs.setdefault("revision_ia_motivo", "La revisión automática está desactivada.")
    kwargs.setdefault("revision_ia_fecha", hace(24 * 9))
    kwargs.setdefault("fecha_ingreso", hace(24 * 9))
    return make_animal(**kwargs)


def avisos():
    return [m for m in mail.outbox if m.to == ["revision@catpuccino.test"]]


@override_settings(**SITIO)
class ReintentarTest(TestCase):
    """La pasada del cron sobre lo que quedó en "no se pudo revisar"."""

    def test_el_que_esperaba_y_ahora_da_ok_se_aprueba_como_un_alta(self):
        """El 1532: la IA lo ve bien, así que sale. Sin aprobado_por_persona (no es historial),
        agendado para Instagram, y su mes de publicado corre desde ahora."""

        animal = pendiente_sin_revisar()

        with veredicto(Animal.REVISION_OK):
            resumen = revision_pendiente.reintentar()

        animal.refresh_from_db()
        self.assertEqual(resumen["aprobados"], [animal.id])
        self.assertTrue(animal.aprobado)
        self.assertFalse(animal.aprobado_por_persona, "una aprobación de la IA quedó como historial")
        self.assertEqual(animal.revision_ia_estado, Animal.REVISION_OK)
        self.assertIsNotNone(animal.instagram_programado_para, "se aprobó y no quedó agendado para Instagram")
        self.assertGreater(animal.fecha_ingreso, hace(1), "el mes de publicado corre desde que se publica")
        self.assertEqual(avisos(), [], "lo aprobado no le manda nada a quien revisa")

    def test_a_quien_lo_cargo_le_llega_que_se_publico(self):
        """Lo cargó, vio "estamos revisando la publicación" y se fue: el mismo mail que cuando lo
        aprueba el equipo."""

        animal = pendiente_sin_revisar()

        with veredicto(Animal.REVISION_OK):
            revision_pendiente.reintentar()

        self.assertEqual([m.to for m in mail.outbox], [["nueva@catpuccino.test"]])
        self.assertIn("ya está publicado", mail.outbox[0].subject)
        self.assertTrue(Animal.objects.get(id=animal.id).aprobado)

    def test_si_la_ia_lo_marca_le_llega_el_mail_a_quien_revisa_y_sigue_esperando(self):

        animal = pendiente_sin_revisar()

        with veredicto(Animal.REVISION_REVISAR, "No se ve ningún animal en las fotos."):
            resumen = revision_pendiente.reintentar()

        animal.refresh_from_db()
        self.assertEqual(resumen["marcados"], [animal.id])
        self.assertFalse(animal.aprobado)
        self.assertEqual(len(avisos()), 1)
        self.assertEqual(avisos()[0].subject, "Catpuccino Adopciones - La revisión marcó a Willy")
        self.assertIn("No se ve ningún animal en las fotos.", avisos()[0].alternatives[0][0])

    def test_lo_marcado_avisa_una_sola_vez(self):
        """Con un veredicto ya no es 'E': la corrida siguiente no lo vuelve a tomar."""

        pendiente_sin_revisar()

        with veredicto(Animal.REVISION_REVISAR, "Es una publicidad."):
            revision_pendiente.reintentar()
            revision_pendiente.reintentar()

        self.assertEqual(len(avisos()), 1)

    def test_si_sigue_sin_poder_suma_un_intento_y_no_avisa(self):

        animal = pendiente_sin_revisar()

        with sin_poder_revisar():
            resumen = revision_pendiente.reintentar()

        animal.refresh_from_db()
        self.assertEqual(resumen["siguen_sin_poder"], [animal.id])
        self.assertEqual(animal.revision_ia_intentos, 1)
        self.assertFalse(animal.aprobado)
        self.assertEqual(avisos(), [])

    def test_despues_de_un_dia_de_intentos_avisa_que_no_se_pudo_y_deja_de_intentar(self):
        """No es sospecha: el mail lo dice. Y no se gasta una llamada por hora para siempre."""

        animal = pendiente_sin_revisar(revision_ia_intentos=revision_pendiente.MAX_INTENTOS - 1)

        with sin_poder_revisar():
            resumen = revision_pendiente.reintentar()

        self.assertEqual(resumen["sin_revision"], [animal.id])
        self.assertEqual(len(avisos()), 1)
        self.assertEqual(avisos()[0].subject, "Catpuccino Adopciones - No se pudo revisar a Willy")
        self.assertIn("No es sospecha", avisos()[0].alternatives[0][0])

        with sin_poder_revisar() as revisar:
            revision_pendiente.reintentar()

        revisar.assert_not_called()
        self.assertEqual(len(avisos()), 1, "avisó dos veces que no se pudo")

    def test_un_veredicto_vuelve_los_intentos_a_cero(self):

        animal = pendiente_sin_revisar(revision_ia_intentos=5)

        with veredicto(Animal.REVISION_OK):
            revision_pendiente.reintentar()

        animal.refresh_from_db()
        self.assertEqual(animal.revision_ia_intentos, 0)

    def test_el_aprobado_por_historial_sigue_publicado_y_si_lo_marca_avisa(self):
        """Al rescatista conocido una caída de OpenAI no lo frena (se aprueba por historial),
        pero la revisión se le pasa igual después."""

        animal = pendiente_sin_revisar(aprobado=True)

        with veredicto(Animal.REVISION_REVISAR, "Es una captura de pantalla."):
            resumen = revision_pendiente.reintentar()

        animal.refresh_from_db()
        self.assertEqual(resumen["marcados"], [animal.id])
        self.assertTrue(animal.aprobado, "la revisión sacó del sitio algo que aprobó el historial")
        self.assertEqual(len(avisos()), 1)
        self.assertIn("Está publicado", avisos()[0].alternatives[0][0])

    def test_el_aprobado_por_historial_que_da_ok_no_manda_nada(self):

        animal = pendiente_sin_revisar(aprobado=True)

        with veredicto(Animal.REVISION_OK):
            resumen = revision_pendiente.reintentar()

        self.assertEqual(resumen["ok"], [animal.id])
        self.assertEqual(mail.outbox, [])

    def test_el_aprobado_por_historial_sin_revision_en_un_dia_no_avisa(self):
        """Ya decidió alguien (el historial) y está publicado: deja de intentar, sin mail."""

        animal = pendiente_sin_revisar(aprobado=True, revision_ia_intentos=revision_pendiente.MAX_INTENTOS - 1)

        with sin_poder_revisar():
            resumen = revision_pendiente.reintentar()

        self.assertEqual(resumen["sin_revision"], [animal.id])
        self.assertEqual(avisos(), [])

    def test_no_toca_lo_que_decide_una_persona(self):
        """Lo que su dueño devolvió a la cola después de un "No publicar", y lo que el equipo
        marcó "No publicar": ni se revisa ni se aprueba."""

        pendiente_sin_revisar(nombre="Vuelve", espera_a_una_persona=True)
        pendiente_sin_revisar(nombre="NoPublicar", estado="D", no_publicar_el=timezone.now())

        with veredicto(Animal.REVISION_OK) as revisar:
            revision_pendiente.reintentar()

        revisar.assert_not_called()
        self.assertFalse(Animal.objects.filter(aprobado=True).exists())

    def test_no_revisa_lo_que_aprobo_una_persona(self):
        """Una persona ya lo miró: un mail sobre eso sólo es ruido."""

        pendiente_sin_revisar(aprobado=True, aprobado_por_persona=True)

        with veredicto(Animal.REVISION_REVISAR) as revisar:
            revision_pendiente.reintentar()

        revisar.assert_not_called()
        self.assertEqual(avisos(), [])

    def test_no_toca_lo_que_no_esta_en_adopcion_ni_lo_que_ya_tiene_veredicto(self):

        pendiente_sin_revisar(nombre="Adoptado", estado="A")
        pendiente_sin_revisar(nombre="Expirado", estado="E")
        pendiente_sin_revisar(nombre="Marcado", revision_ia_estado=Animal.REVISION_REVISAR)
        pendiente_sin_revisar(nombre="Viejo", revision_ia_estado=Animal.REVISION_PENDIENTE)

        with veredicto(Animal.REVISION_OK) as revisar:
            revision_pendiente.reintentar()

        revisar.assert_not_called()

    def test_con_la_revision_apagada_no_hace_nada(self):

        pendiente_sin_revisar()

        with override_settings(MODERACION_IA_ACTIVA=False), veredicto(Animal.REVISION_OK) as revisar:
            resumen = revision_pendiente.reintentar()

        revisar.assert_not_called()
        self.assertTrue(resumen["apagada"])

    def test_el_cupo_no_gasta_intentos(self):
        """El cupo vuelve al día siguiente; los intentos son para fallas de la revisión."""

        animal = pendiente_sin_revisar()

        with mock.patch.object(ModeracionService, "paso_el_limite", return_value=True), \
                veredicto(Animal.REVISION_OK) as revisar:
            resumen = revision_pendiente.reintentar()

        revisar.assert_not_called()
        self.assertEqual(resumen["esperan_cupo"], [animal.id])
        animal.refresh_from_db()
        self.assertEqual(animal.revision_ia_intentos, 0)

        with mock.patch.object(ModeracionService, "paso_el_limite_total", return_value=True), \
                veredicto(Animal.REVISION_OK) as revisar:
            revision_pendiente.reintentar()

        revisar.assert_not_called()

    def test_un_animal_con_problemas_no_corta_la_corrida(self):

        primero = pendiente_sin_revisar(nombre="Primero")
        segundo = pendiente_sin_revisar(nombre="Segundo")

        with mock.patch.object(ModeracionService, "revisar", side_effect=[RuntimeError("roto"), (Animal.REVISION_OK, "Un gato.")]):
            resumen = revision_pendiente.reintentar()

        self.assertEqual(resumen["aprobados"], [segundo.id])
        primero.refresh_from_db()
        self.assertFalse(primero.aprobado)

    def test_una_tanda_por_corrida(self):

        for numero in range(revision_pendiente.POR_CORRIDA + 3):
            pendiente_sin_revisar(nombre="Gato {}".format(numero))

        with veredicto(Animal.REVISION_OK) as revisar:
            revision_pendiente.reintentar()

        self.assertEqual(revisar.call_count, revision_pendiente.POR_CORRIDA)

    def test_si_una_persona_lo_decidio_mientras_la_ia_miraba_no_lo_aprueba(self):
        """La revisión tarda hasta 8 s: en ese rato el equipo pudo marcarlo "No publicar"."""

        animal = pendiente_sin_revisar()

        def revisar_mientras_lo_sacan(self_moderacion, a):
            Animal.objects.filter(id=animal.id).update(estado="E", no_publicar_el=timezone.now())
            return Animal.REVISION_OK, "Se ve un gato."

        with mock.patch.object(ModeracionService, "revisar", autospec=True, side_effect=revisar_mientras_lo_sacan):
            revision_pendiente.reintentar()

        animal.refresh_from_db()
        self.assertFalse(animal.aprobado)
        self.assertIsNone(animal.instagram_programado_para)


@override_settings(**SITIO)
class CronTest(TestCase):
    """Corre desde automatic_approve, que ya corre cada hora y tiene su monitor."""

    def test_el_cron_de_cada_hora_reintenta(self):

        animal = pendiente_sin_revisar()
        salida = StringIO()

        with veredicto(Animal.REVISION_OK):
            call_command("automatic_approve", stdout=salida, stderr=StringIO())

        animal.refresh_from_db()
        self.assertTrue(animal.aprobado)
        self.assertIn("aprobados [{}]".format(animal.id), salida.getvalue())

    def test_si_reintentar_falla_lo_de_antes_ya_se_hizo(self):

        user = make_user(email="conocida@catpuccino.test")
        make_animal(cargado_por=user, aprobado=True, aprobado_por_persona=True)

        with mock.patch("catus.services.revision_pendiente.reintentar", side_effect=RuntimeError("roto")):
            call_command("automatic_approve", stdout=StringIO(), stderr=StringIO())

        user.refresh_from_db()
        self.assertTrue(user.automatic_approve)


class DestinatarioTest(TestCase):

    @override_settings(ENV="TEST", SSL_HOST="https://adopciones.test", AVISOS_DE_REVISION_A=["uno@catpuccino.test", "dos@catpuccino.test"])
    def test_el_mail_va_a_quien_dice_la_config(self):

        MailService().send_new_animal_mail(make_animal(aprobado=False))

        self.assertEqual(mail.outbox[0].to, ["uno@catpuccino.test", "dos@catpuccino.test"])


class AltaEditarTestCase(TestCase):
    """Las altas y las ediciones van por EditView de verdad, con la revisión de verdad y sólo el
    modelo de OpenAI simulado."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media, **SITIO)
        self.override.enable()
        self.factory = RequestFactory()
        self.nueva = make_user(email="nueva@catpuccino.test", automatic_approve=False)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def pedir(self, datos, animal_id=None, user=None):

        request = self.factory.post("/animales/", datos)
        request.user = user or self.nueva
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()

        view = EditView()
        view.request = request
        if animal_id:
            view.req(is_post=True, animal_id=str(animal_id))
        else:
            view.req(is_post=True)
        return request

    def cargar(self, nombre="Willy"):

        self.pedir({
            "tipo": "G", "estado": "D", "nombre": nombre, "edad": "2 años", "sexo": "M", "zona": "CABA",
            "datos": "Gatito en adopción.",
            "animalimage_set-TOTAL_FORMS": "1", "animalimage_set-INITIAL_FORMS": "0",
            "animalimage_set-MIN_NUM_FORMS": "0", "animalimage_set-MAX_NUM_FORMS": "1000",
            "animalimage_set-0-image": uploaded_photo(),
        })
        return Animal.objects.get(nombre=nombre)

    def editar(self, animal, user=None, **cambios):

        imagenes = list(animal.get_images())
        datos = {
            "tipo": animal.tipo, "estado": animal.estado, "nombre": animal.nombre,
            "edad": animal.edad or "", "sexo": animal.sexo or "M", "zona": animal.zona or "",
            "datos": animal.datos or "",
            "animalimage_set-TOTAL_FORMS": str(len(imagenes)), "animalimage_set-INITIAL_FORMS": str(len(imagenes)),
            "animalimage_set-MIN_NUM_FORMS": "0", "animalimage_set-MAX_NUM_FORMS": "1000",
        }
        for i, imagen in enumerate(imagenes):
            datos["animalimage_set-%d-id" % i] = str(imagen.id)
            datos["animalimage_set-%d-animal" % i] = str(animal.id)
        datos.update(cambios)

        request = self.pedir(datos, animal_id=animal.id, user=user or animal.cargado_por)
        animal.refresh_from_db()
        return request


class AltaTest(AltaEditarTestCase):
    """Qué mail sale en el alta que no se aprobó sola."""

    def test_si_la_ia_lo_marca_el_mail_sale_ya(self):

        with gato_de_ia(Animal.REVISION_REVISAR, "Es una captura de pantalla."):
            animal = self.cargar()

        self.assertFalse(animal.aprobado)
        self.assertEqual(len(avisos()), 1)
        self.assertEqual(avisos()[0].subject, "Catpuccino Adopciones - Nuevo Ingreso")

    def test_si_no_pudo_revisar_no_avisa_todavia_porque_reintenta_el_cron(self):
        """Una caída de OpenAI de unos minutos mandaba un mail por cada alta que el cron
        aprueba al rato."""

        with mock.patch.object(ModeracionService, "_preguntar", side_effect=RuntimeError("API caída")):
            animal = self.cargar()

        self.assertFalse(animal.aprobado)
        self.assertEqual(animal.revision_ia_estado, Animal.REVISION_ERROR)
        self.assertEqual(avisos(), [])
        self.assertIn(animal, revision_pendiente.a_reintentar(), "quedó en el limbo: el cron no lo va a tomar")

    def test_con_la_revision_apagada_el_mail_sale_ya(self):
        """Ahí no reintenta nadie: es el mundo de antes, todo lo que espera le llega a una persona."""

        with override_settings(MODERACION_IA_ACTIVA=False):
            animal = self.cargar()

        self.assertFalse(animal.aprobado)
        self.assertEqual(len(avisos()), 1)


class EditarTest(AltaEditarTestCase):
    """La re-revisión de una edición también decide."""

    def pendiente_con_foto(self, **kwargs):

        animal = pendiente_sin_revisar(cargado_por=self.nueva, edad="2 años", sexo="M", zona="CABA",
                                       datos="Gatito.", **kwargs)
        make_animal_image(animal=animal)
        return animal

    def test_el_que_esperaba_y_al_editarlo_da_ok_se_aprueba(self):

        animal = self.pendiente_con_foto()

        with gato_de_ia(Animal.REVISION_OK):
            request = self.editar(animal, datos="Gatito muy mimoso.")

        self.assertTrue(animal.aprobado)
        self.assertFalse(animal.aprobado_por_persona)
        self.assertIsNotNone(animal.instagram_programado_para)
        self.assertTrue(request.session.get("is_new_animal_approved"))

    def test_si_al_editarlo_lo_marca_avisa_una_vez(self):

        animal = self.pendiente_con_foto(aprobado=True, revision_ia_estado=Animal.REVISION_OK)

        with gato_de_ia(Animal.REVISION_REVISAR, "No se ve ningún animal."):
            self.editar(animal, datos="Otra cosa.")
            self.editar(animal, datos="Otra cosa más.")

        self.assertEqual(animal.revision_ia_estado, Animal.REVISION_REVISAR)
        self.assertTrue(animal.aprobado, "la re-revisión no saca del sitio, avisa")
        self.assertEqual(len(avisos()), 1, "cada edición de algo ya marcado mandaba otro mail")
        self.assertEqual(avisos()[0].subject, "Catpuccino Adopciones - La revisión marcó a Willy")

    def test_editar_lo_revisable_le_devuelve_los_intentos(self):

        animal = self.pendiente_con_foto(revision_ia_intentos=revision_pendiente.MAX_INTENTOS)

        with mock.patch.object(ModeracionService, "_preguntar", side_effect=RuntimeError("API caída")):
            self.editar(animal, datos="Gatito con más datos.")

        self.assertEqual(animal.revision_ia_intentos, 0)
        self.assertIn(animal, revision_pendiente.a_reintentar())

    def test_el_que_vuelve_de_un_no_publicar_queda_para_una_persona(self):
        """La vuelta a la cola lo marca, y ni otra edición ni el cron lo aprueban después."""

        animal = self.pendiente_con_foto(estado="E", no_publicar_el=timezone.now(),
                                         no_publicar_motivo="Fotos o datos insuficientes")

        with gato_de_ia(Animal.REVISION_OK):
            self.editar(animal, estado="D", datos="Ahora con datos.")
            self.assertFalse(animal.aprobado)
            self.assertTrue(animal.espera_a_una_persona)

            self.editar(animal, datos="Ahora con más datos.")
            self.assertFalse(animal.aprobado, "la segunda edición lo aprobó sin la persona")

        Animal.objects.filter(id=animal.id).update(revision_ia_estado=Animal.REVISION_ERROR)
        with veredicto(Animal.REVISION_OK) as revisar:
            revision_pendiente.reintentar()
        revisar.assert_not_called()

    def test_cuando_lo_aprueba_una_persona_deja_de_esperarla(self):

        animal = self.pendiente_con_foto(espera_a_una_persona=True)
        equipo = make_user(email="equipo@catpuccino.test", is_superuser=True, is_staff=True)

        request = self.factory.post("/animal/aprobar/", {"id": animal.id})
        request.user = equipo
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        with mock.patch.object(MailService, "send_mail_aprobacion"):
            AprobarView.as_view()(request)

        animal.refresh_from_db()
        self.assertTrue(animal.aprobado)
        self.assertFalse(animal.espera_a_una_persona)
