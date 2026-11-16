"""Los animales salen del sitio al mes de publicados (cron expirar_animales) y el panel le
pregunta al rescatista si siguen en adopción: republicar es un clic por animal."""
import json
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from forms_builder.forms.models import Form

from catus.models import Animal
from catus.signals import ANIMAL_FIELD_LABELS
from catus.tests.factories import make_animal, make_field, make_user


def hace(dias):
    return timezone.now() - timedelta(days=dias)


class ExpirarAnimalesTest(TestCase):

    def setUp(self):
        self.rescatista = make_user()

    def correr(self, *args):

        salida = StringIO()
        call_command("expirar_animales", *args, stdout=salida, stderr=StringIO())
        return salida.getvalue()

    def animal(self, dias, **kwargs):
        return make_animal(cargado_por=self.rescatista, fecha_ingreso=hace(dias), **kwargs)

    def test_expira_al_publicado_hace_mas_de_un_mes(self):

        viejo = self.animal(31)

        salida = self.correr()

        viejo.refresh_from_db()
        self.assertEqual(viejo.estado, "E")
        self.assertIsNotNone(viejo.expiro_el)
        self.assertIn("1 animales expirados", salida)
        self.assertNotIn(viejo, Animal.get_all_for_adoption())

    def test_no_toca_a_los_demas(self):
        """El reciente sigue publicado; el reservado tiene a alguien en proceso; el que
        nunca se aprobó no está en el sitio; el adoptado ya salió."""

        reciente = self.animal(29)
        reservado = self.animal(90, estado="R")
        pendiente = self.animal(90, aprobado=False)
        adoptado = self.animal(90, estado="A")

        self.correr()

        for animal, estado in ((reciente, "D"), (reservado, "R"), (pendiente, "D"), (adoptado, "A")):
            animal.refresh_from_db()
            self.assertEqual(animal.estado, estado)
            self.assertIsNone(animal.expiro_el)

    def test_simular_no_toca_nada(self):

        viejo = self.animal(31)

        salida = self.correr("--simular")

        viejo.refresh_from_db()
        self.assertEqual(viejo.estado, "D")
        self.assertIn("expirarían 1", salida)

    def test_lo_saca_del_desplegable_del_formulario(self):
        """El comando hace un UPDATE, que no dispara el signal de Animal.save(): si no
        actualizara el desplegable a mano, el formulario público seguiría ofreciendo
        animales que ya no están en el sitio."""

        form = Form.objects.create(title="Pre adopción", slug="formulario-de-pre-adopcion")
        campo = make_field(form, ANIMAL_FIELD_LABELS["G"], choices="0")
        make_field(form, ANIMAL_FIELD_LABELS["P"], choices="0")
        #el desplegable se sincroniza al confirmar cada save
        with self.captureOnCommitCallbacks(execute=True):
            viejo, reciente = self.animal(31), self.animal(2)
        campo.refresh_from_db()
        self.assertIn(str(viejo.id), campo.choices.split(","))

        self.correr()

        campo.refresh_from_db()
        self.assertEqual(campo.choices.split(","), ["0", str(reciente.id)])

    def test_no_queda_agendado_para_instagram(self):

        viejo = self.animal(31, instagram_listo_para_publicar=True, instagram_programado_para=timezone.now())

        self.correr()

        viejo.refresh_from_db()
        self.assertFalse(viejo.instagram_listo_para_publicar)
        self.assertIsNone(viejo.instagram_programado_para)

    def test_el_republicado_tiene_otro_mes(self):
        """Republicar arranca el mes de nuevo: si no, la corrida siguiente lo volvía a sacar."""

        viejo = self.animal(400)
        self.correr()
        self.client.force_login(self.rescatista)

        self.client.post("/animal/marcarenadopcion/", {"animal_id": viejo.id})
        self.correr()

        viejo.refresh_from_db()
        self.assertEqual(viejo.estado, "D")
        self.assertIsNone(viejo.expiro_el)
        self.assertGreater(viejo.fecha_ingreso, hace(1))


class TarjetaRepublicarTest(TestCase):
    """La tarjeta "¿Siguen en adopción?" del panel."""

    def setUp(self):
        self.rescatista = make_user()
        self.client.force_login(self.rescatista)

    def expirado(self, nombre="Willy", **kwargs):

        kwargs.setdefault("cargado_por", self.rescatista)
        kwargs.setdefault("expiro_el", timezone.now())
        return make_animal(nombre=nombre, estado="E", fecha_ingreso=hace(40), **kwargs)

    def panel(self):
        return self.client.get("/accounts/profile/").content.decode()

    def test_pregunta_por_los_que_expiro_el_cron(self):

        animal = self.expirado("Tom <b>")

        html = self.panel()

        self.assertIn("¿Siguen en adopción?", html)
        self.assertIn('id="pregunta-adopcion-{}"'.format(animal.id), html)
        self.assertIn("Tom &lt;b&gt;", html, "el nombre sale escapado")

    def test_no_pregunta_por_los_que_expiro_una_persona_ni_por_los_de_otra_cuenta(self):

        self.expirado("A mano", expiro_el=None)
        self.expirado("Ajeno", cargado_por=make_user(email="otra@catpuccino.test"))

        self.assertNotIn("¿Siguen en adopción?", self.panel())

    def test_expirar_a_mano_no_deja_la_pregunta(self):

        animal = make_animal(cargado_por=self.rescatista)

        self.client.post("/animal/marcarexpirado/", {"animal_id": animal.id})

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "E")
        self.assertNotIn("¿Siguen en adopción?", self.panel())

    def test_republicar_lo_devuelve_al_sitio_y_saca_la_pregunta(self):

        animal = self.expirado()

        respuesta = self.client.post("/animal/marcarenadopcion/", {"animal_id": animal.id})

        self.assertTrue(json.loads(respuesta.content)["success"])
        self.assertIn(animal, Animal.get_all_for_adoption())
        self.assertNotIn("¿Siguen en adopción?", self.panel())

    def test_no_republicar_no_vuelve_a_preguntar(self):

        animal = self.expirado()

        self.client.post("/animal/posponerpreguntaadopcion/", {"animal_id": animal.id, "para_siempre": "1"})

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "E")
        self.assertNotIn("¿Siguen en adopción?", self.panel())

    def test_no_se_puede_republicar_el_animal_de_otra_cuenta(self):

        ajeno = self.expirado(cargado_por=make_user(email="otra@catpuccino.test"))

        self.client.post("/animal/marcarenadopcion/", {"animal_id": ajeno.id})

        ajeno.refresh_from_db()
        self.assertEqual(ajeno.estado, "E")
