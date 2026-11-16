"""Tests del envío del formulario público de pre-adopción.

Es el formulario que completa quien quiere adoptar. Si algo falla acá, la
persona ve un error después de llenar un formulario largo y el rescatista nunca
se entera de que alguien se postuló.
"""
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings

from forms_builder.forms.models import FieldEntry, Form

from catus.models import EstadoFormulario
from catus.tests.factories import make_animal, make_field, make_form_entry, make_user
from catus.views.adoption import PreAdoptionView


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test")
class EnviarFormularioTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.animal = make_animal(nombre="Willy", cargado_por=self.rescatista)

        self.form = Form.objects.create(title="Pre Adopción")
        self.campo_animal = make_field(self.form, "Gato a adoptar", 6)
        self.campo_nombre = make_field(self.form, "Nombre y Apellido")
        self.campo_email = make_field(self.form, "Email")
        self.campo_otro = make_field(self.form, "Nombre del gato a adoptar")

    def build_entry(self, animal_value, email="ana@ejemplo.test"):

        entry = make_form_entry(self.form)
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

    def test_responder_el_mail_le_escribe_a_quien_se_postulo(self):
        """El Reply-To eran los mismos destinatarios: "Responder" le escribía al propio
        rescatista y al equipo, nunca al candidato."""

        from catus.services.adoption import AdoptionService

        entry = self.build_entry(str(self.animal.id))
        self.enviar(entry, self.animal, AdoptionService().get_animal(entry))

        aviso = next(m for m in mail.outbox if self.rescatista.email in m.to)
        self.assertEqual(aviso.reply_to, ["ana@ejemplo.test"])

    def test_el_mail_trae_el_boton_de_whatsapp(self):

        from catus.services.adoption import AdoptionService

        campo_celular = make_field(self.form, "Celular")
        entry = self.build_entry(str(self.animal.id))
        FieldEntry.objects.create(entry=entry, field_id=campo_celular.id, value="11 5555-4444")
        self.enviar(entry, self.animal, AdoptionService().get_animal(entry))

        aviso = next(m for m in mail.outbox if self.rescatista.email in m.to)
        html = aviso.alternatives[0][0]
        self.assertIn("https://wa.me/5491155554444", html)
        self.assertIn("Escribirle por WhatsApp", html)

    def test_sin_mail_valido_responder_queda_como_antes(self):

        from catus.services.adoption import AdoptionService

        entry = self.build_entry(str(self.animal.id), email="no tengo")
        self.enviar(entry, self.animal, AdoptionService().get_animal(entry))

        aviso = next(m for m in mail.outbox if self.rescatista.email in m.to)
        self.assertNotIn("no tengo", aviso.reply_to)

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


class AnimalDelLinkTest(TestCase):
    """El animal que trae el link (?id=) en la página del formulario.

    Antes se buscaba sin mirar si estaba aprobado (los ids son correlativos: cualquiera veía
    nombre y foto de uno sin aprobar), y si ya no estaba en adopción la página decía igual
    "Formulario para adoptar a X" con el desplegable sin él: la persona se enteraba al
    final, al enviar, después de unas 40 preguntas.
    """

    def setUp(self):
        Form.objects.create(title="Adopción gatos", slug="formulario-de-pre-adopcion", intro="<p>Requisitos</p>")
        Form.objects.create(title="Adopción perros", slug="formulario-de-pre-adopcion-para-perros", intro="<p>Requisitos</p>")

    def test_un_animal_en_adopcion_encabeza_el_formulario(self):
        animal = make_animal(nombre="Michi")
        response = self.client.get(f"/pre-adopcion/?id={animal.id}")
        self.assertContains(response, "Formulario para adoptar a <b>Michi</b>", html=False)
        self.assertNotContains(response, "aviso-no-disponible\"")

    def test_uno_adoptado_avisa_arriba_que_ya_no_esta(self):
        animal = make_animal(nombre="Michi", estado="A")
        response = self.client.get(f"/pre-adopcion/?id={animal.id}")
        self.assertNotContains(response, "Formulario para adoptar a")
        self.assertContains(response, "Michi ya no está en adopción")

    def test_uno_sin_aprobar_no_se_muestra(self):
        animal = make_animal(nombre="Secreto", aprobado=False)
        response = self.client.get(f"/pre-adopcion/?id={animal.id}")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Secreto")

    def test_el_link_de_un_perro_en_el_formulario_de_gatos_lleva_al_de_perros(self):
        perro = make_animal(nombre="Toby", tipo="P")
        response = self.client.get(f"/pre-adopcion/?id={perro.id}")
        self.assertRedirects(response, f"/pre-adopcion/perros/?id={perro.id}", fetch_redirect_response=False)

    def test_un_id_que_no_es_un_numero_no_rompe(self):
        response = self.client.get("/pre-adopcion/?id=abc")
        self.assertEqual(response.status_code, 200)

    def test_el_desplegable_obliga_a_elegir(self):
        """Sin opción vacía quedaba elegido el primero de la lista sin que nadie lo eligiera."""
        response = self.client.get("/pre-adopcion/")
        self.assertContains(response, 'vacia.text = isDog ? "Elegí un perro" : "Elegí un gato";')
        self.assertContains(response, "select.required = true;")
