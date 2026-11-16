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

    def test_animal_nuevo_al_equipo_lleva_a_la_cola_y_no_aprueba(self):
        """El botón era un link que aprobaba con un GET: lo aprobaba cualquier cosa que
        abriera el link (la vista previa del mail, el antivirus que revisa los links). Ahora
        lleva a la cola, donde aprobar es un POST."""

        MailService().send_new_animal_mail(self.gato)

        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('href="https://adopciones.test/tools/animalespendientes/#animal-{}"'.format(self.gato.id), html)
        self.assertNotIn("/animal/aprobar/", html)
        self.assertIn("<b>Muy</b> mimosa", html, "la descripción pasa por html_seguro, como en el sitio")

    def test_animal_nuevo_al_equipo_con_lo_que_dijo_la_revision(self):
        """Es lo primero que hay que mirar, y antes había que entrar al sitio para verlo."""

        self.gato.revision_ia_estado = "R"
        self.gato.revision_ia_motivo = "No se ve ningún animal en las fotos."
        self.gato.save()

        MailService().send_new_animal_mail(self.gato)

        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("Revisión automática", html)
        self.assertIn("Revisar a mano", html)
        self.assertIn("No se ve ningún animal en las fotos.", html)

    def test_el_que_vuelve_a_revision_dice_por_que_no_se_habia_publicado(self):

        MailService().send_new_animal_mail(self.gato, vuelve=True, motivo_anterior="Repetido: ya está como <Michi>")

        mensaje = mail.outbox[0]
        html = mensaje.alternatives[0][0]
        self.assertEqual(mensaje.subject, "Catpuccino Adopciones - Vuelve a revisión: Michi")
        self.assertIn("Vuelve a revisión", html)
        self.assertIn("Repetido: ya está como &lt;Michi&gt;", html, "el motivo es texto: va escapado")


@override_settings(**SITIO)
class NoPublicadoMailTest(TestCase):
    """Al rescatista, cuando el equipo decide no publicar su animal ("No publicar" en la
    cola, o archivar_pendientes). Antes no se le decía nada: el animal quedaba "En revisión"
    para siempre y la persona no sabía por qué ni qué hacer."""

    def setUp(self):
        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.gato = make_animal(nombre="Michi", cargado_por=self.rescatista, aprobado=False)

    def html(self):

        return mail.outbox[0].alternatives[0][0]

    def test_dice_cual_el_motivo_y_como_volver(self):

        MailService().send_mail_no_publicado(self.rescatista, [self.gato], "Fotos o datos insuficientes")

        mensaje = mail.outbox[0]
        self.assertEqual(mensaje.to, ["rescatista@catpuccino.test"])
        self.assertEqual(mensaje.subject, "Catpuccino Adopciones - Michi no se publicó")
        self.assertIn("Michi no se publicó", self.html())
        self.assertIn("Fotos o datos insuficientes", self.html())
        self.assertIn("Si sigue en adopción, editalo y lo volvemos a mirar.", self.html())
        self.assertIn('href="https://adopciones.test/animales/{}/"'.format(self.gato.id), self.html())

    def test_sin_motivo_igual_dice_como_volver(self):

        MailService().send_mail_no_publicado(self.rescatista, [self.gato], None)

        self.assertNotIn("Motivo", self.html())
        self.assertIn("Si sigue en adopción, editalo y lo volvemos a mirar.", self.html())

    def test_el_motivo_que_ya_dice_como_volver_no_se_repite(self):

        from catus.services.pendientes import MOTIVO_SIN_REVISION

        MailService().send_mail_no_publicado(self.rescatista, [self.gato], MOTIVO_SIN_REVISION)

        #en el cuerpo: el resumen oculto que muestra la bandeja de entrada lo dice siempre
        cuerpo = self.html().split('class="mail-cuerpo"')[1]
        self.assertEqual(cuerpo.count("editalo y lo volvemos a mirar"), 1)

    def test_el_nombre_y_el_motivo_van_escapados(self):

        self.gato.nombre = "<img src=x onerror=alert(1)>"
        self.gato.save()

        MailService().send_mail_no_publicado(self.rescatista, [self.gato], "Otro: <b>raro</b>")

        self.assertNotIn("<img src=x", self.html())
        self.assertNotIn("<b>raro</b>", self.html())

    def test_varios_animales_van_en_un_solo_mail(self):

        otro = make_animal(nombre="Pelusa", cargado_por=self.rescatista, aprobado=False)

        MailService().send_mail_no_publicado(self.rescatista, [self.gato, otro], "Pasó mucho tiempo")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Catpuccino Adopciones - 2 animales no se publicaron")
        self.assertIn("Michi", self.html())
        self.assertIn("Pelusa", self.html())
        self.assertIn('href="https://adopciones.test/accounts/profile/"', self.html())

    def test_al_que_se_saca_del_sitio_se_le_dice_eso(self):

        MailService().send_mail_no_publicado(self.rescatista, [self.gato], None, sacado_del_sitio=True)

        self.assertEqual(mail.outbox[0].subject, "Catpuccino Adopciones - Michi ya no está publicado")
        self.assertIn("la sacamos del sitio", self.html())

    def test_sin_mail_no_rompe(self):

        sin_mail = make_user(email="", username="sinmail")

        MailService().send_mail_no_publicado(sin_mail, [self.gato], None)

        self.assertEqual(len(mail.outbox), 0)
