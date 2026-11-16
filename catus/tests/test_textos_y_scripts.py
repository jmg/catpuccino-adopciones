"""Lo que entra escrito por usuarios se guarda limpio, y las páginas no cargan código de
terceros sin versión fija.

Corre con ENV=TEST:
    ENV=TEST python manage.py test catus.tests.test_textos_y_scripts
"""
import datetime
import io
import pathlib
import re

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from catus.forms import AnimalForm, CatusUserForm, ContratoPersonaForm
from catus.tests.factories import make_animal, make_user

SCRIPT = '<p>Hola</p><script>alert(1)</script><img src=x onerror="alert(2)">'


class DescripcionLimpiaAlGuardarTest(TestCase):
    """La descripción del animal y la del perfil se limpiaban solo al mostrarlas: se
    guardaban como llegaban en el POST, y la edición las carga en TinyMCE 5, que tiene XSS
    al cargar contenido. El equipo abre esa pantalla con su sesión para animales de
    cualquiera, y el registro es abierto."""

    def test_la_descripcion_del_animal_se_guarda_sin_scripts(self):
        form = AnimalForm(data={"tipo": "G", "estado": "D", "nombre": "Michi", "sexo": "M", "datos": SCRIPT})
        form.is_valid()
        datos = form.cleaned_data["datos"]
        self.assertIn("<p>Hola</p>", datos)
        self.assertNotIn("<script", datos)
        self.assertNotIn("onerror", datos)

    def test_la_descripcion_del_perfil_se_guarda_sin_scripts(self):
        usuario = make_user(email="rescate@catpuccino.test")
        form = CatusUserForm(data={"email": usuario.email, "description": SCRIPT}, instance=usuario)
        form.is_valid()
        self.assertNotIn("<script", form.cleaned_data["description"])
        self.assertNotIn("onerror", form.cleaned_data["description"])

    def test_el_comando_limpia_lo_viejo_solo_con_aplicar(self):
        animal = make_animal(nombre="Viejo", datos=SCRIPT)
        salida = io.StringIO()

        call_command("sanear_textos", stdout=salida)
        animal.refresh_from_db()
        self.assertIn("<script", animal.datos)
        self.assertIn("Animal.datos: 1 revisados, 1 cambiarían", salida.getvalue())

        call_command("sanear_textos", "--aplicar", stdout=io.StringIO())
        animal.refresh_from_db()
        self.assertNotIn("<script", animal.datos)
        self.assertIn("<p>Hola</p>", animal.datos)


class FechasDelContratoTest(SimpleTestCase):
    """Las fechas del contrato usan el selector del navegador: antes era Pikaday, de jsDelivr
    sin versión fija, en la página donde el adoptante escribe su DNI."""

    def test_el_campo_es_de_tipo_fecha_y_muestra_el_valor_en_iso(self):
        form = ContratoPersonaForm(initial={"persona_fecha_nacimiento": datetime.date(1990, 5, 17)})
        html = str(form["persona_fecha_nacimiento"])
        self.assertIn('type="date"', html)
        self.assertIn('value="1990-05-17"', html)

    def test_acepta_la_fecha_del_navegador_y_la_escrita_a_mano(self):
        for valor in ("1990-05-17", "17/05/1990"):
            form = ContratoPersonaForm(data={"persona_fecha_nacimiento": valor})
            form.is_valid()
            self.assertEqual(form.cleaned_data.get("persona_fecha_nacimiento"), datetime.date(1990, 5, 17), valor)


class ScriptsDeTercerosTest(SimpleTestCase):
    """Ninguna página carga código de un CDN de npm: ahí, una URL sin versión (como la de
    Pikaday) sirve la última que alguien publique. Lo que se usa está en static/vendor, con
    versión en la carpeta; el SDK de Jentry va con versión e integrity."""

    def test_ningun_template_carga_de_un_cdn_de_npm(self):
        raiz = pathlib.Path(settings.BASE_DIR) / "catus" / "templates"
        encontrados = []
        for template in raiz.rglob("*.html"):
            texto = template.read_text(encoding="utf-8")
            for host in ("unpkg.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com"):
                if host in texto:
                    encontrados.append("{}: {}".format(template.relative_to(raiz), host))
        self.assertEqual(encontrados, [])

    def test_el_sdk_de_jentry_va_con_version_e_integrity(self):
        raiz = pathlib.Path(settings.BASE_DIR) / "catus" / "templates"
        texto = (raiz / "jentry" / "browser.html").read_text(encoding="utf-8")
        etiqueta = re.search(r"<script src=\"https://browser\.sentry-cdn\.com/[^\"]+\"[^>]*>", texto).group(0)
        self.assertRegex(etiqueta, r"/\d+\.\d+\.\d+/")
        self.assertIn("integrity=", etiqueta)
