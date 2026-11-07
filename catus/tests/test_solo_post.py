"""Las URLs que solo reciben un POST (botones, forms con htmx, $.post).

Abiertas con un GET caían en el get() de TemplateView, que busca el template que
django_conventions deriva del nombre de la vista. Casi ninguna lo tiene: daban 500
TemplateDoesNotExist, también a un anónimo, y cada visita dejaba un error en Jentry.
Las que sí tenían uno contestaban 200 con un pedazo de pantalla vacío:
/tools/sendpreguntaremail/ decía "Ya se envió un mail a este usuario" sin mandar nada.

Estos tests van por el urlconf de verdad (self.client) y no por RequestFactory: lo que
se rompía era justamente lo que arma django_conventions al registrar las rutas.
"""
import importlib
import inspect
import json
import pkgutil
import shutil
import tempfile

from django.core import mail
from django.test import TestCase, override_settings
from django.views.generic import TemplateView, View
from django.views.generic.base import ContextMixin, TemplateResponseMixin

from catus.tests.factories import make_animal, make_animal_image, make_user


URLS_SOLO_POST = [
    "/accounts/checkhandle/",
    "/animal/validatename/",
    "/animal/photos/",
    "/animal/updateanimal/",
    "/animal/marcaradoptado/",
    "/animal/marcarenadopcion/",
    "/animal/marcarexpirado/",
    "/animal/actualizarfechaingreso/",
    "/animal/addcomment/",
    "/facebook/login/",
    "/tools/makeimages/",
    "/tools/makesingleimage/",
    "/tools/publish/",
    "/tools/saveform/",
    "/tools/sendpreguntaremail/",
    "/usuario/save/",
]

#ninguna vista queda afuera: si hiciera falta exceptuar una, va acá con el porqué
FUERA_DE_ESTE_CAMBIO = set()


def vistas_que_solo_reciben_post():
    """Las vistas de catus/views con post() y sin nada propio para el GET.

    Si ni get() ni render_to_response() ni get_context_data() están pisados, el GET es el
    de TemplateView: renderiza el template derivado del nombre, sin datos.
    """

    import catus.views
    from catus.views.base import BaseView

    genericas = {View, TemplateView, TemplateResponseMixin, ContextMixin, BaseView}

    for _, nombre, _ in pkgutil.walk_packages(catus.views.__path__, "catus.views."):
        modulo = importlib.import_module(nombre)

        for clase in vars(modulo).values():
            if not (inspect.isclass(clase) and issubclass(clase, View) and clase.__module__ == nombre):
                continue

            if not hasattr(clase, "post"):
                continue

            def definido_en(metodo):
                #una vista que hereda de View a secas no tiene get(): ya contesta 405 sola
                return next((k for k in clase.__mro__ if metodo in vars(k)), None)

            if any(definido_en(m) is None for m in ("get", "render_to_response", "get_context_data")):
                continue

            if all(definido_en(m) in genericas for m in ("get", "render_to_response", "get_context_data")):
                yield clase


class SoloPostTestCase(TestCase):

    def setUp(self):
        self.admin = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)
        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.animal = make_animal(cargado_por=self.rescatista)


class GetEnUrlsSoloPostTest(SoloPostTestCase):

    def assert_405(self, url, quien):

        response = self.client.get(url)

        self.assertEqual(response.status_code, 405, "{} abriendo {}".format(quien, url))
        self.assertEqual(response["Allow"], "POST", url)

    def test_un_anonimo_recibe_405(self):
        """Ni 500 ni la redirección al login: el GET no llega a ningún chequeo ni a post()."""

        for url in URLS_SOLO_POST:
            with self.subTest(url=url):
                self.assert_405(url, "un anónimo")

    def test_un_usuario_comun_recibe_405(self):

        self.client.force_login(self.rescatista)

        for url in URLS_SOLO_POST:
            with self.subTest(url=url):
                self.assert_405(url, "un rescatista")

    def test_el_equipo_recibe_405(self):

        self.client.force_login(self.admin)

        for url in URLS_SOLO_POST:
            with self.subTest(url=url):
                self.assert_405(url, "el equipo")

    def test_head_tambien_recibe_405(self):
        """Django contesta un HEAD con el get(): sin esto un HEAD daba el mismo 500."""

        self.client.force_login(self.admin)

        for url in URLS_SOLO_POST:
            with self.subTest(url=url):
                self.assertEqual(self.client.head(url).status_code, 405, url)

    @override_settings(ENV="TEST")
    def test_el_get_no_dice_que_mando_un_mail(self):
        """Antes contestaba "Ya se envió un mail a este usuario" sin haber mandado nada."""

        self.client.force_login(self.admin)

        response = self.client.get("/tools/sendpreguntaremail/", {
            "user_id": self.rescatista.id, "content": "hola",
        })

        self.assertEqual(response.status_code, 405)
        self.assertNotIn("Ya se envi", response.content.decode())
        self.assertEqual(len(mail.outbox), 0)

    def test_la_lista_tiene_todas_las_vistas_que_solo_reciben_post(self):
        """Si aparece una vista nueva de este tipo, que también la cubran los tests de arriba."""

        from django.urls import resolve

        en_la_lista = {resolve(url).func.view_class for url in URLS_SOLO_POST}

        faltan = [
            "{}.{}".format(clase.__module__, clase.__name__)
            for clase in vistas_que_solo_reciben_post()
            if clase not in en_la_lista
        ]

        self.assertEqual(sorted(set(faltan) - FUERA_DE_ESTE_CAMBIO), [])

    def test_ninguna_vista_que_solo_recibe_post_acepta_el_get(self):
        """Una vista nueva que solo recibe POST y se olvida de SoloPostMixin falla acá,
        antes de dar 500 en producción."""

        sin_405 = [
            "{}.{}".format(clase.__module__, clase.__name__)
            for clase in vistas_que_solo_reciben_post()
            if "get" in clase.http_method_names
        ]

        self.assertEqual(sorted(set(sin_405) - FUERA_DE_ESTE_CAMBIO), [])


class PostEnUrlsSoloPostTest(SoloPostTestCase):
    """El POST sigue haciendo exactamente lo mismo, con los mismos permisos."""

    def test_el_equipo_marca_listo_para_instagram(self):

        self.client.force_login(self.admin)

        response = self.client.post("/tools/saveform/", {
            "animal_id": self.animal.id, "instagram_listo_para_publicar": "on",
        })

        self.assertEqual(response.content.decode(), "ok")
        self.animal.refresh_from_db()
        self.assertTrue(self.animal.instagram_listo_para_publicar)

    @override_settings(ENV="TEST")
    def test_el_equipo_manda_el_mail_de_pregunta(self):

        self.client.force_login(self.admin)

        response = self.client.post("/tools/sendpreguntaremail/", {
            "user_id": self.rescatista.id, "content": "¿Sigue en adopción?",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.rescatista.email])

    def test_el_rescatista_marca_su_animal_como_adoptado(self):

        self.client.force_login(self.rescatista)

        response = self.client.post("/animal/marcaradoptado/", {"animal_id": self.animal.id})

        self.assertEqual(response.status_code, 200)
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "A")

    def test_el_formulario_publico_sigue_trayendo_las_fotos(self):
        """/animal/photos/ es abierta a propósito: la usa el formulario de pre-adopción."""

        #make_animal_image escribe archivos de verdad: que no queden en gallery/ del repo
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)

        with override_settings(MEDIA_ROOT=media):
            make_animal_image(animal=self.animal)

            response = self.client.post("/animal/photos/", {"animal_id": self.animal.id})

        self.assertEqual(response.status_code, 200)
        #json_response() no le pone Content-Type, así que response.json() no lo lee
        self.assertEqual(json.loads(response.content)["photos_count"], 1)

    def test_un_anonimo_sigue_sin_poder_usar_las_herramientas(self):

        response = self.client.post("/tools/saveform/", {
            "animal_id": self.animal.id, "instagram_listo_para_publicar": "on",
        })

        self.assertEqual(response.content.decode(), "No tenes permisos para esto.")
        self.animal.refresh_from_db()
        self.assertFalse(self.animal.instagram_listo_para_publicar)

    def test_un_anonimo_sigue_yendo_al_login(self):

        for url in ("/animal/marcaradoptado/", "/animal/addcomment/", "/facebook/login/"):
            with self.subTest(url=url):
                response = self.client.post(url, {"animal_id": self.animal.id})

                self.assertEqual(response.status_code, 302, url)
                self.assertIn("/accounts/login/", response["Location"])

        self.animal.refresh_from_db()
        self.assertEqual(self.animal.estado, "D")

    def test_un_rescatista_sigue_sin_poder_vincular_instagram(self):

        self.client.force_login(self.rescatista)

        response = self.client.post("/facebook/login/", {"access_token": "x"})

        self.assertEqual(response.status_code, 403)
