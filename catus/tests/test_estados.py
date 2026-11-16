"""Un solo camino para cambiar el estado de un animal (services/estados.py).

En producción, de 35 adopciones en 90 días, 15 se marcaron desde el selector de la edición
y quedaron sin fecha de adopción: el panel solo pregunta "¿Quién lo adoptó?" si la hay, así
que tampoco quedó el adoptante ni se mandó la adopción a BuenAdoptante. Y pasar un expirado a
"En adopción" desde ahí no le renovaba el mes: expirar_animales lo volvía a sacar a la mañana
siguiente. Cada transición se prueba por los dos caminos: el selector de la edición y los
botones del panel, que ahora pasan por el mismo servicio.
"""
import json
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from catus.models import ActividadBuenAdoptante, Animal
from catus.services import estados
from catus.services.moderacion import ModeracionService
from catus.tests.factories import make_animal, make_animal_image, make_estado_formulario, make_user
from catus.views.animal import EditView


def hace(dias):
    return timezone.now() - timedelta(days=dias)


class EstadosTestCase(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.factory = RequestFactory()
        self.rescatista = make_user()
        self.client.force_login(self.rescatista)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def animal(self, **kwargs):
        """Publicado hace dos meses: si nadie le renueva el mes, el cron lo expira."""

        kwargs.setdefault("cargado_por", self.rescatista)
        kwargs.setdefault("fecha_ingreso", hace(60))
        animal = make_animal(**kwargs)
        make_animal_image(animal=animal)
        return animal

    def post_de_edicion(self, animal, **cambios):
        """El POST de la pantalla de edición, como lo manda el navegador. Un cambio en
        None saca ese campo del POST."""

        imagenes = list(animal.get_images())
        datos = {
            "tipo": animal.tipo, "estado": animal.estado, "nombre": animal.nombre,
            "edad": animal.edad or "", "sexo": animal.sexo, "zona": animal.zona or "",
            "datos": animal.datos or "",
            "animalimage_set-TOTAL_FORMS": str(len(imagenes)),
            "animalimage_set-INITIAL_FORMS": str(len(imagenes)),
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
        }
        for i, imagen in enumerate(imagenes):
            datos["animalimage_set-%d-id" % i] = str(imagen.id)
            datos["animalimage_set-%d-animal" % i] = str(animal.id)
        datos.update(cambios)
        datos = {clave: valor for clave, valor in datos.items() if valor is not None}

        request = self.factory.post("/animales/%s/" % animal.id, datos)
        request.user = self.rescatista
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()

        view = EditView()
        view.request = request
        with mock.patch.object(ModeracionService, "revisar_y_guardar"):
            return view.req(is_post=True, animal_id=str(animal.id))

    def editar(self, animal, **cambios):

        respuesta = self.post_de_edicion(animal, **cambios)

        #un 302 al panel es que guardó; con errores vuelve a mostrar el formulario
        self.assertEqual(respuesta.status_code, 302, "la edición no guardó")
        animal.refresh_from_db()
        return animal

    def boton(self, url, animal, **datos):
        """Los botones del panel."""

        respuesta = self.client.post(url, dict(animal_id=animal.id, **datos))
        self.assertTrue(json.loads(respuesta.content)["success"])
        animal.refresh_from_db()
        return animal

    def correr_expiracion(self):
        call_command("expirar_animales", stdout=StringIO(), stderr=StringIO())

    def panel(self):
        return self.client.get("/accounts/profile/").content.decode()


class MarcarAdoptadoTest(EstadosTestCase):

    def test_desde_la_edicion_queda_con_fecha_y_el_panel_pregunta_quien(self):
        """El bug: "Adoptado" en el selector lo dejaba sin fecha, y sin fecha el panel no
        preguntaba "¿Quién lo adoptó?"."""

        animal = self.animal()
        make_estado_formulario(animal, persona_nombre="Ana Pérez", tipo="A", hash="h-ana")

        animal = self.editar(animal, estado="A")

        self.assertEqual(animal.estado, "A")
        self.assertIsNotNone(animal.fecha_adopcion)
        self.assertIn('id="pregunta-adopcion-{}"'.format(animal.id), self.panel())

    def test_desde_el_panel_queda_con_fecha(self):

        animal = self.boton("/animal/marcaradoptado/", self.animal())

        self.assertEqual(animal.estado, "A")
        self.assertIsNotNone(animal.fecha_adopcion)

    def test_editar_otra_cosa_de_un_adoptado_no_le_pisa_la_fecha(self):

        fecha = hace(20)
        animal = self.animal(estado="A", fecha_adopcion=fecha)

        animal = self.editar(animal, edad="3 años")

        self.assertEqual(animal.estado, "A")
        self.assertEqual(animal.fecha_adopcion, fecha)

    def test_decir_despues_quien_lo_adopto_no_le_pisa_la_fecha(self):

        fecha = hace(20)
        animal = self.animal(estado="A", fecha_adopcion=fecha)
        formulario = make_estado_formulario(animal, persona_nombre="Ana Pérez", tipo="A", hash="h-ana")

        animal = self.boton("/animal/marcaradoptado/", animal, estado_formulario_id=formulario.id)

        self.assertEqual(animal.fecha_adopcion, fecha)
        self.assertEqual(animal.estado_formulario_id, formulario.id)

    @override_settings(BUENADOPTANTE_ACTIVO=True, BUENADOPTANTE_API_KEY="ba_test_x")
    def test_con_el_formulario_de_quien_adopto_queda_registrado(self):
        """El formulario queda vinculado y adoptado, y la adopción queda anotada para que
        el cron la mande a BuenAdoptante (acá no se llama a la API)."""

        animal = self.animal()
        formulario = make_estado_formulario(animal, persona_nombre="Ana Pérez", tipo="A", hash="h-ana")

        animal = self.boton("/animal/marcaradoptado/", animal, estado_formulario_id=formulario.id)

        formulario.refresh_from_db()
        self.assertEqual(animal.estado_formulario_id, formulario.id)
        self.assertEqual(animal.adoptante, "Ana Pérez")
        self.assertEqual(formulario.estado, "A")
        self.assertTrue(ActividadBuenAdoptante.objects.filter(tipo="adoption", animal=animal, estado_formulario=formulario).exists())

    def test_no_vincula_el_formulario_de_otro_rescatista(self):

        animal = self.animal()
        ajeno = make_animal(nombre="Ajeno", cargado_por=make_user(email="otra@catpuccino.test"))
        formulario = make_estado_formulario(ajeno, persona_nombre="Ana Pérez", tipo="A", hash="h-ajeno")

        animal = self.boton("/animal/marcaradoptado/", animal, estado_formulario_id=formulario.id)

        self.assertEqual(animal.estado, "A")
        self.assertIsNone(animal.estado_formulario_id)

    def test_no_vincula_un_formulario_frenado_ni_un_duplicado_ni_un_id_raro(self):

        animal = self.animal()
        frenado = make_estado_formulario(animal, estado="B", tipo="A", hash="h-b")
        duplicado = make_estado_formulario(animal, estado="U", tipo="A", hash="h-u")

        for elegido in (frenado.id, duplicado.id, "1 OR 1=1", "", None):
            self.assertIsNone(estados.formulario_del_adoptante(animal, elegido))


class RepublicarTest(EstadosTestCase):

    def test_desde_la_edicion_un_expirado_tiene_otro_mes(self):
        """El bug: de "Expirado" a "En adopción" en el selector no renovaba fecha_ingreso y
        el cron lo volvía a sacar al día siguiente."""

        animal = self.animal(estado="E", expiro_el=hace(1))

        animal = self.editar(animal, estado="D")
        self.correr_expiracion()

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "D")
        self.assertIsNone(animal.expiro_el)
        self.assertGreater(animal.fecha_ingreso, hace(1))
        self.assertIn(animal, Animal.get_all_for_adoption())

    def test_desde_el_panel_un_expirado_tiene_otro_mes(self):

        animal = self.boton("/animal/marcarenadopcion/", self.animal(estado="E", expiro_el=hace(1)))
        self.correr_expiracion()

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "D")
        self.assertGreater(animal.fecha_ingreso, hace(1))

    def test_un_reservado_que_vuelve_a_adopcion_no_expira_al_otro_dia(self):
        """El cron no expira a los reservados, pero cuenta el mes desde fecha_ingreso: uno
        reservado hace dos meses que volvía a adopción salía del sitio a la mañana siguiente."""

        for camino in ("edicion", "panel"):
            animal = self.animal(nombre="Reservado " + camino, estado="R")

            if camino == "edicion":
                animal = self.editar(animal, estado="D")
            else:
                animal = self.boton("/animal/marcarenadopcion/", animal)
            self.correr_expiracion()

            animal.refresh_from_db()
            self.assertEqual(animal.estado, "D", camino)

    def test_un_adoptado_que_vuelve_a_adopcion_pierde_la_fecha_de_adopcion(self):

        for camino in ("edicion", "panel"):
            animal = self.animal(nombre="Devuelto " + camino, estado="A", fecha_adopcion=hace(10),
                                 pregunta_adopcion_hasta=timezone.now() + timedelta(days=3650))

            if camino == "edicion":
                animal = self.editar(animal, estado="D")
            else:
                animal = self.boton("/animal/marcarenadopcion/", animal)

            self.assertEqual(animal.estado, "D", camino)
            self.assertIsNone(animal.fecha_adopcion, camino)
            #"nadie de la lista lo adoptó" era sobre esa adopción
            self.assertIsNone(animal.pregunta_adopcion_hasta, camino)

    def test_editar_uno_en_adopcion_no_le_cambia_la_fecha_de_publicacion(self):

        animal = self.animal(fecha_ingreso=hace(10))
        publicado = animal.fecha_ingreso

        animal = self.editar(animal, edad="3 años")

        self.assertEqual(animal.fecha_ingreso, publicado)


class ReservarTest(EstadosTestCase):

    def test_desde_la_edicion(self):

        animal = self.editar(self.animal(), estado="R")
        self.correr_expiracion()

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "R")
        self.assertNotIn(animal, Animal.get_all_for_adoption())

    def test_desde_el_servicio_un_adoptado_reservado_pierde_la_fecha_de_adopcion(self):
        """No hay botón de reservar en el panel: lo usa la página del formulario."""

        animal = estados.reservar(self.animal(estado="A", fecha_adopcion=hace(3)))

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "R")
        self.assertIsNone(animal.fecha_adopcion)


class ExpirarAManoTest(EstadosTestCase):

    def test_desde_la_edicion_no_deja_la_pregunta_del_panel(self):
        """A mano no tiene expiro_el: ni el panel ni el mail preguntan si sigue en adopción."""

        animal = self.editar(self.animal(fecha_ingreso=hace(2)), estado="E")

        self.assertEqual(animal.estado, "E")
        self.assertIsNone(animal.expiro_el)
        self.assertNotIn("¿Siguen en adopción?", self.panel())

    def test_desde_el_panel_no_deja_la_pregunta(self):

        animal = self.boton("/animal/marcarexpirado/", self.animal(estado="E", expiro_el=hace(1)))

        self.assertEqual(animal.estado, "E")
        self.assertIsNone(animal.expiro_el)


class SelectorDeEstadoTest(EstadosTestCase):

    def test_sin_estado_en_el_post_no_cambia(self):
        """El campo es opcional: un POST que no lo trae no le cambia el estado a nadie."""

        animal = self.editar(self.animal(estado="R"), estado=None, edad="1 año")

        self.assertEqual(animal.estado, "R")
        self.assertEqual(animal.edad, "1 año")

    def test_un_estado_que_no_existe_no_guarda(self):

        animal = self.animal()

        respuesta = self.post_de_edicion(animal, estado="Z", edad="1 año")

        self.assertEqual(respuesta.status_code, 200)
        animal.refresh_from_db()
        self.assertEqual(animal.estado, "D")
        self.assertNotEqual(animal.edad, "1 año")

    def test_un_alta_siempre_arranca_en_adopcion(self):
        """El selector no se muestra al cargar uno nuevo; un POST armado a mano con
        "Adoptado" daba de alta un adoptado sin fecha."""

        from catus.tests.factories import uploaded_photo

        datos = {
            "tipo": "G", "estado": "A", "nombre": "Nuevo", "edad": "2 años", "sexo": "M",
            "zona": "CABA", "datos": "Gatito en adopción.",
            "animalimage_set-TOTAL_FORMS": "1", "animalimage_set-INITIAL_FORMS": "0",
            "animalimage_set-MIN_NUM_FORMS": "0", "animalimage_set-MAX_NUM_FORMS": "1000",
            "animalimage_set-0-image": uploaded_photo(),
        }
        request = self.factory.post("/animales/", datos)
        request.user = self.rescatista
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        view = EditView()
        view.request = request
        with mock.patch.object(ModeracionService, "revisar_y_guardar", return_value=Animal.REVISION_ERROR), \
                mock.patch("catus.views.animal.MailService"):
            view.req(is_post=True)

        nuevo = Animal.objects.get(nombre="Nuevo")
        self.assertEqual(nuevo.estado, "D")
        self.assertIsNone(nuevo.fecha_adopcion)


class ServicioTest(TestCase):

    def test_un_estado_desconocido_es_un_error(self):

        with self.assertRaises(ValueError):
            estados.cambiar_estado(make_animal(), "Z", guardar=False)

    def test_sin_guardar_no_toca_la_base(self):

        animal = make_animal()

        estados.cambiar_estado(animal, "A", guardar=False)

        self.assertEqual(Animal.objects.get(id=animal.id).estado, "D")
        self.assertEqual(animal.estado, "A")
        self.assertIsNotNone(animal.fecha_adopcion)


class CompletarFechaAdopcionTest(TestCase):
    """Los adoptados que quedaron sin fecha por el selector de la edición: el comando los
    cuenta y, con --aplicar --desde, les pone la fecha para que el panel pregunte quién."""

    def setUp(self):
        self.rescatista = make_user()

    def adoptado_sin_fecha(self, tocado_hace, nombre="Willy"):

        animal = make_animal(nombre=nombre, estado="A", cargado_por=self.rescatista)
        #updated_at a mano: save() no lo toca, pero create sí lo puso en ahora
        Animal.objects.filter(id=animal.id).update(updated_at=hace(tocado_hace))
        animal.refresh_from_db()
        return animal

    def correr(self, *args):

        salida = StringIO()
        call_command("completar_fecha_adopcion", *args, stdout=salida, stderr=StringIO())
        return salida.getvalue()

    def test_sin_aplicar_solo_cuenta_y_no_imprime_nombres_ni_mails(self):

        reciente = self.adoptado_sin_fecha(3, nombre="Nombre Secreto")
        self.adoptado_sin_fecha(400, nombre="Otro Secreto")
        make_animal(nombre="Con fecha", estado="A", fecha_adopcion=hace(5))

        salida = self.correr()

        self.assertIn("2 adoptados sin fecha", salida)
        self.assertIn("última semana: 1", salida)
        self.assertIn("más de un año: 1", salida)
        self.assertNotIn("Secreto", salida)
        self.assertNotIn("@", salida)
        reciente.refresh_from_db()
        self.assertIsNone(reciente.fecha_adopcion)

    def test_aplicar_pone_la_fecha_de_updated_at_solo_desde_el_corte(self):

        reciente = self.adoptado_sin_fecha(10)
        viejo = self.adoptado_sin_fecha(200, nombre="Viejo")
        desde = timezone.localdate() - timedelta(days=30)

        salida = self.correr("--aplicar", "--desde", desde.isoformat())

        reciente.refresh_from_db()
        viejo.refresh_from_db()
        self.assertEqual(reciente.fecha_adopcion, reciente.updated_at)
        self.assertIsNone(viejo.fecha_adopcion)
        self.assertIn("1 adoptados quedaron con fecha", salida)

    def test_el_panel_pregunta_quien_lo_adopto_despues_de_completar(self):

        animal = self.adoptado_sin_fecha(10)
        make_estado_formulario(animal, persona_nombre="Ana Pérez", tipo="A", hash="h-ana")
        self.client.force_login(self.rescatista)
        self.assertNotIn('id="pregunta-adopcion-{}"'.format(animal.id), self.client.get("/accounts/profile/").content.decode())

        self.correr("--aplicar", "--desde", (timezone.localdate() - timedelta(days=30)).isoformat())

        self.assertIn('id="pregunta-adopcion-{}"'.format(animal.id), self.client.get("/accounts/profile/").content.decode())

    def test_aplicar_sin_desde_no_toca_nada(self):

        from django.core.management.base import CommandError

        animal = self.adoptado_sin_fecha(10)

        with self.assertRaises(CommandError):
            self.correr("--aplicar")

        animal.refresh_from_db()
        self.assertIsNone(animal.fecha_adopcion)
