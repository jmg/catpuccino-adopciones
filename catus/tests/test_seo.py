"""Lo que el sitio les dice a los buscadores y a WhatsApp: /robots.txt, /sitemap.xml, las
meta de la portada y del perfil de cada rescatista, y los links de la tarjeta a la ficha.

/robots.txt daba 404; el sitemap era un archivo fijo, con el login y el registro adentro y
ni un animal; la portada repetía la misma descripción que todas las páginas y un meta
keywords que los buscadores ignoran; y el perfil de un rescatista, que extiende la
portada, no tenía URL canónica propia.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from catus.tests.factories import make_animal, make_animal_image, make_user

HOST = "https://adopciones.catpuccino.org"


def meta(response, nombre):

    encontrada = re.search(r'<meta (?:name|property)="{}" content="([^"]*)"'.format(re.escape(nombre)), response.content.decode())
    return encontrada.group(1) if encontrada else None


def canonica(response):

    encontrada = re.search(r'<link rel="canonical" href="([^"]*)">', response.content.decode())
    return encontrada.group(1) if encontrada else None


class RobotsTest(TestCase):

    def test_existe_y_dice_que_no_indexar(self):

        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        texto = response.content.decode()
        for ruta in ["/accounts/", "/tools/", "/formularios/", "/formulario/", "/contrato/", "/contrato_adopcion/", "/postularme/"]:
            self.assertIn("Disallow: {}\n".format(ruta), texto)
        self.assertIn("Sitemap: {}/sitemap.xml".format(HOST), texto)
        self.assertNotIn("Disallow: /\n", texto)

    def test_no_nombra_la_url_del_admin(self):
        """La URL del admin es secreta: robots.txt lo lee cualquiera."""

        self.assertNotIn(settings.ADMIN_URL.strip("/"), self.client.get("/robots.txt").content.decode())


class SitemapTest(TestCase):

    def setUp(self):

        self.refugio = make_user(email="refugio@test.com", handle="refugio")
        self.sin_animales = make_user(email="vacio@test.com", handle="vacio")
        self.michi = make_animal(nombre="Michi", cargado_por=self.refugio,
                                 fecha_ingreso=timezone.make_aware(datetime(2026, 11, 2, 12)))
        self.firulais = make_animal(nombre="Firulais", tipo="P", cargado_por=self.refugio,
                                    fecha_ingreso=timezone.make_aware(datetime(2026, 10, 20, 12)))
        self.borrador = make_animal(nombre="Borrador", aprobado=False)
        self.adoptado = make_animal(nombre="Adoptado", estado="A", cargado_por=self.sin_animales)

    def entradas(self):

        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/xml"))

        espacio = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        raiz = ET.fromstring(response.content)
        return {
            url.find("s:loc", espacio).text: getattr(url.find("s:lastmod", espacio), "text", None)
            for url in raiz.findall("s:url", espacio)
        }

    def test_lista_las_paginas_publicas_y_no_el_login(self):

        entradas = self.entradas()

        for ruta in ["/", "/pre-adopcion/", "/pre-adopcion/perros/", "/como-funciona/", "/terminos/", "/privacidad/"]:
            self.assertIn(HOST + ruta, entradas)
        self.assertNotIn(HOST + "/accounts/login/", entradas)
        self.assertNotIn(HOST + "/accounts/register/", entradas)

    def test_lista_la_ficha_de_cada_animal_en_adopcion_con_su_fecha(self):

        entradas = self.entradas()

        self.assertEqual(entradas[HOST + self.michi.get_ficha_url()], "2026-11-02")
        self.assertEqual(entradas[HOST + self.firulais.get_ficha_url()], "2026-10-20")
        self.assertNotIn(HOST + self.borrador.get_ficha_url(), entradas)
        self.assertNotIn(HOST + self.adoptado.get_ficha_url(), entradas)

    def test_la_portada_y_los_formularios_cambian_con_el_ultimo_animal(self):

        entradas = self.entradas()

        self.assertEqual(entradas[HOST + "/"], "2026-11-02")
        self.assertEqual(entradas[HOST + "/pre-adopcion/"], "2026-11-02")
        self.assertEqual(entradas[HOST + "/pre-adopcion/perros/"], "2026-10-20")
        self.assertIsNone(entradas[HOST + "/terminos/"])

    def test_lista_los_perfiles_con_animales_en_adopcion(self):

        entradas = self.entradas()

        self.assertEqual(entradas[HOST + "/refugio/"], "2026-11-02")
        self.assertNotIn(HOST + "/vacio/", entradas)

    def test_un_perfil_con_handle_repetido_va_por_id(self):

        otra = make_user(email="otra@test.com", handle="refugio")

        entradas = self.entradas()

        self.assertIn(HOST + "/usuario/{}/animales/".format(self.refugio.id), entradas)
        self.assertNotIn(HOST + "/refugio/", entradas)
        self.assertNotIn(HOST + "/usuario/{}/animales/".format(otra.id), entradas)

    def test_un_nombre_raro_no_rompe_el_xml(self):

        make_animal(nombre='Tom & "Jerry" <3')

        self.assertTrue(any("tom-jerry-3" in url for url in self.entradas()))


class PortadaTest(TestCase):

    def test_la_descripcion_dice_cuantos_buscan_familia(self):

        make_animal(nombre="Michi")
        make_animal(nombre="Pelusa")
        make_animal(nombre="Firulais", tipo="P")
        make_animal(nombre="Borrador", aprobado=False)

        response = self.client.get("/")

        self.assertTrue(meta(response, "description").startswith("2 gatos y 1 perro buscan familia."))
        self.assertEqual(meta(response, "og:description"), meta(response, "description"))

    def test_tiene_su_url_canonica_y_su_foto_para_compartir(self):

        response = self.client.get("/?buscar=lanus&tipo=gatos")

        self.assertEqual(canonica(response), HOST + "/")
        self.assertEqual(meta(response, "og:url"), HOST + "/")
        self.assertEqual(meta(response, "og:image"), HOST + "/static/compartir.png")

    def test_sin_meta_keywords(self):

        self.assertNotContains(self.client.get("/"), "keywords")

    def test_la_tarjeta_lleva_a_la_ficha_y_el_boton_al_formulario(self):

        michi = make_animal(nombre="Michi")
        make_animal_image(michi)

        response = self.client.get("/")
        html = response.content.decode()

        #el nombre y la foto; la foto no la recorren ni el teclado ni el lector, que ya tienen el nombre
        self.assertIn('<a class="animal-title" href="{}">'.format(michi.get_ficha_url()), html)
        self.assertIn('<a class="carousel-image foto-ficha" href="{}" tabindex="-1" aria-hidden="true">'.format(michi.get_ficha_url()), html)
        self.assertContains(response, 'href="/pre-adopcion/?id={}"'.format(michi.id))

    def test_la_tarjeta_trae_lo_que_usa_el_buscador(self):

        make_animal(nombre="Michi", sexo="H", edad="6/7 meses", zona=None)

        html = self.client.get("/").content.decode()

        self.assertIn('data-sexo="H"', html)
        self.assertIn('data-edad="6/7 meses"', html)
        self.assertIn('data-meses="6"', html)
        #sin zona, vacía: "None" se encontraba buscando "no"
        self.assertIn('data-zone=""', html)

    def test_la_edad_desconocida_va_vacia(self):

        make_animal(nombre="Michi", edad="joven")

        self.assertContains(self.client.get("/"), 'data-meses=""')


class PerfilDelRescatistaTest(TestCase):
    """/<handle>/ extiende la portada: no puede decir que es la portada."""

    def test_tiene_su_propia_canonica_y_descripcion(self):

        refugio = make_user(email="refugio@test.com", handle="refugio", title="Refugio Patitas",
                            description="<p>Rescatamos gatos en <b>Lanús</b> &amp; alrededores.</p>")
        make_animal(nombre="Michi", cargado_por=refugio)

        for ruta in ["/refugio/", "/usuario/{}/animales/".format(refugio.id)]:
            with self.subTest(ruta=ruta):
                response = self.client.get(ruta)
                self.assertEqual(canonica(response), HOST + "/refugio/")
                self.assertEqual(meta(response, "og:url"), HOST + "/refugio/")
                self.assertEqual(meta(response, "description"), "Rescatamos gatos en Lanús &amp; alrededores.")
                self.assertEqual(meta(response, "og:description"), "Rescatamos gatos en Lanús &amp; alrededores.")

    def test_sin_descripcion_dice_de_quien_es(self):

        refugio = make_user(email="refugio@test.com", handle="refugio", title="Refugio Patitas")

        response = self.client.get("/refugio/")

        self.assertEqual(meta(response, "description"), "Gatos y perros en adopción de Refugio Patitas en Catpuccino Adopciones.")

    def test_la_tarjeta_del_perfil_tambien_lleva_a_la_ficha(self):

        refugio = make_user(email="refugio@test.com", handle="refugio")
        michi = make_animal(nombre="Michi", cargado_por=refugio)

        self.assertContains(self.client.get("/refugio/"), '<a class="animal-title" href="{}">'.format(michi.get_ficha_url()))
