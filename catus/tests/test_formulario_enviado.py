"""La página que ve el adoptante después de mandar el formulario de pre-adopción.

En producción esa página (la de "formulario enviado" y la de error, en gatos y en
perros) se renderizaba sin form_max_bytes: el script quedaba como "if (total > )", el
navegador lo descartaba entero con un SyntaxError y nunca corría el clearForm(). Las
respuestas del adoptante, que el formulario va guardando en el localStorage, quedaban
en el navegador y volvían a llenar el formulario en la próxima visita.
"""
import re
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings

from forms_builder.forms.models import Form

from catus.models import EstadoFormulario
from catus.test_login_throttle import fake_memcached
from catus.tests.factories import make_animal, make_field, make_user
from catus.views import adoption

LIMITE = re.compile(r"if \(total > (\S*?)\) \{")


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test")
class PaginaDeFormularioEnviadoTest(TestCase):

    def setUp(self):
        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)

        rescatista = make_user(email="rescatista@catpuccino.test")
        self.gato = make_animal(nombre="Michi", tipo="G", cargado_por=rescatista)
        self.perro = make_animal(nombre="Firulais", tipo="P", cargado_por=rescatista)

        self.forms = {
            "/pre-adopcion/": self.crear_formulario("formulario-de-pre-adopcion", "gato", self.gato),
            "/pre-adopcion/perros/": self.crear_formulario("formulario-de-pre-adopcion-para-perros", "perro", self.perro),
        }

    def crear_formulario(self, slug, especie, animal):

        form = Form.objects.create(title="Pre adopción", slug=slug, response="Recibido, gracias")
        #como en forms.sql: la primera respuesta es el id del animal elegido
        campos = {
            "animal": make_field(form, "Nombre del {} a adoptar".format(especie)),
            "nombre": make_field(form, "Nombre y Apellido"),
            "email": make_field(form, "Email"),
        }
        return {"form": form, "campos": campos, "animal": animal}

    def enviar(self, url, sin_nombre=False, **extra):

        datos = self.forms[url]
        campos = datos["campos"]
        post = {
            campos["animal"].slug: str(datos["animal"].id),
            campos["email"].slug: "ana@ejemplo.test",
        }
        if not sin_nombre:
            post[campos["nombre"].slug] = "Ana Gómez"
        post.update(extra)

        return self.client.post("{}?id={}".format(url, datos["animal"].id), post, HTTP_X_FORWARDED_FOR="190.2.3.4")

    def assertScriptValido(self, response):
        """El límite que escribe el template es un número: sin él, el script no compila."""

        self.assertEqual(response.status_code, 200)
        pagina = response.content.decode()

        self.assertNotIn("total > )", pagina)
        limite = LIMITE.search(pagina)
        self.assertIsNotNone(limite, "no está el chequeo del peso de los adjuntos")
        self.assertEqual(int(limite.group(1)), adoption.FORM_MAX_BYTES)
        self.assertIn('form.elements["{}"]'.format(adoption.HONEYPOT_FIELD), pagina)
        return pagina

    def test_envio_exitoso_borra_las_respuestas_guardadas(self):

        for url in self.forms:
            with self.subTest(url=url):
                pagina = self.assertScriptValido(self.enviar(url))

                self.assertIn("Recibido, gracias", pagina)
                self.assertIn("clearForm();", pagina)
                self.assertNotIn("formToLocalStorage();", pagina)

        self.assertEqual(EstadoFormulario.objects.count(), 2)

    def test_envio_con_errores_conserva_las_respuestas_para_reintentar(self):

        for url in self.forms:
            with self.subTest(url=url):
                pagina = self.assertScriptValido(self.enviar(url, sin_nombre=True))

                self.assertIn("response-text-error", pagina)
                self.assertNotIn("clearForm();", pagina)

        self.assertEqual(EstadoFormulario.objects.count(), 0)

    def test_adjuntos_demasiado_pesados(self):

        for url in self.forms:
            with self.subTest(url=url):
                foto = SimpleUploadedFile("foto.jpg", b"x" * 5000, content_type="image/jpeg")
                with mock.patch.object(adoption, "FORM_MAX_BYTES", 1000):
                    response = self.enviar(url, foto=foto)

                self.assertContains(response, "pesan demasiado")
                self.assertNotIn("total > )", response.content.decode())
                self.assertRegex(response.content.decode(), r"if \(total > 1000\) \{")

    def test_el_honeypot_tambien_recibe_un_script_valido(self):

        for url in self.forms:
            with self.subTest(url=url):
                pagina = self.assertScriptValido(self.enviar(url, **{adoption.HONEYPOT_FIELD: "https://spam.example"}))

                self.assertIn("Recibido, gracias", pagina)

        self.assertEqual(EstadoFormulario.objects.count(), 0)


class TemplateSinLimiteTest(TestCase):
    """Si alguna vista nueva se olvida del límite, el script tiene que seguir compilando."""

    def test_sin_form_max_bytes_el_chequeo_queda_desactivado_y_no_rompe(self):

        request = RequestFactory().post("/pre-adopcion/")
        request.user = AnonymousUser()

        pagina = render_to_string(
            "adoption/preadoption.html",
            {"is_post": True, "success": True, "form": None},
            request=request,
        )

        self.assertNotIn("total > )", pagina)
        self.assertEqual(LIMITE.search(pagina).group(1), "Infinity")
        self.assertIn("clearForm();", pagina)
