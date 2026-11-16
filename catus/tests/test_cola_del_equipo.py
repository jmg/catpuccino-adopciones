"""La cola del equipo (/tools/animalespendientes/), "No publicar" y archivar_pendientes.

En noviembre de 2026 había 58 animales sin aprobar, 54 de antes de la revisión con IA y 41
con más de 180 días, y nadie los miraba: la pantalla listaba también todo lo ya publicado o
expirado (publicar y expirar apagan instagram_listo_para_publicar), así que lo que esperaba
aprobación quedaba enterrado. Y no había forma de decir que no: lo que el equipo no quería
publicar quedaba "En revisión" para siempre, en la cola y en el panel del rescatista.
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
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catus.models import Animal
from catus.services.mail import MailService
from catus.services.moderacion import ModeracionService
from catus.services.pendientes import MOTIVO_SIN_REVISION, PendientesService
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo

SITIO = dict(ENV="TEST", HOST="adopciones.test", SSL_HOST="https://adopciones.test", SEND_MAIL="sitio@catpuccino.test")


def hace(dias):
    return timezone.now() - timedelta(days=dias)


def no_publicado(**kwargs):
    """Un animal que el equipo decidió no publicar, como lo deja "No publicar"."""

    kwargs.setdefault("estado", "E")
    kwargs.setdefault("aprobado", False)
    kwargs.setdefault("no_publicar_el", timezone.now())
    kwargs.setdefault("no_publicar_motivo", "Fotos o datos insuficientes")
    return make_animal(**kwargs)


class ColaTestCase(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.equipo = make_user(email="equipo@catpuccino.test", is_superuser=True, is_staff=True)
        self.rescatista = make_user(email="rescatista@catpuccino.test")

    def pedido(self, metodo, datos=None, user=None, sesion=None):

        request = getattr(self.factory, metodo)("/tools/animalespendientes/", datos or {})
        request.user = user or self.equipo
        request.session = {} if sesion is None else sesion
        return request

    def abrir(self, user=None, sesion=None):

        from catus.views.tools import AnimalesPendientesView

        response = AnimalesPendientesView.as_view(template_name="tools/animalespendientes.html")(
            self.pedido("get", user=user, sesion=sesion),
        )
        if hasattr(response, "render") and not response.is_rendered:
            response.render()
        return response.content.decode()

    def no_publicar(self, animal, user=None, sesion=None, **datos):

        from catus.views.tools import AnimalesPendientesView

        datos.setdefault("accion", "no_publicar")
        datos.setdefault("animal_id", animal.id)
        return AnimalesPendientesView.as_view()(self.pedido("post", datos, user=user, sesion=sesion))

    def esperando(self, nombre, dias=1, **kwargs):

        kwargs.setdefault("cargado_por", self.rescatista)
        kwargs.setdefault("aprobado", False)
        return make_animal(nombre=nombre, fecha_ingreso=hace(dias), **kwargs)


class LaColaEsSoloLoQueEsperaAprobacionTest(ColaTestCase):

    def test_no_lista_lo_ya_publicado_ni_lo_expirado(self):
        """El ruido que la tapaba: publicar en Instagram y expirar apagan la marca de
        Instagram, y la pantalla listaba todo lo que no la tuviera."""

        make_animal(nombre="Publicado", cargado_por=self.rescatista, aprobado=True,
                    instagram_publicado=True, instagram_listo_para_publicar=False)
        make_animal(nombre="SinPosteo", cargado_por=self.rescatista, aprobado=True,
                    instagram_listo_para_publicar=False)
        make_animal(nombre="Expirado", cargado_por=self.rescatista, aprobado=True, estado="E",
                    expiro_el=timezone.now())
        make_animal(nombre="ExpiradoSinAprobar", cargado_por=self.rescatista, aprobado=False, estado="E")
        self.esperando("Willy")

        cuerpo = self.abrir()

        self.assertIn(">Willy<", cuerpo)
        for nombre in ("Publicado", "SinPosteo", "Expirado", "ExpiradoSinAprobar"):
            self.assertNotIn(">{}<".format(nombre), cuerpo, "{} no espera aprobación".format(nombre))

    def test_los_reservados_sin_aprobar_tambien_esperan(self):

        self.esperando("Reservado", estado="R")

        self.assertIn(">Reservado<", self.abrir())

    def test_no_lista_los_que_no_se_publicaron(self):

        no_publicado(nombre="Descartado", cargado_por=self.rescatista)

        self.assertNotIn(">Descartado<", self.abrir())

    def test_va_del_que_mas_espera_al_mas_nuevo(self):
        """Los 41 con más de seis meses tienen que ser lo primero que se ve, no lo último:
        la pantalla iba del más nuevo al más viejo."""

        self.esperando("Nuevo", dias=2)
        self.esperando("Viejo", dias=200)
        self.esperando("Medio", dias=40)

        cuerpo = self.abrir()

        self.assertLess(cuerpo.index(">Viejo<"), cuerpo.index(">Medio<"))
        self.assertLess(cuerpo.index(">Medio<"), cuerpo.index(">Nuevo<"))

    def test_dice_cuantos_dias_lleva_esperando(self):

        self.esperando("Willy", dias=45)

        self.assertIn("Espera hace <b>45 días</b>", self.abrir())

    def test_dice_cuantos_animales_le_aprobo_el_equipo_a_esa_cuenta(self):
        """Es con lo que el equipo decide si confía en una cuenta. Los que aprobó la IA
        sola no cuentan, igual que para automatic_approve."""

        make_animal(nombre="A1", cargado_por=self.rescatista, aprobado=True, aprobado_por_persona=True)
        make_animal(nombre="A2", cargado_por=self.rescatista, aprobado=True, aprobado_por_persona=True)
        make_animal(nombre="PorLaIA", cargado_por=self.rescatista, aprobado=True, aprobado_por_persona=False)
        self.esperando("Willy")

        nueva = make_user(email="nueva@catpuccino.test")
        self.esperando("Michi", cargado_por=nueva)

        cuerpo = self.abrir()

        self.assertIn("2 animales aprobados por el equipo", cuerpo)
        self.assertIn("Ningún animal aprobado por el equipo", cuerpo)

    def test_no_hace_una_consulta_por_animal(self):
        """Foto, cuenta e historial de cada tarjeta: pedidos adentro del for son tres
        consultas por animal."""

        for i in range(2):
            make_animal_image(animal=self.esperando("Pocos{}".format(i)))

        with CaptureQueriesContext(connection) as pocos:
            self.abrir()

        for i in range(8):
            make_animal_image(animal=self.esperando("Muchos{}".format(i), cargado_por=make_user(email="r{}@x.test".format(i))))

        with CaptureQueriesContext(connection) as muchos:
            self.abrir()

        self.assertEqual(len(muchos), len(pocos))

    def test_aprobar_es_un_formulario_post_y_no_un_link(self):
        """Aprobar con un link lo disparaba cualquier vista previa o prefetch."""

        self.esperando("Willy")

        cuerpo = self.abrir()

        self.assertIn('<form method="post" action="/animal/aprobar/"', cuerpo)
        self.assertNotIn('href="/animal/aprobar/', cuerpo)

    def test_el_nombre_va_escapado_tambien_en_el_confirmar(self):
        """El confirm() de aprobar lee el nombre de un data-*, no de adentro del JS: el
        navegador decodifica las entidades de un atributo de evento antes de correrlo."""

        self.esperando("');alert(1);//<b>")

        cuerpo = self.abrir()

        self.assertNotIn("');alert(1);//<b>", cuerpo)
        self.assertIn('onsubmit="return confirm(this.dataset.confirmar)"', cuerpo)

    def test_muestra_el_aviso_una_sola_vez(self):

        sesion = {"pendientes_aviso": "Willy quedó aprobado y ya está en el sitio."}

        self.assertIn("Willy quedó aprobado", self.abrir(sesion=sesion))
        self.assertNotIn("Willy quedó aprobado", self.abrir(sesion=sesion))


@override_settings(**SITIO)
class NoPublicarTest(ColaTestCase):

    def test_un_usuario_comun_no_puede(self):

        animal = self.esperando("Willy")

        self.no_publicar(animal, user=self.rescatista)

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "D")
        self.assertIsNone(animal.no_publicar_el)

    def test_lo_deja_no_publicado_y_fuera_de_la_cola(self):
        """En "E", sin aprobar y sin expiro_el: así el panel no le pregunta al rescatista
        "¿siguen en adopción?", que es para lo que expiró solo y se republica con un clic."""

        animal = self.esperando("Willy")

        response = self.no_publicar(animal, motivo="Repetido")

        animal.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/tools/animalespendientes/")
        self.assertEqual(animal.estado, "E")
        self.assertFalse(animal.aprobado)
        self.assertIsNone(animal.expiro_el)
        self.assertIsNotNone(animal.no_publicar_el)
        self.assertEqual(animal.no_publicar_motivo, "Repetido")
        self.assertTrue(animal.no_se_publico())
        self.assertNotIn(animal, PendientesService().esperando())

    def test_el_motivo_es_la_opcion_y_el_texto(self):

        animal = self.esperando("Willy")

        self.no_publicar(animal, motivo="Fotos o datos insuficientes", detalle="  falta  la edad ")

        animal.refresh_from_db()
        self.assertEqual(animal.no_publicar_motivo, "Fotos o datos insuficientes: falta la edad")

    def test_otro_es_el_texto_solo(self):

        animal = self.esperando("Willy")

        self.no_publicar(animal, motivo="Otro", detalle="Es una publicidad")

        animal.refresh_from_db()
        self.assertEqual(animal.no_publicar_motivo, "Es una publicidad")

    def test_sin_motivo_tambien_se_puede(self):

        animal = self.esperando("Willy")

        self.no_publicar(animal)

        animal.refresh_from_db()
        self.assertTrue(animal.no_se_publico())
        self.assertIsNone(animal.no_publicar_motivo)

    def test_una_opcion_que_no_es_de_la_lista_no_se_guarda(self):
        """Lo que llega en el POST lo puede escribir cualquiera, aunque el form sea del
        equipo: la opción sólo vale si es una de la lista."""

        animal = self.esperando("Willy")

        self.no_publicar(animal, motivo="Cualquier cosa")

        animal.refresh_from_db()
        self.assertIsNone(animal.no_publicar_motivo)

    def test_le_avisa_a_quien_lo_cargo(self):

        animal = self.esperando("Willy")
        sesion = {}

        self.no_publicar(animal, sesion=sesion, motivo="Repetido")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["rescatista@catpuccino.test"])
        self.assertEqual(mail.outbox[0].subject, "Catpuccino Adopciones - Willy no se publicó")
        self.assertIn("Repetido", mail.outbox[0].alternatives[0][0])
        self.assertIn("Le avisamos a quien lo cargó", sesion["pendientes_aviso"])

    def test_un_fallo_del_mail_no_deshace_nada(self):

        animal = self.esperando("Willy")
        sesion = {}

        with mock.patch.object(MailService, "send_mail_no_publicado", side_effect=Exception("sendgrid caído")):
            response = self.no_publicar(animal, sesion=sesion)

        animal.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(animal.no_se_publico())
        self.assertIn("No se pudo mandar el mail", sesion["pendientes_aviso"])

    def test_no_dispara_instagram(self):

        animal = self.esperando("Willy")

        with mock.patch("catus.services.instagram_auto.InstagramAutoService.agendar") as agendar:
            self.no_publicar(animal)

        agendar.assert_not_called()
        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_programado_para)
        self.assertFalse(animal.instagram_listo_para_publicar)

    def test_no_toca_un_adoptado(self):
        """Desde una pestaña vieja se puede mandar uno que mientras tanto alguien marcó
        adoptado: pasarlo a "E" le borraba la adopción."""

        animal = self.esperando("Willy", estado="A")

        self.no_publicar(animal)

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "A")
        self.assertIsNone(animal.no_publicar_el)
        self.assertEqual(len(mail.outbox), 0)

    def test_al_publicado_que_la_ia_marco_lo_saca_del_sitio(self):
        """Lo que la re-revisión marcó después de una edición ya está publicado: "No
        publicar" lo desaprueba, le saca la marca de aprobado por una persona (como el
        tilde del admin) y cancela el posteo de Instagram."""

        animal = make_animal(
            nombre="Editado", cargado_por=self.rescatista, aprobado=True, aprobado_por_persona=True,
            revision_ia_estado=Animal.REVISION_REVISAR, revision_ia_motivo="Es una publicidad.",
            instagram_programado_para=timezone.now() + timedelta(hours=1),
        )

        self.assertIn("Editado", self.abrir())

        self.no_publicar(animal)

        animal.refresh_from_db()
        self.assertFalse(animal.aprobado)
        self.assertFalse(animal.aprobado_por_persona)
        self.assertIsNone(animal.instagram_programado_para)
        self.assertNotIn(animal, Animal.get_all_for_adoption())
        self.assertEqual(mail.outbox[0].subject, "Catpuccino Adopciones - Editado ya no está publicado")


@override_settings(MODERACION_IA_ACTIVA=True, OPENIA_API_KEY="k", **SITIO)
class MailAlEquipoEnElAltaTest(TestCase):
    """El mail "Nuevo animal para revisar… espera la aprobación del equipo" salía en todas
    las altas, también en las que la revisión ya había aprobado y estaban en el sitio."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.factory = RequestFactory()
        self.rescatista = make_user(email="rescatista@catpuccino.test")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def alta(self, animales, descripcion="Se ve un gato."):

        from catus.views.animal import EditView

        request = self.factory.post("/animales/", {
            "tipo": "G", "estado": "D", "nombre": "Willy", "edad": "2 años", "sexo": "M",
            "zona": "CABA", "datos": "Gatito en adopción.",
            "animalimage_set-TOTAL_FORMS": "1", "animalimage_set-INITIAL_FORMS": "0",
            "animalimage_set-MIN_NUM_FORMS": "0", "animalimage_set-MAX_NUM_FORMS": "1000",
            "animalimage_set-0-image": uploaded_photo(),
        })
        request.user = self.rescatista
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()

        view = EditView()
        view.request = request

        respuesta = json.dumps({"animales": animales, "descripcion": descripcion,
                                "texto_sospechoso": False, "inapropiado": False})
        with mock.patch.object(ModeracionService, "_preguntar", return_value=respuesta):
            view.req(is_post=True)

        return Animal.objects.get(nombre="Willy")

    def test_el_alta_que_se_aprobo_sola_no_avisa_al_equipo(self):

        animal = self.alta(["gato"])

        self.assertTrue(animal.aprobado, "el test no probó el caso: la IA no lo aprobó")
        self.assertEqual(len(mail.outbox), 0, "le avisó al equipo de algo que no espera nada")

    def test_el_que_espera_avisa_con_el_motivo_y_el_boton_a_la_cola(self):

        animal = self.alta([], "No se ve ningún animal.")

        self.assertFalse(animal.aprobado)
        self.assertEqual(len(mail.outbox), 1)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("No se ve ningún animal", html)
        self.assertIn('href="https://adopciones.test/tools/animalespendientes/#animal-{}"'.format(animal.id), html)
        self.assertNotIn("/animal/aprobar/", html)

    def test_un_fallo_del_mail_no_voltea_el_alta_que_espera(self):

        with mock.patch.object(MailService, "send_new_animal_mail", side_effect=Exception("sendgrid caído")):
            animal = self.alta([], "No se ve ningún animal.")

        self.assertFalse(animal.aprobado)
        self.assertIn(animal, PendientesService().esperando())


class IndiceDeHerramientasTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.equipo = make_user(email="equipo@catpuccino.test", is_superuser=True, is_staff=True)

    def abrir(self):

        from catus.views.tools import ToolsIndexView

        request = self.factory.get("/tools/")
        request.user = self.equipo
        response = ToolsIndexView.as_view(template_name="tools/toolsindex.html")(request)
        response.render()
        return response.content.decode()

    def test_dice_cuantos_esperan_aprobacion(self):
        """Los 58 que esperaban no los miraba nadie: el número tiene que verse sin entrar."""

        rescatista = make_user()
        make_animal(nombre="Uno", cargado_por=rescatista, aprobado=False)
        make_animal(nombre="Dos", cargado_por=rescatista, aprobado=False, estado="R")
        make_animal(nombre="Publicado", cargado_por=rescatista, aprobado=True)

        cuerpo = self.abrir()

        self.assertIn("2 esperando", cuerpo)
        self.assertIn("/tools/animalespendientes/", cuerpo)

    def test_enlaza_los_aprobados_sin_posteo(self):

        self.assertIn("/tools/animalessinposteo/", self.abrir())


class AprobadosSinPosteoTest(TestCase):
    """El flujo a mano de Instagram (armar las imágenes y marcarlo listo) salía de la
    pantalla de pendientes, que ahora es sólo la cola de aprobación."""

    def setUp(self):
        self.factory = RequestFactory()
        self.equipo = make_user(email="equipo@catpuccino.test", is_superuser=True, is_staff=True)
        self.rescatista = make_user()

    def abrir(self, user=None):

        from catus.views.tools import AnimalesSinPosteoView

        request = self.factory.get("/tools/animalessinposteo/")
        request.user = user or self.equipo
        response = AnimalesSinPosteoView.as_view(template_name="tools/animalessinposteo.html")(request)
        if hasattr(response, "render") and not response.is_rendered:
            response.render()
        return response.content.decode()

    def test_un_usuario_comun_no_entra(self):

        self.assertIn("No tenes permisos", self.abrir(self.rescatista))

    def test_lista_lo_aprobado_que_no_tiene_posteo_con_el_link_a_las_imagenes(self):

        animal = make_animal(nombre="SinPosteo", cargado_por=self.rescatista, aprobado=True)

        cuerpo = self.abrir()

        self.assertIn("SinPosteo", cuerpo)
        self.assertIn('href="/tools/generarimagen/{}/"'.format(animal.id), cuerpo)

    def test_no_repite_lo_que_esta_en_la_cola_de_instagram_ni_lo_que_ya_salio(self):

        make_animal(nombre="Agendado", cargado_por=self.rescatista, aprobado=True,
                    instagram_programado_para=timezone.now() + timedelta(hours=1))
        make_animal(nombre="Listo", cargado_por=self.rescatista, aprobado=True, instagram_listo_para_publicar=True)
        make_animal(nombre="ConError", cargado_por=self.rescatista, aprobado=True, instagram_error="Falló")
        make_animal(nombre="YaSalio", cargado_por=self.rescatista, aprobado=True, instagram_publicado=True)
        make_animal(nombre="SinAprobar", cargado_por=self.rescatista, aprobado=False)
        make_animal(nombre="Adoptado", cargado_por=self.rescatista, aprobado=True, estado="A")

        cuerpo = self.abrir()

        for nombre in ("Agendado", "Listo", "ConError", "YaSalio", "SinAprobar", "Adoptado"):
            self.assertNotIn(">{}<".format(nombre), cuerpo, nombre)
