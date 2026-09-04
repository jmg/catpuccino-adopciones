"""Tests del posteo automático: aprobar agenda la publicación en Instagram.

La demora entre aprobar y postear es el único gate humano que queda. `aprobado=True`
no garantiza que alguien haya mirado la publicación: el comando automatic_approve deja
aprobando solos a los rescatistas con historial, así que para el segundo animal en
adelante nadie la mira. De ahí las dos reglas que se prueban acá:

  1. Lo que se agenda se tiene que poder cancelar, y cancelado tiene que quedar.
  2. Agendar no puede hacer fallar una aprobación. Si el servicio se rompe, el animal
     queda aprobado igual y el equipo publica a mano desde /tools/, como siempre.
"""
import io
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.forms.models import modelform_factory
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from catus.admin import AnimalAdmin
from catus.management.commands.publish import Command as PublishCommand
from catus.models import Animal
from catus.services.instagram_auto import InstagramAutoService
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo
from catus.views.animal import AprobarView, EditView


def form_del_listado(animal, campos=("aprobado",), **datos):
    """El form que arma el admin cuando se toca un tilde del listado (list_editable).

    Se usa el form de verdad y no un doble porque lo que decide si se agenda es
    form.changed_data: con un doble, cambiar esa condición dejaba el test en verde.
    """

    FormDelAnimal = modelform_factory(Animal, fields=list(campos))
    form = FormDelAnimal(datos, instance=animal)
    form.is_valid()

    return form


def guardar_en_el_listado(admin, request, animal, campos, **datos):
    """Lo que hace el admin con un tilde del listado: arma el form, guarda y avisa."""

    form = form_del_listado(animal, campos=campos, **datos)
    obj = form.save(commit=False)

    admin.save_model(request, obj, form, change=True)

    return obj


@override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=True)
class AgendarTest(TestCase):
    """Qué se agenda y qué no."""

    def setUp(self):
        self.service = InstagramAutoService()
        self.animal = make_animal(nombre="Willy", aprobado=True)

    def agendar(self):

        agendado = self.service.agendar(self.animal)
        self.animal.refresh_from_db()

        return agendado

    def test_aprobar_agenda_el_posteo_para_mas_tarde(self):

        self.assertTrue(self.agendar())

        self.assertIsNotNone(self.animal.instagram_programado_para)
        self.assertGreater(
            self.animal.instagram_programado_para, timezone.now(),
            "el posteo quedó agendado en el pasado: para el cron eso es publicar ya",
        )

    def test_agendar_dos_veces_no_corre_la_hora(self):
        """El link "Aprobar!" del mail se puede apretar dos veces, y el admin guarda el
        mismo animal muchas veces: si cada guardado reagendara, el posteo se iría
        corriendo para adelante y no saldría nunca."""

        self.agendar()
        primera = self.animal.instagram_programado_para

        self.assertFalse(self.agendar(), "reagendó un posteo que ya estaba agendado")
        self.assertEqual(self.animal.instagram_programado_para, primera)

    def test_dos_aprobaciones_a_la_vez_agendan_una_sola_vez(self):
        """El candado está en la base, no en el objeto que cada request tiene en memoria.

        Dos personas del equipo abren el mail "Aprobar!" del mismo animal y aprietan casi
        juntas: los dos requests levantan el animal ANTES de que ninguno agende, así que
        para los dos `instagram_programado_para` es None en memoria y el chequeo en Python
        los deja pasar a los dos. Lo único que decide es el update con
        `instagram_programado_para__isnull=True`: el segundo tiene que actualizar 0 filas.
        Sin eso, la segunda aprobación corre la hora hacia adelante y el posteo se atrasa
        en cada click.
        """

        uno = Animal.objects.get(id=self.animal.id)
        otro = Animal.objects.get(id=self.animal.id)

        self.assertTrue(self.service.agendar(uno))

        #`otro` sigue con la fecha en None, como la tenía al levantarlo de la base
        self.assertIsNone(otro.instagram_programado_para)
        self.assertFalse(self.service.agendar(otro), "agendó dos veces el mismo animal")

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.instagram_programado_para, uno.instagram_programado_para)

    def test_no_agenda_lo_que_la_ia_marco_para_revisar(self):
        """Lo que la revisión automática marcó no puede salir solo a la cuenta pública."""

        self.animal.revision_ia_estado = Animal.REVISION_REVISAR
        self.animal.save()

        self.assertFalse(self.agendar())
        self.assertIsNone(self.animal.instagram_programado_para)

    def test_lo_que_la_ia_no_pudo_revisar_se_agenda_igual(self):
        """La invariante de moderacion.py: 'E' es un fallo nuestro, no sospecha de nadie.

        Sólo 'R' retiene. Si 'E' o 'P' frenaran el posteo, quedarse sin crédito en la
        API de OpenAI dejaría al refugio sin publicaciones automáticas.
        """

        for estado in (Animal.REVISION_ERROR, Animal.REVISION_PENDIENTE, Animal.REVISION_OK):

            animal = make_animal(nombre="Willy {}".format(estado), aprobado=True, revision_ia_estado=estado)

            self.assertTrue(
                self.service.agendar(animal), "no se agendó un animal con revisión {}".format(estado),
            )

    def test_no_agenda_lo_que_no_esta_aprobado(self):

        self.animal.aprobado = False
        self.animal.save()

        self.assertFalse(self.agendar())
        self.assertIsNone(self.animal.instagram_programado_para)

    def test_no_reagenda_lo_que_ya_se_publico(self):
        """Volver a agendar un animal ya posteado lo publicaría dos veces."""

        self.animal.instagram_publicado = True
        self.animal.save()

        self.assertFalse(self.agendar())
        self.assertIsNone(self.animal.instagram_programado_para)


class EntornoTest(TestCase):
    """El mismo criterio que ModeracionService: no se dispara desde una máquina de
    desarrollo, y se puede apagar desde la config sin tocar código."""

    @override_settings(ENV="LOCAL")
    def test_en_local_no_se_agenda_nada(self):

        animal = make_animal(nombre="Willy", aprobado=True)

        self.assertFalse(InstagramAutoService().agendar(animal))

        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_programado_para)

    def test_el_default_de_settings_es_apagado(self):
        """SIN override: mira el valor real que arma settings.py.

        Es la única propiedad de todo esto que no se puede equivocar. Los demás tests
        prenden el flag con override_settings, así que ninguno se enteraría si alguien
        cambia el default a True; y ese día el próximo `git pull` a producción —que es
        todo lo que hace deploy.sh— pone a publicar en la cuenta real del refugio sin que
        nadie lo haya pedido. El config de tests no trae la clave, igual que producción.
        """

        self.assertFalse(
            settings.INSTAGRAM_AUTO_ACTIVO,
            "el posteo automático tiene que arrancar apagado y prenderse a mano desde la config",
        )

    @override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO="0")
    def test_se_apaga_desde_la_config(self):
        """read_config devuelve todo como string: un "0" en el JSON llega como texto y
        en Python cualquier string no vacío es verdadero. Sin normalizarlo, apagar el
        posteo automático desde la config no apagaba nada."""

        self.assertFalse(InstagramAutoService().esta_activo())

    @override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=None)
    def test_sin_la_clave_en_la_config_queda_apagado(self):
        """Postear en la cuenta de la organización es irreversible y se ve de afuera.

        Prenderlo tiene que ser una decisión de alguien, no algo que empiece a pasar solo
        en el próximo deploy: deploy.sh es un git pull, así que si la ausencia de la clave
        significara "prendido", el día que esto sube el sitio arrancaría a publicar sin
        que nadie lo haya pedido. Un valor que no sabemos leer también cuenta como apagado.
        """

        self.assertFalse(InstagramAutoService().esta_activo())


@override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=True)
class DemoraTest(TestCase):
    """La demora es la ventana para cancelar: si se va a cero, no queda ninguna."""

    def setUp(self):
        self.animal = make_animal(nombre="Willy", aprobado=True)

    def falta(self):

        self.animal.refresh_from_db()

        return self.animal.instagram_programado_para - timezone.now()

    @override_settings(INSTAGRAM_AUTO_DEMORA_MINUTOS="45")
    def test_la_demora_sale_de_la_config_aunque_venga_como_texto(self):

        InstagramAutoService().agendar(self.animal)

        self.assertGreater(self.falta(), timedelta(minutes=44))
        self.assertLess(self.falta(), timedelta(minutes=46))

    @override_settings(INSTAGRAM_AUTO_DEMORA_MINUTOS="media hora")
    def test_una_demora_ilegible_no_rompe_la_aprobacion(self):
        """timedelta(minutes="media hora") revienta, y esto cuelga de la aprobación."""

        self.assertTrue(InstagramAutoService().agendar(self.animal))

        self.assertGreater(self.falta(), timedelta(minutes=25))

    @override_settings(INSTAGRAM_AUTO_DEMORA_MINUTOS=0)
    def test_una_demora_en_cero_no_borra_la_ventana_para_cancelar(self):
        """Agendar en el pasado es "publicá ya" para el cron: nadie llega a cancelarlo."""

        InstagramAutoService().agendar(self.animal)

        self.assertGreater(self.falta(), timedelta(minutes=25))


@override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=True)
class CancelarTest(TestCase):
    """Cancelar tiene que sacar al animal de la cola del cron, no adelantarlo."""

    def setUp(self):
        #las imágenes de Instagram son archivos de verdad: que caigan en un directorio
        #descartable y no en la galería del repo
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.service = InstagramAutoService()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def animal_en_camino(self, **kwargs):
        """Un animal aprobado, con la imagen armada y el posteo ya agendado."""

        kwargs.setdefault("aprobado", True)
        kwargs.setdefault("estado", "D")
        kwargs.setdefault("instagram_listo_para_publicar", True)

        animal = make_animal(nombre="Willy", **kwargs)

        imagen = make_animal_image(animal=animal, posicion=1)
        imagen.image_for_instagram.save("insta.jpg", uploaded_photo(), save=True)

        self.service.agendar(animal)

        return animal

    def cola(self):

        return list(PublishCommand().animales_de_esta_corrida())

    def test_cancelar_lo_saca_de_la_cola_del_cron(self):
        """Borrar sólo la fecha no cancela: para el cron un animal listo y sin fecha es
        uno del flujo viejo, o sea "publicá ya", así que cancelar el posteo lo hacía
        salir en la corrida siguiente en vez de frenarlo."""

        animal = self.animal_en_camino()

        self.assertTrue(self.service.cancelar(animal))

        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_programado_para)
        self.assertNotIn(animal, self.cola(), "el posteo cancelado salió igual")

    def test_cancelar_anda_con_el_posteo_automatico_apagado(self):
        """Si cancelar mirara el flag, apagarlo dejaría sin frenar lo ya agendado."""

        animal = self.animal_en_camino()

        with override_settings(INSTAGRAM_AUTO_ACTIVO="0"):
            self.assertTrue(self.service.cancelar(animal))

        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_programado_para)

    def test_lo_ya_publicado_no_se_toca(self):
        """El post no vuelve: no hay nada que cancelar y apagarle la marca de publicado
        sólo confundiría al listado del equipo."""

        animal = self.animal_en_camino(instagram_publicado=True)

        self.assertFalse(self.service.cancelar(animal))

    def test_cancelar_limpia_el_motivo_del_ultimo_fallo(self):
        """El animal cancelado quedaba para siempre en "Con problemas" de la pantalla.

        instagram_error lo escribe el cron cuando no puede preparar o publicar, y es lo
        que arma ese grupo en /tools/colainstagram/. Cancelar es justo el momento en que
        ese motivo dejó de describir nada: el posteo ya no va a salir, así que no falló.
        Quedaba mostrando un error de un posteo que ya no existe, y encima lo sacaba de
        los grupos "Agendados" y "En cola", que filtran por SIN_ERROR.
        """

        animal = self.animal_en_camino()
        Animal.objects.filter(id=animal.id).update(
            instagram_error="No se pudo armar la imagen de la foto 3: cannot identify image file",
        )
        animal.refresh_from_db()

        self.assertTrue(self.service.cancelar(animal))

        #también en el objeto en memoria, que es el que sigue usando quien acaba de cancelar
        self.assertFalse(animal.instagram_error, "el motivo le quedó pegado al animal en memoria")

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_error, "el posteo cancelado sigue contando como fallado")


@override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=True)
class CaminosDeAprobacionTest(TestCase):
    """Los tres caminos por los que un animal pasa a aprobado=True agendan el posteo.

    Si alguno se queda afuera, ese animal no se publica nunca solo y nadie se entera:
    no hay error, simplemente no sale.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.admin = AnimalAdmin(Animal, AdminSite())
        self.equipo = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)
        self.animal = make_animal(nombre="Willy", aprobado=False, cargado_por=make_user())

    def request_del_admin(self):

        request = self.factory.post("/")
        request.user = self.equipo
        request.session = {}
        request._messages = FallbackStorage(request)

        return request

    def aprobar_por_el_link_del_mail(self):

        request = self.factory.get("/", {"id": self.animal.id})
        request.user = self.equipo

        return AprobarView.as_view()(request)

    def test_el_link_aprobar_del_mail_agenda(self):

        self.aprobar_por_el_link_del_mail()

        self.animal.refresh_from_db()
        self.assertTrue(self.animal.aprobado)
        self.assertIsNotNone(self.animal.instagram_programado_para, "aprobar no agendó el posteo")

    def test_la_accion_del_admin_agenda(self):

        self.admin.aprobar_animales(self.request_del_admin(), Animal.objects.filter(id=self.animal.id))

        self.animal.refresh_from_db()
        self.assertTrue(self.animal.aprobado)
        self.assertIsNotNone(self.animal.instagram_programado_para, "aprobar no agendó el posteo")

    def test_el_tilde_de_aprobado_del_listado_agenda(self):
        """`aprobado` está en list_editable: se aprueba con un tilde en el listado, sin
        pasar por la acción en lote ni por el link del mail."""

        form = form_del_listado(self.animal, aprobado="on")
        animal = form.save(commit=False)

        self.admin.save_model(self.request_del_admin(), animal, form, change=True)

        self.animal.refresh_from_db()
        self.assertTrue(self.animal.aprobado)
        self.assertIsNotNone(self.animal.instagram_programado_para, "aprobar no agendó el posteo")

    def test_destildar_aprobado_cancela_el_posteo(self):
        """Desaprobar es la forma de frenar una publicación que ya estaba en camino."""

        self.animal.aprobado = True
        self.animal.save()
        InstagramAutoService().agendar(self.animal)

        form = form_del_listado(self.animal)
        animal = form.save(commit=False)

        self.admin.save_model(self.request_del_admin(), animal, form, change=True)

        self.animal.refresh_from_db()
        self.assertFalse(self.animal.aprobado)
        self.assertIsNone(self.animal.instagram_programado_para, "el posteo del animal desaprobado sigue agendado")

    def test_guardar_en_el_admin_sin_tocar_aprobado_no_reagenda(self):
        """El equipo entra a corregir un dato de un animal cuyo posteo se canceló: si
        cada guardado reagendara, la cancelación no duraría nada."""

        self.animal.aprobado = True
        self.animal.save()

        form = form_del_listado(self.animal, aprobado="on")
        animal = form.save(commit=False)

        self.admin.save_model(self.request_del_admin(), animal, form, change=True)

        self.animal.refresh_from_db()
        self.assertIsNone(self.animal.instagram_programado_para)

    def test_si_agendar_explota_la_aprobacion_igual_queda_hecha(self):
        """Mismo criterio que ModeracionService con el alta: esto cuelga de la
        aprobación y no puede tumbarla. Sin posteo automático se publica a mano; con
        una excepción acá, el equipo ve un 500 y el animal se queda sin aprobar."""

        with mock.patch.object(InstagramAutoService, "esta_activo", side_effect=RuntimeError("boom")):
            response = self.aprobar_por_el_link_del_mail()

        self.animal.refresh_from_db()
        self.assertTrue(self.animal.aprobado, "se perdió la aprobación porque falló el posteo automático")
        self.assertEqual(response.status_code, 200)


@override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=True)
class AutoAprobacionTest(TestCase):
    """El camino que más importa: el alta que se auto-aprueba sola.

    Es donde no miró nadie, así que es el que de verdad necesita la ventana para
    cancelar. Va por EditView a propósito: copiar la condición adentro del test dejaría
    todo en verde aunque la vista dejara de agendar.
    """

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.factory = RequestFactory()
        self.rescatista = make_user(email="rescatista@catpuccino.test", automatic_approve=True)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def dar_de_alta(self):

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

        #se mockea sólo lo que sale a la red
        with mock.patch("catus.views.animal.MailService"):
            view.req(is_post=True)

        animal = Animal.objects.filter(nombre="Willy").first()
        self.assertIsNotNone(animal, "el alta no guardó el animal: el POST del test quedó viejo")

        return animal

    def test_el_alta_auto_aprobada_queda_agendada(self):

        animal = self.dar_de_alta()

        self.assertTrue(animal.aprobado)
        self.assertIsNotNone(animal.instagram_programado_para, "el alta auto-aprobada no agendó el posteo")

    def test_si_agendar_explota_el_alta_igual_se_guarda(self):
        """El rescatista está esperando este POST: una excepción acá le devuelve un 500
        con el animal ya guardado."""

        with mock.patch.object(InstagramAutoService, "esta_activo", side_effect=RuntimeError("boom")):
            animal = self.dar_de_alta()

        self.assertTrue(animal.aprobado, "se perdió el alta porque falló el posteo automático")
        self.assertIsNone(animal.instagram_programado_para)


@override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=True)
class FrenoDelAdminTest(TestCase):
    """El freno de mano del listado del admin: destildar "listo para publicar".

    En el flujo viejo ese tilde era lo único que decidía si un animal salía, así que es
    el gesto que el equipo tiene aprendido. Con el posteo automático dejó de frenar nada:
    la agenda vencida seguía puesta y `preparar_publicaciones` volvía a prender la marca
    en la corrida siguiente.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.admin = AnimalAdmin(Animal, AdminSite())
        self.equipo = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)

    def request_del_admin(self):

        request = self.factory.post("/")
        request.user = self.equipo
        request.session = {}
        request._messages = FallbackStorage(request)

        return request

    def animal_marcado(self, **kwargs):
        """Un animal aprobado, agendado y ya marcado como listo por el cron."""

        kwargs.setdefault("aprobado", True)
        animal = make_animal(nombre="Willy", **kwargs)

        InstagramAutoService().agendar(animal)
        Animal.objects.filter(id=animal.id).update(instagram_listo_para_publicar=True)
        animal.refresh_from_db()

        return animal

    def test_destildar_listo_para_publicar_cancela_el_posteo(self):
        """Destildarlo tiene que apagar también la agenda, o no frena nada.

        El equipo destildaba, veía la marca apagada, y a los minutos el animal salía igual
        porque el cron lo levantaba por la agenda vencida y la volvía a prender.
        """

        animal = self.animal_marcado()

        #el checkbox destildado no viaja en el POST: la clave directamente no está
        guardar_en_el_listado(
            self.admin, self.request_del_admin(), animal, ["instagram_listo_para_publicar"],
        )

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar)
        self.assertIsNone(
            animal.instagram_programado_para,
            "la agenda quedó puesta: el cron le vuelve a prender la marca",
        )

    def test_marcar_listo_a_mano_no_borra_la_agenda(self):
        """La contraparte: tildarlo es adelantar el posteo, no cancelarlo.

        Si el cambio a True también cancelara, marcar un animal como listo lo sacaría de
        la cola en vez de meterlo.
        """

        animal = make_animal(nombre="Willy", aprobado=True)
        InstagramAutoService().agendar(animal)
        animal.refresh_from_db()
        agendado = animal.instagram_programado_para

        guardar_en_el_listado(
            self.admin, self.request_del_admin(), animal, ["instagram_listo_para_publicar"],
            instagram_listo_para_publicar="on",
        )

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_listo_para_publicar)
        self.assertEqual(animal.instagram_programado_para, agendado, "marcar listo canceló el posteo")

    def test_guardar_sin_tocar_la_marca_no_cancela_nada(self):
        """Se mira el cambio y no el valor: la mayoría de los animales están sin marcar,
        y cancelar en cada guardado le borraría la agenda a todos los que se toquen por
        cualquier otra cosa."""

        animal = make_animal(nombre="Willy", aprobado=True)
        InstagramAutoService().agendar(animal)
        animal.refresh_from_db()
        agendado = animal.instagram_programado_para

        #se toca otro tilde del listado; el de la marca ni aparece en el form
        guardar_en_el_listado(self.admin, self.request_del_admin(), animal, ["estado"], estado="R")

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "R")
        self.assertEqual(animal.instagram_programado_para, agendado, "guardar canceló el posteo")


@override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=True)
class NingunCronResucitaUnPosteoFrenadoTest(TestCase):
    """LA regla: una vez que alguien frena un posteo, ningún cron lo puede resucitar solo.

    Los frenos son varios y cada uno se aprieta en otro lado, pero quien decide si el
    animal sale son los dos cron: `preparar_publicaciones` lo levanta por la agenda y le
    prende la marca de listo, y `publish` saca a los marcados. Así que todos los frenos se
    prueban igual: se frena, corren los dos cron, y el animal tiene que seguir frenado.

    Lo que se revierte solo es la agenda: `instagram_programado_para` no se limpiaba
    nunca, quedaba vencida para siempre, y cada corrida de `preparar_publicaciones` volvía
    a marcar como listo al animal que alguien acababa de frenar.
    """

    def setUp(self):
        #preparar_publicaciones arma imágenes de verdad: que caigan en un directorio
        #descartable y no en la galería del repo
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.factory = RequestFactory()
        self.admin = AnimalAdmin(Animal, AdminSite())
        self.equipo = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def request_del_admin(self):

        request = self.factory.post("/")
        request.user = self.equipo
        request.session = {}
        request._messages = FallbackStorage(request)

        return request

    def animal_en_camino(self):
        """Aprobado, con una foto cargada y la agenda ya vencida: le toca al cron.

        La foto va sin image_for_instagram a propósito: así `preparar_publicaciones` tiene
        algo que hacer con el animal y el test se entera si lo levanta.
        """

        animal = make_animal(nombre="Willy", aprobado=True, estado="D")
        make_animal_image(animal=animal, posicion=1)

        Animal.objects.filter(id=animal.id).update(
            instagram_programado_para=timezone.now() - timedelta(minutes=1),
            instagram_listo_para_publicar=True,
        )
        animal.refresh_from_db()

        return animal

    def correr_los_cron(self):
        """Las dos corridas, en el mismo orden que el crontab."""

        salida = io.StringIO()
        call_command("preparar_publicaciones", stdout=salida, stderr=salida)
        call_command("publish", stdout=salida, stderr=salida)

        return salida.getvalue()

    def assert_sigue_frenado(self, animal):

        animal.refresh_from_db()

        self.assertIsNone(
            animal.instagram_programado_para,
            "la agenda vencida sigue puesta: el cron va a levantar el posteo frenado",
        )
        self.assertFalse(
            animal.instagram_listo_para_publicar,
            "el cron le volvió a prender la marca al posteo que alguien frenó",
        )
        self.assertFalse(animal.instagram_publicado, "el posteo frenado salió igual")
        self.assertNotIn(animal, list(PublishCommand().animales_de_esta_corrida()))

    def test_cancelar_desde_la_pantalla_de_la_cola(self):
        """El botón "Cancelar" de /tools/colainstagram/, que es lo que hace el servicio."""

        animal = self.animal_en_camino()

        self.assertTrue(InstagramAutoService().cancelar(animal))

        self.correr_los_cron()
        self.assert_sigue_frenado(animal)

    def test_destildar_aprobado_en_el_listado_del_admin(self):
        """Desaprobar es el freno más a mano: saca al animal de la web y del posteo."""

        animal = self.animal_en_camino()

        guardar_en_el_listado(self.admin, self.request_del_admin(), animal, ["aprobado"])

        self.correr_los_cron()
        self.assert_sigue_frenado(animal)

    def test_destildar_listo_para_publicar_en_el_listado_del_admin(self):
        """El freno de mano del flujo viejo, que es el que el equipo tiene aprendido."""

        animal = self.animal_en_camino()

        guardar_en_el_listado(
            self.admin, self.request_del_admin(), animal, ["instagram_listo_para_publicar"],
        )

        self.correr_los_cron()
        self.assert_sigue_frenado(animal)

    def test_el_que_no_se_frena_sale_igual(self):
        """La contraparte, que es la que dice que los cron de verdad corrieron.

        Sin esto, cualquier arreglo que rompiera el pipeline entero dejaría los tres
        tests de arriba en verde: nada sale nunca y nada se resucita.
        """

        animal = self.animal_en_camino()

        self.correr_los_cron()

        animal.refresh_from_db()
        self.assertTrue(
            animal.instagram_listo_para_publicar,
            "el cron no preparó un animal que nadie frenó: los tests de al lado no prueban nada",
        )
