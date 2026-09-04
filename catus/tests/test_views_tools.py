"""Tests de las herramientas del equipo (/tools/).

Todo lo que hay acá es de administración: publicar en Instagram, generar
imágenes, mandar mails. Nada debería estar abierto.
"""
import shutil
import tempfile

from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catus.models import Animal
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo


def cola_de_publish():
    """La cola del cron que postea. Usa el filtro real del comando, no una copia."""

    from catus.management.commands.publish import Command

    return list(Command().animales_a_publicar())


def cola_de_preparar():
    """La cola del cron que arma las imágenes y deja listo. La del comando, no una copia."""

    from catus.management.commands.preparar_publicaciones import Command

    return list(Command().animales_a_preparar())


class ToolsViewTestCase(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.cualquiera = make_user(email="cualquiera@ejemplo.test")
        self.admin = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)
        self.rescatista = make_user(email="rescatista@catpuccino.test")

    def call(self, view_class, user, method="post", data=None, **kwargs):

        request = getattr(self.factory, method)("/", data or {})
        request.user = user
        return view_class.as_view()(request, **kwargs)


class ToolsIndexViewTest(ToolsViewTestCase):
    """El índice de /tools/. La herramienta que no está acá no existe: no hay menú, no hay
    link desde ningún lado y las URLs de /tools/ hay que saberlas de memoria."""

    def abrir(self, user):
        """django-conventions deriva template_name del módulo+clase al armar el urlconf;
        acá las vistas se llaman directo, así que hay que pasárselo."""

        from catus.views.tools import ToolsIndexView

        request = self.factory.get("/tools/")
        request.user = user
        response = ToolsIndexView.as_view(template_name="tools/toolsindex.html")(request)

        #TemplateResponse llega sin renderizar cuando se llama a la vista directo
        if hasattr(response, "render") and not response.is_rendered:
            response.render()

        return response

    def agendar(self, nombre, minutos=30, **kwargs):

        return make_animal(
            nombre=nombre, cargado_por=self.rescatista,
            instagram_programado_para=timezone.now() + timedelta(minutes=minutos),
            **kwargs
        )

    def test_un_usuario_comun_no_entra(self):

        self.assertIn("No tenes permisos", self.abrir(self.cualquiera).content.decode())

    def test_enlaza_la_cola_de_instagram(self):
        """La cola era la única pantalla que no figuraba acá, y es el único lugar donde una
        persona puede frenar un posteo automático antes de que salga: había que saberse la
        URL de memoria para llegar."""

        self.assertIn("/tools/colainstagram/", self.abrir(self.admin).content.decode())

    def test_muestra_cuantos_hay_agendados(self):
        """Para que se vea de un vistazo que hay algo por salir, sin entrar a mirar."""

        self.agendar("Uno")
        self.agendar("Dos")

        self.assertIn("2 agendados", self.abrir(self.admin).content.decode())

    def test_no_cuenta_los_que_ya_salieron(self):
        """Contar posteos que ya se publicaron es mandar al equipo a frenar lo que no se
        puede frenar: el post ya está en la cuenta de la organización."""

        self.agendar("YaSalio", instagram_publicado=True)

        self.assertIn("Sin agendar", self.abrir(self.admin).content.decode())

    def test_no_cuenta_los_que_ya_les_toco(self):
        """Los vencidos ya no se pueden frenar por acá: el número es la ventana que queda."""

        self.agendar("Vencido", minutos=-5)

        self.assertIn("Sin agendar", self.abrir(self.admin).content.decode())


class SendPreguntarEmailViewTest(ToolsViewTestCase):
    """Manda un mail con contenido libre al rescatista que se le indique.

    Sin control de acceso esto era un relay abierto: cualquiera podía mandar
    HTML arbitrario a cualquier usuario registrado, desde el dominio del sitio.
    """

    def setUp(self):
        super().setUp()
        make_animal(cargado_por=self.rescatista, estado="D", aprobado=True)

    def enviar(self, user):

        from catus.views.tools import SendPreguntarEmailView

        return self.call(SendPreguntarEmailView, user, data={
            "user_id": self.rescatista.id,
            "content": "<b>hola</b>",
        })

    @override_settings(ENV="TEST")
    def test_un_anonimo_no_puede_mandar_mails(self):

        self.enviar(AnonymousUser())

        self.assertEqual(len(mail.outbox), 0, "un anónimo mandó un mail desde el sitio")

    @override_settings(ENV="TEST")
    def test_un_usuario_comun_no_puede_mandar_mails(self):

        self.enviar(self.cualquiera)

        self.assertEqual(len(mail.outbox), 0, "un usuario común mandó un mail desde el sitio")

    @override_settings(ENV="TEST")
    def test_un_user_id_inexistente_no_rompe(self):

        from catus.views.tools import SendPreguntarEmailView

        response = self.call(SendPreguntarEmailView, self.admin, data={
            "user_id": 999999, "content": "hola",
        })

        self.assertEqual(response.status_code, 200)


class DownloadImagesViewTest(ToolsViewTestCase):

    def descargar(self, user, animal_id):

        from catus.views.tools import DownloadImagesView

        return self.call(DownloadImagesView, user, method="get", animal_id=str(animal_id))

    def test_un_usuario_comun_no_descarga(self):

        animal = make_animal(cargado_por=self.rescatista)

        response = self.descargar(self.cualquiera, animal.id)

        self.assertNotEqual(response.get("Content-Type"), "application/octet-stream")

    def test_un_animal_inexistente_no_rompe(self):

        response = self.descargar(self.admin, 999999)

        self.assertEqual(response.status_code, 200)

    def test_sin_imagenes_generadas_no_rompe(self):
        """Antes explotaba al leer image_for_instagram de una foto sin procesar."""

        animal = make_animal(cargado_por=self.rescatista)
        make_animal_image(animal=animal)

        response = self.descargar(self.admin, animal.id)

        self.assertEqual(response.status_code, 200)


class SaveFormViewTest(ToolsViewTestCase):

    def test_un_usuario_comun_no_marca_listo_para_publicar(self):

        from catus.views.tools import SaveFormView

        animal = make_animal(cargado_por=self.rescatista)

        self.call(SaveFormView, self.cualquiera, data={
            "animal_id": animal.id, "instagram_listo_para_publicar": "1",
        })

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar)

    def test_un_animal_inexistente_no_rompe(self):

        from catus.views.tools import SaveFormView

        response = self.call(SaveFormView, self.admin, data={"animal_id": 999999})

        self.assertEqual(response.status_code, 200)


class MarcarListoParaInstagramTest(ToolsViewTestCase):
    """El botón "Listo para Instagram" decide qué publica el cron."""

    def toggle(self, animal, valor):

        from catus.views.tools import SaveFormView

        return self.call(SaveFormView, self.admin, data={
            "animal_id": animal.id,
            "instagram_listo_para_publicar": valor,
        })

    def test_marcar_lo_deja_listo(self):

        animal = make_animal(cargado_por=self.rescatista)

        self.toggle(animal, "on")

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_listo_para_publicar)

    def test_desmarcar_lo_saca_de_la_cola(self):
        """El botón manda "" al desmarcar; antes eso lo dejaba marcado igual."""

        animal = make_animal(cargado_por=self.rescatista, instagram_listo_para_publicar=True)

        self.toggle(animal, "")

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar, "desmarcar no tuvo efecto")

    def agendado_y_listo(self):
        """Como queda un animal del pipeline automático al que ya le venció la agenda."""

        return make_animal(
            cargado_por=self.rescatista,
            instagram_listo_para_publicar=True,
            instagram_programado_para=timezone.now() - timedelta(minutes=5),
        )

    def test_desmarcar_tambien_limpia_la_agenda(self):
        """Desmarcar es un gesto de freno, y frenar tiene que sacarlo de la cola entera."""

        animal = self.agendado_y_listo()

        self.toggle(animal, "")

        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_programado_para, "la agenda quedó puesta")

    def test_ningun_cron_lo_resucita_despues_de_desmarcarlo(self):
        """Apagando sólo la marca, la agenda quedaba vencida para siempre: en la corrida
        siguiente preparar_publicaciones levantaba al animal por la agenda y le volvía a
        prender la marca, así que el freno se revertía solo y el posteo salía igual."""

        animal = self.agendado_y_listo()

        self.toggle(animal, "")

        animal.refresh_from_db()
        self.assertNotIn(animal, cola_de_preparar(), "el cron que prepara lo volvió a levantar")
        self.assertNotIn(animal, cola_de_publish(), "el cron que publica lo volvió a levantar")


class PublishCommandTest(TestCase):
    """A qué animales alcanza el cron de publicación."""

    def animales_a_publicar(self):
        """Usa el filtro real del comando, no una copia."""

        from catus.management.commands.publish import Command

        return list(Command().animales_a_publicar())

    def test_publica_los_que_estan_en_adopcion(self):

        animal = make_animal(instagram_listo_para_publicar=True, aprobado=True, estado="D")

        self.assertIn(animal, self.animales_a_publicar())

    def test_no_publica_un_animal_ya_adoptado(self):
        """Se marcaba listo el lunes, se adoptaba el martes y el cron lo publicaba igual."""

        animal = make_animal(instagram_listo_para_publicar=True, aprobado=True, estado="A")

        self.assertNotIn(animal, self.animales_a_publicar())

    def test_no_publica_un_animal_sin_aprobar(self):

        animal = make_animal(instagram_listo_para_publicar=True, aprobado=False, estado="D")

        self.assertNotIn(animal, self.animales_a_publicar())

    def test_no_republica_lo_ya_publicado(self):

        animal = make_animal(
            instagram_listo_para_publicar=True, aprobado=True, estado="D",
            instagram_publicado=True,
        )

        self.assertNotIn(animal, self.animales_a_publicar())


class ComentarioDeAdoptadoEnInstagramTest(TestCase):
    """El cron que comenta en el post de Instagram cuando el animal encuentra hogar."""

    def animales_a_comentar(self):
        """Usa el filtro real del comando, no una copia."""

        from catus.management.commands.update_status_in_ig import Command

        return list(Command().animales_a_comentar())

    def publicado(self, **kwargs):

        kwargs.setdefault("instagram_publicado", True)
        kwargs.setdefault("instagram_post_id", "123")
        return make_animal(**kwargs)

    def test_comenta_en_los_adoptados(self):

        animal = self.publicado(estado="A")

        self.assertIn(animal, self.animales_a_comentar())

    def test_no_comenta_en_los_reservados(self):
        """Decía "Ya fue adoptado" sobre un animal solo reservado, y no se podía corregir."""

        animal = self.publicado(estado="R")

        self.assertNotIn(animal, self.animales_a_comentar())

    def test_no_comenta_dos_veces(self):

        animal = self.publicado(estado="A", instagram_comment_id="456")

        self.assertNotIn(animal, self.animales_a_comentar())

    def test_no_comenta_en_los_que_no_se_publicaron(self):

        animal = make_animal(estado="A", instagram_publicado=False)

        self.assertNotIn(animal, self.animales_a_comentar())


class AnimalesPendientesViewTest(ToolsViewTestCase):
    """La pantalla donde el equipo revisa lo que falta aprobar."""

    def abrir(self, user):
        """django-conventions deriva template_name del módulo+clase al armar el urlconf;
        acá las vistas se llaman directo, así que hay que pasárselo."""

        from catus.views.tools import AnimalesPendientesView

        request = self.factory.get("/tools/animalespendientes/")
        request.user = user
        response = AnimalesPendientesView.as_view(
            template_name="tools/animalespendientes.html",
        )(request)

        #TemplateResponse llega sin renderizar cuando se llama a la vista directo
        if hasattr(response, "render") and not response.is_rendered:
            response.render()

        return response

    def test_un_usuario_comun_no_entra(self):

        response = self.abrir(self.cualquiera)

        self.assertIn("No tenes permisos", response.content.decode())

    def test_lista_los_que_faltan_aprobar(self):

        animal = make_animal(nombre="Willy", cargado_por=self.rescatista, aprobado=False)

        response = self.abrir(self.admin)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Willy", response.content.decode())

    def test_no_lista_los_adoptados(self):

        make_animal(nombre="YaAdoptado", cargado_por=self.rescatista, aprobado=False, estado="A")

        self.assertNotIn("YaAdoptado", self.abrir(self.admin).content.decode())

    def test_los_marcados_por_la_ia_aparecen_primero(self):
        """Es el punto de la pantalla: que lo dudoso se vea sin buscar."""

        from catus.models import Animal

        #el marcado va primero en el tiempo a propósito: como created_at se sella al
        #instanciar, si se creaba último el "-created_at" solo ya lo ponía adelante y el
        #test pasaba igual aunque el orden por revisión de IA no hiciera nada
        make_animal(
            nombre="Sospechoso", cargado_por=self.rescatista, aprobado=False,
            revision_ia_estado=Animal.REVISION_REVISAR,
            revision_ia_motivo="No se ve ningún animal en las fotos.",
        )
        make_animal(nombre="Comun", cargado_por=self.rescatista, aprobado=False)
        make_animal(nombre="Tranquilo", cargado_por=self.rescatista, aprobado=False)

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertLess(
            cuerpo.index("Sospechoso"), cuerpo.index("Comun"),
            "el marcado por la IA no quedó primero",
        )
        self.assertLess(
            cuerpo.index("Sospechoso"), cuerpo.index("Tranquilo"),
            "el marcado por la IA no quedó primero",
        )

    def test_muestra_el_motivo_de_la_ia(self):

        from catus.models import Animal

        make_animal(
            nombre="Sospechoso", cargado_por=self.rescatista, aprobado=False,
            revision_ia_estado=Animal.REVISION_REVISAR,
            revision_ia_motivo="No se ve ningún animal en las fotos.",
        )

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("No se ve ningún animal", cuerpo)
        self.assertIn("Revisar publicación", cuerpo)

    def test_los_animales_viejos_sin_revisar_no_molestan(self):
        """Tras migrar, todos los que ya existen quedan en 'sin revisar'."""

        from catus.models import Animal

        animal = make_animal(nombre="Viejo", cargado_por=self.rescatista, aprobado=False)
        self.assertEqual(animal.revision_ia_estado, Animal.REVISION_PENDIENTE)

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("Viejo", cuerpo)
        self.assertNotIn("Revisar publicación", cuerpo)
        self.assertNotIn("Revisada", cuerpo)

    def test_lista_lo_que_la_ia_marco_aunque_ya_este_aprobado(self):
        """La re-revisión al editar marca animales que ya pasaron todo el pipeline.

        El caso es cargar un animal de verdad, quedar aprobado y con las imágenes listas,
        y después reemplazar fotos y texto por otra cosa. Como esta pantalla es el único
        lugar donde se ve el 'R', dejarlos afuera del filtro hacía que no lo viera nadie.
        """

        from catus.models import Animal

        make_animal(
            nombre="Editado", cargado_por=self.rescatista,
            aprobado=True, instagram_listo_para_publicar=True,
            revision_ia_estado=Animal.REVISION_REVISAR,
            revision_ia_motivo="Las fotos no muestran un animal.",
        )

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("Editado", cuerpo)
        self.assertIn("Revisar publicación", cuerpo)



class ColaInstagramViewTest(ToolsViewTestCase):
    """La pantalla donde el equipo ve y frena lo que Instagram está por publicar solo.

    Es el único gate humano que queda: el posteo se agenda solo al aprobar, y aprobado=True
    no quiere decir que alguien haya mirado, porque automatic_approve deja auto-aprobando
    a cualquiera que ya tenga un animal aprobado.
    """

    def setUp(self):
        super().setUp()

        #make_animal_image escribe archivos de verdad, y sin esto quedan tirados en la
        #carpeta gallery/ del repo
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def abrir(self, user):
        """django-conventions deriva template_name del módulo+clase al armar el urlconf;
        acá las vistas se llaman directo, así que hay que pasárselo."""

        from catus.views.tools import ColaInstagramView

        request = self.factory.get("/tools/colainstagram/")
        request.user = user
        response = ColaInstagramView.as_view(
            template_name="tools/colainstagram.html",
        )(request)

        #TemplateResponse llega sin renderizar cuando se llama a la vista directo
        if hasattr(response, "render") and not response.is_rendered:
            response.render()

        return response

    def accionar(self, user, animal_id, accion):

        from catus.views.tools import ColaInstagramView

        return self.call(ColaInstagramView, user, data={"animal_id": animal_id, "accion": accion})

    def grupos_con(self, animal):
        """En qué grupos de la pantalla quedó el animal."""

        response = self.abrir(self.admin)

        return [
            grupo["clave"] for grupo in response.context_data["grupos"]
            if animal in grupo["animales"]
        ]

    def agendado(self, nombre="Willy", minutos=30, **kwargs):
        """Un animal como lo deja la aprobación: agendado para dentro de un rato."""

        kwargs.setdefault("cargado_por", self.rescatista)
        kwargs.setdefault("instagram_listo_para_publicar", True)
        kwargs.setdefault(
            "instagram_programado_para", timezone.now() + timedelta(minutes=minutos),
        )
        return make_animal(nombre=nombre, **kwargs)

    def trabado(self, nombre="Trabado", **kwargs):
        """Un animal como lo deja un fallo de preparar_publicaciones: sin agenda, sin la
        marca y con el motivo escrito. La agenda es de un solo uso: ahí no vuelve solo."""

        kwargs.setdefault("cargado_por", self.rescatista)
        kwargs.setdefault("instagram_error", "No tiene ninguna foto cargada.")
        kwargs.setdefault("instagram_listo_para_publicar", False)
        kwargs.setdefault("instagram_programado_para", None)
        return make_animal(nombre=nombre, **kwargs)

    def con_imagen_para_instagram(self, animal):
        """Una foto con la imagen del posteo ya armada, como la deja /tools/generarimagen/."""

        imagen = make_animal_image(animal=animal)
        imagen.image_for_instagram.save("ig.jpg", uploaded_photo(), save=True)
        return imagen

    def cola_del_cron(self):
        """Usa el filtro real del comando, no una copia."""

        return cola_de_publish()

    def boton_de_cancelar(self, animal):
        """Si la tarjeta del animal trae el botón para frenarle el posteo."""

        return "accionCola(this, '{}', 'cancelar')".format(animal.id) in self.abrir(self.admin).content.decode()

    def test_un_usuario_comun_no_entra(self):
        """Registrarse es gratis: estar logueado no es un permiso."""

        self.agendado()

        self.assertIn("No tenes permisos", self.abrir(self.cualquiera).content.decode())

    def test_un_anonimo_no_entra(self):

        self.assertIn("No tenes permisos", self.abrir(AnonymousUser()).content.decode())

    def test_un_usuario_comun_no_cancela(self):
        """Cancelar decide qué sale a la cuenta de la organización."""

        animal = self.agendado()

        self.accionar(self.cualquiera, animal.id, "cancelar")

        animal.refresh_from_db()
        self.assertIsNotNone(animal.instagram_programado_para, "un usuario común canceló un posteo")

    def test_un_usuario_comun_no_publica_ya(self):

        animal = self.agendado()
        programado = animal.instagram_programado_para

        self.accionar(self.cualquiera, animal.id, "publicar_ya")

        animal.refresh_from_db()
        self.assertEqual(
            animal.instagram_programado_para, programado, "un usuario común adelantó un posteo",
        )

    def test_el_agendado_a_futuro_espera_en_agendados(self):
        """Es el grupo que importa: el único que todavía se puede frenar."""

        animal = self.agendado(minutos=30)

        self.assertEqual(self.grupos_con(animal), ["agendados"])

    def test_el_agendado_vencido_ya_esta_en_la_cola(self):

        animal = self.agendado(minutos=-5)

        self.assertEqual(self.grupos_con(animal), ["en_cola"])

    def test_el_marcado_a_mano_sin_agenda_esta_en_la_cola(self):
        """El flujo viejo sigue existiendo: se marca a mano desde /tools/makeimages/."""

        animal = make_animal(
            nombre="AMano", cargado_por=self.rescatista,
            instagram_listo_para_publicar=True, instagram_programado_para=None,
        )

        self.assertEqual(self.grupos_con(animal), ["en_cola"])

    def test_el_que_quedo_trabado_va_a_parar_a_con_problemas(self):
        """Hasta ahora el error moría en el stdout del cron y no se veía en ningún lado."""

        animal = self.trabado(instagram_error="Error 100: la imagen no se pudo bajar")

        self.assertEqual(self.grupos_con(animal), ["con_problemas"])

    def test_el_agendado_con_un_error_encima_sigue_en_agendados(self):
        """El grupo lo decide el momento del pipeline, no el error.

        Decidiéndolo por el error, a un agendado al que el cron le escribía un motivo se le
        caía la tarjeta a "Con problemas" y perdía el botón de cancelar, sin que el posteo
        se hubiera frenado: la agenda seguía puesta y salía igual al llegar la hora.
        """

        animal = self.agendado(instagram_error="Error 100: la imagen no se pudo bajar")

        self.assertEqual(self.grupos_con(animal), ["agendados"])

    def test_el_vencido_con_un_error_encima_sigue_en_la_cola(self):

        animal = self.agendado(minutos=-5, instagram_error="Error 100: no se pudo bajar")

        self.assertEqual(self.grupos_con(animal), ["en_cola"])

    def test_el_error_se_muestra_sin_sacar_al_animal_de_su_grupo(self):
        """El motivo es una nota de la tarjeta: donde esté el animal, se ve por qué falló."""

        self.agendado(nombre="Fallado", instagram_error="Error 100: la imagen no se pudo bajar")

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("la imagen no se pudo bajar", cuerpo)
        self.assertIn("Sale en", cuerpo)

    def test_ningun_animal_cae_en_dos_grupos(self):
        """Si estuviera en dos, el equipo lo cancelaría en uno y lo seguiría viendo en el otro.

        Y en ninguno tampoco: un animal del pipeline que no aparece en la pantalla es un
        posteo que va a salir y que nadie puede frenar, que es lo único que esto no puede
        permitir. Por eso los grupos se reparten el pipeline entero.
        """

        for animal in (
            self.agendado(nombre="Agendado"),
            self.agendado(nombre="AgendadoConError", instagram_error="algo salió mal"),
            self.agendado(nombre="Vencido", minutos=-5),
            self.agendado(nombre="VencidoConError", minutos=-5, instagram_error="algo salió mal"),
            self.agendado(nombre="AMano", instagram_programado_para=None),
            self.trabado(nombre="Trabado"),
        ):
            self.assertEqual(
                len(self.grupos_con(animal)), 1,
                "{} no está en exactamente un grupo".format(animal.nombre),
            )

    def test_el_que_no_esta_en_el_pipeline_no_aparece(self):
        """La pantalla es la cola de Instagram, no el listado de animales del sitio."""

        animal = make_animal(nombre="Comun", cargado_por=self.rescatista)

        self.assertEqual(self.grupos_con(animal), [])

    def test_se_puede_cancelar_desde_los_tres_grupos(self):
        """El botón estaba sólo en "Agendados", que es el único grupo que todavía no sale.

        Al que ya venció —el que está por salir en la próxima corrida— y al que quedó
        trabado no había forma de frenarlos desde la pantalla, aunque el endpoint y
        cancelar() los aceptaban igual.
        """

        for animal in (
            self.agendado(nombre="Agendado"),
            self.agendado(nombre="Vencido", minutos=-5),
            self.trabado(nombre="Trabado"),
        ):
            self.assertTrue(
                self.boton_de_cancelar(animal),
                "{} no se puede cancelar desde la pantalla".format(animal.nombre),
            )

    def test_cancelar_un_vencido_lo_saca_de_los_dos_crones(self):
        """El que ya venció es el que está por salir: frenarlo tiene que frenarlo de verdad,
        y ningún cron puede volver a levantarlo solo."""

        animal = self.agendado(nombre="Vencido", minutos=-5)

        self.accionar(self.admin, animal.id, "cancelar")

        animal.refresh_from_db()
        self.assertNotIn(animal, cola_de_preparar(), "el cron que prepara lo volvió a levantar")
        self.assertNotIn(animal, cola_de_publish(), "el cron que publica lo volvió a levantar")

    def test_lo_ya_publicado_no_aparece(self):

        animal = self.agendado(instagram_publicado=True, minutos=-5)

        self.assertEqual(self.grupos_con(animal), [])

    def test_cancelar_limpia_la_agenda(self):

        animal = self.agendado()

        self.accionar(self.admin, animal.id, "cancelar")

        animal.refresh_from_db()
        self.assertIsNone(animal.instagram_programado_para)

    def test_cancelar_lo_saca_de_la_cola_del_cron(self):
        """Limpiar sólo la fecha no cancela nada: para el cron un animal listo y sin fecha
        es del flujo viejo, o sea "publicá ya", y el posteo salía en la corrida siguiente."""

        animal = self.agendado()

        self.accionar(self.admin, animal.id, "cancelar")

        animal.refresh_from_db()
        self.assertNotIn(animal, self.cola_del_cron(), "cancelar lo dejó igual en la cola del cron")

    def test_cancelar_lo_saca_de_la_pantalla(self):

        animal = self.agendado()

        self.accionar(self.admin, animal.id, "cancelar")

        self.assertEqual(self.grupos_con(animal), [])

    def test_publicar_ya_vence_la_agenda(self):

        animal = self.agendado(minutos=120)

        self.accionar(self.admin, animal.id, "publicar_ya")

        animal.refresh_from_db()
        self.assertLessEqual(animal.instagram_programado_para, timezone.now())

    def test_publicar_ya_lo_deja_en_la_cola_de_algun_cron(self):
        """Vencer la agenda y nada más no hacía nada cuando el pipeline era uno solo.

        Ahora son dos: al que todavía no tiene las imágenes armadas lo levanta
        preparar_publicaciones, que se las arma y recién ahí lo marca.
        """

        animal = self.agendado(instagram_listo_para_publicar=False)

        self.accionar(self.admin, animal.id, "publicar_ya")

        animal.refresh_from_db()
        self.assertIn(animal, cola_de_preparar())

    def test_publicar_ya_no_marca_listo_al_que_le_faltan_imagenes(self):
        """La marca quiere decir "las imágenes del posteo ya están armadas".

        Prendiéndola a mano, el botón salteaba a preparar_publicaciones —que es quien las
        arma y quien se niega a marcar al animal que quedó con alguna sin armar— y mandaba
        a publicar un carrusel al que le faltaban fotos que el rescatista sí había cargado.
        """

        animal = self.agendado(instagram_listo_para_publicar=False)
        self.con_imagen_para_instagram(animal)
        make_animal_image(animal=animal)

        self.accionar(self.admin, animal.id, "publicar_ya")

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar, "lo mandó a publicar a medio armar")
        self.assertNotIn(animal, self.cola_del_cron())

    def test_publicar_ya_marca_al_que_ya_tiene_todas_las_imagenes(self):
        """El flujo viejo: las imágenes se armaron a mano desde /tools/generarimagen/, no
        hay nada que preparar y sin la marca el cron que publica no lo mira."""

        animal = self.agendado(instagram_listo_para_publicar=False)
        self.con_imagen_para_instagram(animal)

        self.accionar(self.admin, animal.id, "publicar_ya")

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_listo_para_publicar)
        self.assertIn(animal, self.cola_del_cron())

    def test_publicar_ya_no_marca_listo_al_que_no_tiene_ni_una_foto(self):
        """Sin fotos no hay posteo, y "todas las que tiene están armadas" da que sí."""

        animal = self.agendado(instagram_listo_para_publicar=False)

        self.accionar(self.admin, animal.id, "publicar_ya")

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar)

    def test_publicar_ya_lo_pasa_a_la_cola(self):

        animal = self.agendado(minutos=120)

        self.accionar(self.admin, animal.id, "publicar_ya")

        self.assertEqual(self.grupos_con(animal), ["en_cola"])

    def test_publicar_ya_no_resucita_lo_ya_publicado(self):
        """El post ya salió: adelantarlo de nuevo es publicarlo dos veces."""

        animal = self.agendado(instagram_publicado=True, instagram_listo_para_publicar=False)

        self.accionar(self.admin, animal.id, "publicar_ya")

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar)

    def test_una_accion_desconocida_no_toca_nada(self):

        animal = self.agendado()
        programado = animal.instagram_programado_para

        response = self.accionar(self.admin, animal.id, "borrar")

        animal.refresh_from_db()
        self.assertEqual(animal.instagram_programado_para, programado)
        self.assertEqual(response.status_code, 200)

    def test_un_animal_inexistente_no_rompe(self):

        response = self.accionar(self.admin, 999999, "cancelar")

        self.assertEqual(response.status_code, 200)

    def test_un_animal_id_que_no_es_un_numero_no_rompe(self):
        """Django castea el filtro por id a entero: con un "abc" filter() levantaba
        ValueError y la pantalla contestaba 500 en vez de "No se encontró el animal."."""

        response = self.accionar(self.admin, "abc", "cancelar")

        self.assertEqual(response.status_code, 200)
        self.assertIn("No se encontró el animal", response.content.decode())

    def test_muestra_el_veredicto_de_la_ia(self):
        """Es lo único del pipeline que mira el contenido: aprobado=True no mira nada."""

        self.agendado(
            nombre="Sospechoso",
            revision_ia_estado=Animal.REVISION_REVISAR,
            revision_ia_motivo="No se ve ningún animal en las fotos.",
        )

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("Revisar publicación", cuerpo)
        self.assertIn("No se ve ningún animal", cuerpo)

    def test_avisa_que_lo_marcado_por_la_ia_no_va_a_salir(self):
        """El cron no lo publica, así que la pantalla no puede decir que está por salir."""

        self.agendado(
            nombre="Sospechoso",
            revision_ia_estado=Animal.REVISION_REVISAR,
            revision_ia_motivo="No se ve ningún animal en las fotos.",
        )

        self.assertIn("No va a salir", self.abrir(self.admin).content.decode())

    def test_el_que_si_va_a_salir_no_dice_que_no(self):

        self.agendado(nombre="Willy")

        self.assertNotIn("No va a salir", self.abrir(self.admin).content.decode())

    def test_el_agendado_que_todavia_no_se_preparo_no_dice_que_no_va_a_salir(self):
        """El pipeline son dos etapas y la marca de listo la prende la primera.

        La pantalla preguntaba nada más que por la cola de `publish`, así que de todo lo que
        estaba esperando a `preparar_publicaciones` —o sea del camino feliz entero, desde
        que se aprueba el animal hasta que corre el primer cron— decía "No va a salir".
        """

        self.agendado(nombre="Willy", instagram_listo_para_publicar=False)

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertNotIn("No va a salir", cuerpo)
        self.assertIn("Sale en", cuerpo)

    def test_el_vencido_que_espera_a_preparar_tampoco_dice_que_no_va_a_salir(self):
        """Ya le tocó y el cron que prepara lo va a levantar en la próxima corrida."""

        self.agendado(nombre="Willy", minutos=-5, instagram_listo_para_publicar=False)

        self.assertNotIn("No va a salir", self.abrir(self.admin).content.decode())

    def test_el_trabado_dice_que_no_va_a_salir(self):
        """Sin agenda y sin marca no lo levanta ningún cron: ahí la pantalla tiene que
        decirlo, que para eso está."""

        self.trabado(nombre="Trabado")

        self.assertIn("No va a salir", self.abrir(self.admin).content.decode())

    def test_la_cuenta_regresiva_esta_en_castellano(self):
        """El sitio corre con USE_I18N en False, así que Django no traduce: el filtro
        timeuntil escribía "Sale en 41 minutes" en una pantalla que está toda en castellano."""

        self.agendado(minutos=45)

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("44 minutos", cuerpo)
        self.assertNotIn("minutes", cuerpo)

    def test_la_cuenta_regresiva_cuenta_las_horas(self):

        self.agendado(minutos=125)

        self.assertIn("2 h 4 min", self.abrir(self.admin).content.decode())

    def test_muestra_el_motivo_del_error_y_los_intentos(self):

        self.agendado(
            nombre="Fallado",
            instagram_error="Error 100: la imagen no se pudo bajar",
            instagram_intentos=3,
        )

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertIn("la imagen no se pudo bajar", cuerpo)
        self.assertIn("3 intentos", cuerpo)

    def test_el_motivo_del_error_se_muestra_escapado(self):
        """instagram_error es lo que contestó la API de Facebook: texto de afuera en la
        pantalla de un superusuario, que es justo quien puede aprobar animales."""

        self.agendado(
            nombre="Fallado",
            instagram_error='Error 100: <script>alert("robo la sesion")</script>',
        )

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertNotIn('<script>alert', cuerpo, "el error de la API se imprimió como HTML")
        self.assertIn("&lt;script&gt;", cuerpo)

    def test_la_descripcion_del_animal_se_muestra_sin_scripts(self):
        """datos lo escribe cualquiera que se registre, y acá lo abre un superusuario."""

        self.agendado(nombre="Willy", datos='Muy bueno <script>alert("hola")</script>')

        cuerpo = self.abrir(self.admin).content.decode()

        self.assertNotIn('<script>alert', cuerpo)

    def test_muestra_quien_lo_cargo(self):
        """Sin esto no se sabe a quién avisarle antes de cancelarle el posteo."""

        self.agendado(nombre="Willy")

        self.assertIn("rescatista@catpuccino", self.abrir(self.admin).content.decode())

    def poblar(self, cantidad, prefijo):
        """Reparte animales entre los tres grupos, con una foto cada uno."""

        for i in range(cantidad):

            nombre = "{}{}".format(prefijo, i)

            if i % 3 == 0:
                animal = self.agendado(nombre=nombre)
            elif i % 3 == 1:
                animal = self.agendado(nombre=nombre, minutos=-5)
            else:
                animal = self.trabado(nombre=nombre)

            make_animal_image(animal=animal)

    def test_no_hace_una_consulta_por_animal(self):
        """Las otras pantallas de la cola piden la foto adentro del for, que es una
        consulta por animal, y acá se listan los tres grupos juntos: con treinta animales
        repartidos entre los tres, la pantalla tiene que costar lo mismo que con tres."""

        self.poblar(3, "Pocos")

        with CaptureQueriesContext(connection) as con_tres:
            self.abrir(self.admin)

        self.poblar(30, "Muchos")

        with CaptureQueriesContext(connection) as con_treinta_y_tres:
            self.abrir(self.admin)

        self.assertEqual(
            len(con_treinta_y_tres), len(con_tres),
            "la pantalla hace una consulta por animal",
        )
