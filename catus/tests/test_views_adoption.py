"""Tests del envío del formulario público de pre-adopción.

Es el formulario que completa quien quiere adoptar. Si algo falla acá, la
persona ve un error después de llenar un formulario largo y el rescatista nunca
se entera de que alguien se postuló.
"""
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings

from forms_builder.forms.models import Field, FieldEntry, Form, FormEntry

from catus.models import EstadoFormulario
from catus.tests.factories import make_animal, make_user
from catus.views.adoption import PreAdoptionView


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test")
class EnviarFormularioTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.animal = make_animal(nombre="Willy", cargado_por=self.rescatista)

        self.form = Form.objects.create(title="Pre Adopción")
        self.campo_animal = Field.objects.create(label="Gato a adoptar", field_type=6)
        self.campo_nombre = Field.objects.create(label="Nombre y Apellido", field_type=1)
        self.campo_email = Field.objects.create(label="Email", field_type=1)
        self.campo_otro = Field.objects.create(label="Nombre del gato a adoptar", field_type=1)

    def build_entry(self, animal_value, email="ana@ejemplo.test"):

        entry = FormEntry.objects.create(form=self.form)
        FieldEntry.objects.create(entry=entry, field_id=self.campo_animal.id, value=animal_value)
        FieldEntry.objects.create(entry=entry, field_id=self.campo_nombre.id, value="Ana Gómez")
        FieldEntry.objects.create(entry=entry, field_id=self.campo_email.id, value=email)
        FieldEntry.objects.create(entry=entry, field_id=self.campo_otro.id, value="")
        return entry

    def enviar(self, entry, animal, animal_name):

        request = self.factory.post("/pre-adopcion/", {})
        request.user = make_user(email="anon@ejemplo.test")

        view = PreAdoptionView()
        view.request = request

        estado = EstadoFormulario.objects.create(
            hash="hash-de-prueba", form_entry=entry, gato=animal, tipo="A",
        )
        view.send_email(entry, None, animal_name, estado)
        return estado

    def test_avisa_al_rescatista_cuando_eligen_su_animal(self):

        from catus.services.adoption import AdoptionService

        entry = self.build_entry(str(self.animal.id))
        animal = AdoptionService().get_animal_obj(entry)

        self.enviar(entry, animal, AdoptionService().get_animal(entry))

        destinatarios = [dest for m in mail.outbox for dest in m.to]
        self.assertIn(self.rescatista.email, destinatarios)

    def test_elegir_otro_animal_no_rompe(self):
        """Con la opción "otro" el formulario guarda un nombre escrito a mano.

        En ese caso no hay Animal, así que buscar el mail de su rescatista
        reventaba: la persona veía un 500 después de completar todo el
        formulario y nadie recibía el aviso.
        """

        from catus.services.adoption import AdoptionService

        entry = self.build_entry("0")
        FieldEntry.objects.filter(entry=entry, field_id=self.campo_otro.id).update(value="Michi")

        animal = AdoptionService().get_animal_obj(entry)
        self.assertIsNone(animal)

        self.enviar(entry, animal, AdoptionService().get_animal(entry))

        self.assertTrue(mail.outbox, "no se avisó a nadie del formulario recibido")
        destinatarios = [dest for m in mail.outbox for dest in m.to]
        self.assertIn("catpuccino.ok@gmail.com", destinatarios)

    def test_le_confirma_a_quien_se_postula(self):

        from catus.services.adoption import AdoptionService

        entry = self.build_entry(str(self.animal.id))

        self.enviar(entry, self.animal, AdoptionService().get_animal(entry))

        destinatarios = [dest for m in mail.outbox for dest in m.to]
        self.assertIn("ana@ejemplo.test", destinatarios)

    def test_sin_mail_de_contacto_igual_avisa_al_equipo(self):

        entry = self.build_entry(str(self.animal.id), email="")

        self.enviar(entry, self.animal, self.animal)

        destinatarios = [dest for m in mail.outbox for dest in m.to]
        self.assertIn("catpuccino.ok@gmail.com", destinatarios)

    def test_un_animal_sin_rescatista_no_rompe(self):
        """Los animales cargados antes de que existieran las cuentas no tienen dueño."""

        huerfano = make_animal(nombre="Huérfano", cargado_por=None)
        entry = self.build_entry(str(huerfano.id))

        self.enviar(entry, huerfano, huerfano)

        self.assertTrue(mail.outbox)


class ElegirFormularioTest(TestCase):
    """Qué formulario público se muestra en /pre-adopcion/ y /pre-adopcion/perros/."""

    def setUp(self):
        #el orden de creación importa: antes se elegía por posición
        self.gatos = Form.objects.create(title="Adopción gatos", slug="formulario-de-pre-adopcion")
        self.transito = Form.objects.create(title="Tránsito gatos", slug="formulario-de-transito")
        self.transito_perros = Form.objects.create(title="Tránsito perros", slug="formulario-de-transito-para-perros")
        self.perros = Form.objects.create(title="Adopción perros", slug="formulario-de-pre-adopcion-para-perros")

    def test_gatos_usa_el_formulario_de_gatos(self):

        self.assertEqual(PreAdoptionView()._get_form(), self.gatos)

    def test_perros_usa_el_formulario_de_perros(self):

        from catus.views.adoption import PreAdoptionPerrosView

        self.assertEqual(PreAdoptionPerrosView()._get_form(), self.perros)

    def test_borrar_otro_formulario_no_rompe_el_de_perros(self):
        """Antes se tomaba el de la posición 3: borrar cualquiera lo dejaba en 500."""

        from catus.views.adoption import PreAdoptionPerrosView

        self.transito.delete()

        self.assertEqual(PreAdoptionPerrosView()._get_form(), self.perros)

    def test_borrar_otro_formulario_no_cambia_el_de_gatos(self):
        """Antes, borrar el de gatos hacía que /pre-adopcion/ mostrara el de tránsito."""

        self.assertEqual(PreAdoptionView()._get_form(), self.gatos)

        self.transito.delete()

        self.assertEqual(PreAdoptionView()._get_form(), self.gatos)
