"""El diseño de los mails (email/base.html) y su versión de texto.

Todos los mails pasan por utils.send_html_email: las plantillas de email/ ya extienden el
marco, y el HTML que arma el código (avisos, contrato) lo envuelve envolver_mail. La versión
de texto antes era el HTML crudo, con las etiquetas a la vista.
"""
from django.core import mail
from django.test import TestCase, override_settings
from django.template.loader import render_to_string

from catus.services.mail import MailService
from catus.tests.factories import make_animal, make_user
from catus.utils import envolver_mail, send_html_email, texto_plano

SITIO = dict(ENV="TEST", HOST="adopciones.test", SSL_HOST="https://adopciones.test")


class MarcoTest(TestCase):

    def test_el_html_que_arma_el_codigo_va_adentro_del_marco(self):

        html = envolver_mail("<p>Hay que volver a conectar Instagram.</p>")

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Catpuccino Adopciones", html)
        self.assertIn("<p>Hay que volver a conectar Instagram.</p>", html)
        self.assertIn("Hay que volver a conectar Instagram.", html.split("</head>")[1].split("<table")[0],
                      "el resumen que muestra la bandeja de entrada")

    def test_una_plantilla_que_ya_trae_el_marco_no_se_envuelve_dos_veces(self):

        html = render_to_string("email/received.html", {"tipo": "transit"})

        self.assertEqual(envolver_mail(html), html)
        self.assertEqual(html.count("<!DOCTYPE html>"), 1)

    def test_el_marco_no_trae_links_propios(self):
        """El mail "¿Sigue en adopción?" lleva texto del equipo, y su test controla que no
        aparezca ningún link (test_animales.test_the_ask_mail_is_the_teams_and_goes_as_text)."""

        self.assertNotIn("<a ", envolver_mail("hola"))


class TextoPlanoTest(TestCase):

    def test_sin_etiquetas_y_con_los_links_a_la_vista(self):

        texto = texto_plano(envolver_mail(
            "<p>Hola <b>Ana</b>,</p><p>Mirá <a href='https://adopciones.test/formularios/abc/'>el formulario</a>"
            " o <a href=\"https://adopciones.test/\">https://adopciones.test/</a>.<br>Gracias &amp; saludos</p>"))

        self.assertNotIn("<", texto)
        self.assertIn("Hola Ana,", texto)
        self.assertIn("el formulario (https://adopciones.test/formularios/abc/)", texto)
        self.assertIn(" o https://adopciones.test/.", texto, "un link que ya es la dirección no se repite")
        self.assertIn("Gracias & saludos", texto)
        self.assertNotIn("@media", texto, "el <style> del marco no va al texto")

    def test_las_filas_de_una_tabla_quedan_como_etiqueta_y_valor(self):

        texto = texto_plano("<table><tr><td>Persona</td><td>Ana Gómez</td></tr>"
                            "<tr><td><img src='x.png'></td><td>Catpuccino Adopciones</td></tr></table>")

        self.assertEqual(texto.splitlines(), ["Persona: Ana Gómez", "Catpuccino Adopciones"])

    def test_lo_escapado_sigue_siendo_texto(self):

        texto = texto_plano("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")

        self.assertEqual(texto, "<script>alert(1)</script>", "en texto plano es solo texto")

    def test_el_mail_que_sale_lleva_las_dos_versiones(self):

        send_html_email("Asunto", "<p>Hola <b>Ana</b></p>", "sitio@catpuccino.test", "ana@ejemplo.test")

        mensaje = mail.outbox[0]
        self.assertEqual(mensaje.body.split("\n")[0].strip(), "Catpuccino Adopciones")
        self.assertIn("Hola Ana", mensaje.body)
        self.assertNotIn("<b>", mensaje.body)
        self.assertIn("<b>Ana</b>", mensaje.alternatives[0][0])


@override_settings(**SITIO)
class PlantillasTest(TestCase):

    def setUp(self):
        self.rescatista = make_user(email="rescatista@catpuccino.test", instagram="@refugio.michi", handle="refugiomichi")
        self.gato = make_animal(nombre="Michi", sexo="H", edad="2 años", datos="<b>Muy</b> mimosa", cargado_por=self.rescatista)

    def test_el_formulario_nuevo_trae_la_ficha_las_respuestas_y_las_fotos(self):
        from catus.views.adoption import PreAdoptionView

        fields = [("Nombre y Apellido", "Ana Gómez"), ("Celular", "11 4000-7001"),
                  ("1. ¿Por qué querés adoptar?", "Porque sí"),
                  ("Fotos Protección (1)", "https://adopciones.test/forms/abc/foto.jpg"),
                  ("Video", "https://adopciones.test/forms/abc/video.mp4")]
        contexto = dict(PreAdoptionView()._datos_del_mail(fields, self.gato),
                        url_formulario="https://adopciones.test/formularios/h1/")

        html = render_to_string("email/form.html", contexto)

        self.assertIn("Ana Gómez quiere adoptar a Michi", html)
        self.assertEqual(html.count('href="https://adopciones.test/formularios/h1/"'), 2)
        self.assertIn('<img src="https://adopciones.test/forms/abc/foto.jpg"', html)
        self.assertIn("Ver el archivo adjunto", html)
        self.assertNotIn('<img src="https://adopciones.test/forms/abc/video.mp4"', html)
        self.assertEqual([e for e, _ in contexto["ficha"]], ["Nombre y Apellido", "Celular"])

    def test_el_formulario_con_un_animal_escrito_a_mano(self):
        from catus.views.adoption import PreAdoptionView

        datos = PreAdoptionView()._datos_del_mail([("Nombre y Apellido", "Ana Gómez")], "Pelusa")

        self.assertEqual(datos["titulo"], "Ana Gómez quiere adoptar a Pelusa")

    def test_la_confirmacion_ofrece_el_instagram_del_rescatista(self):

        html = render_to_string("email/received.html", {"animal": self.gato, "tipo": "preadoption", "settings": __import__("django.conf").conf.settings})

        self.assertIn("¡Gracias por querer adoptar a Michi!", html)
        self.assertIn("Escribirle a @refugio.michi", html)
        self.assertIn("https://adopciones.test/adopciones/", html)

    def test_publicado_con_un_link_propio_no_le_pega_el_dominio(self):

        self.gato.custom_link = "https://forms.gle/abc"
        self.gato.save()

        MailService().send_mail_aprobacion(self.gato)

        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('href="https://forms.gle/abc"', html)
        self.assertNotIn("https://adopciones.testhttps://", html)
        self.assertIn("https://adopciones.test/refugiomichi/", html)

    def test_animal_nuevo_al_equipo_con_el_boton_de_aprobar(self):

        MailService().send_new_animal_mail(self.gato)

        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('href="https://adopciones.test/animal/aprobar/?id={}"'.format(self.gato.id), html)
        self.assertIn("<b>Muy</b> mimosa", html, "la descripción pasa por html_seguro, como en el sitio")
