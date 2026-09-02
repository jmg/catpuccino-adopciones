"""Tests de AdoptionService, que lee las respuestas de los formularios públicos.

Las respuestas se buscan por el LABEL en español del campo ("Nombre y Apellido",
"Email"). Es frágil por diseño, así que conviene tenerlo cubierto: si alguien renombra
un campo en el admin, estos tests no lo detectan, pero sí detectan que el servicio
degrade mal cuando el dato no está.
"""
from django.test import TestCase

from forms_builder.forms.models import Field, FieldEntry, Form, FormEntry

from catus.services.adoption import AdoptionService
from catus.tests.factories import make_animal


class AdoptionServiceTestCase(TestCase):

    def setUp(self):
        self.service = AdoptionService()
        self.form = Form.objects.create(title="Pre Adopción")

    def add_field(self, entry, label, value, field_type=1):

        field = Field.objects.create(label=label, field_type=field_type)
        FieldEntry.objects.create(entry=entry, field_id=field.id, value=value)
        return field

    def make_entry(self, campos):
        """campos: lista de (label, value) o (label, value, field_type)."""

        entry = FormEntry.objects.create(form=self.form)
        for campo in campos:
            self.add_field(entry, *campo)
        return entry


class GetFormAttrTest(AdoptionServiceTestCase):

    def test_encuentra_el_valor_por_label(self):

        entry = self.make_entry([("Nombre y Apellido", "Ana Gómez")])

        self.assertEqual(self.service.get_form_attr(entry, "Nombre y Apellido"), "Ana Gómez")

    def test_matchea_sin_importar_mayusculas(self):

        entry = self.make_entry([("NOMBRE Y APELLIDO", "Ana Gómez")])

        self.assertEqual(self.service.get_form_attr(entry, "nombre y apellido"), "Ana Gómez")

    def test_devuelve_vacio_si_el_campo_no_existe(self):

        entry = self.make_entry([("Email", "ana@test.com")])

        self.assertEqual(self.service.get_form_attr(entry, "Nombre y Apellido"), "")

    def test_sin_formulario_devuelve_vacio(self):

        self.assertEqual(self.service.get_form_attr(None, "Email"), "")

    def test_ignora_campos_cuyo_Field_fue_borrado(self):
        """Si borran el campo del formulario, las respuestas viejas quedan huérfanas."""

        entry = FormEntry.objects.create(form=self.form)
        FieldEntry.objects.create(entry=entry, field_id=99999, value="huérfano")
        self.add_field(entry, "Email", "ana@test.com")

        self.assertEqual(self.service.get_form_attr(entry, "Email"), "ana@test.com")


class GetAnimalObjTest(AdoptionServiceTestCase):

    def test_encuentra_el_animal_por_el_primer_campo(self):

        animal = make_animal(nombre="Willy")
        entry = self.make_entry([("Gato a adoptar", str(animal.id))])

        self.assertEqual(self.service.get_animal_obj(entry), animal)

    def test_cero_significa_otro_animal(self):

        entry = self.make_entry([("Gato a adoptar", "0")])

        self.assertIsNone(self.service.get_animal_obj(entry))

    def test_un_id_inexistente_no_rompe(self):

        entry = self.make_entry([("Gato a adoptar", "999999")])

        self.assertIsNone(self.service.get_animal_obj(entry))

    def test_un_formulario_sin_respuestas_no_rompe(self):
        """Antes hacía [...][0] sobre una lista vacía: IndexError y 500."""

        entry = FormEntry.objects.create(form=self.form)

        self.assertIsNone(self.service.get_animal_obj(entry))

    def test_sin_formulario_devuelve_none(self):

        self.assertIsNone(self.service.get_animal_obj(None))


class GetAdoptanteTest(AdoptionServiceTestCase):

    def test_devuelve_el_nombre_del_adoptante(self):

        from catus.models import EstadoFormulario

        entry = self.make_entry([("Nombre y Apellido", "Ana Gómez")])
        estado = EstadoFormulario.objects.create(hash="h", form_entry=entry)

        self.assertEqual(self.service.get_adoptante(estado), "Ana Gómez")

    def test_sin_el_campo_no_rompe(self):
        """Se usa al generar el contrato: un IndexError ahí corta el flujo del admin."""

        from catus.models import EstadoFormulario

        entry = self.make_entry([("Email", "ana@test.com")])
        estado = EstadoFormulario.objects.create(hash="h", form_entry=entry)

        self.assertEqual(self.service.get_adoptante(estado), "")

    def test_sin_form_entry_no_rompe(self):

        from catus.models import EstadoFormulario

        estado = EstadoFormulario.objects.create(hash="h", form_entry=None)

        self.assertEqual(self.service.get_adoptante(estado), "")


class GetFormattedFieldsTest(AdoptionServiceTestCase):

    def test_devuelve_label_y_valor(self):

        entry = self.make_entry([("Email", "ana@test.com")])

        self.assertEqual(
            self.service.get_formatted_fields(entry.fields.all()),
            [("Email", "ana@test.com")],
        )

    def test_los_numeros_se_muestran_sin_decimales(self):

        entry = self.make_entry([("Edad", "35.0", 13)])

        self.assertEqual(self.service.get_formatted_fields(entry.fields.all()), [("Edad", 35)])

    def test_un_numero_invalido_se_muestra_tal_cual(self):

        entry = self.make_entry([("Edad", "treinta y cinco", 13)])

        self.assertEqual(
            self.service.get_formatted_fields(entry.fields.all()),
            [("Edad", "treinta y cinco")],
        )

    def test_las_fotos_salen_como_link_absoluto(self):

        entry = self.make_entry([("Foto del hogar", "gallery/casa.jpg", 9)])

        label, value = self.service.get_formatted_fields(entry.fields.all())[0]

        self.assertEqual(label, "Foto del hogar")
        self.assertIn("gallery/casa.jpg", value)
        self.assertIn("<a", value)

    def test_las_fotos_en_modo_html_salen_como_img(self):

        entry = self.make_entry([("Foto del hogar", "gallery/casa.jpg", 9)])

        _, value = self.service.get_formatted_fields(entry.fields.all(), photos_html=True)[0]

        self.assertIn("<img", value)

    def test_una_foto_vacia_no_rompe(self):

        entry = self.make_entry([("Foto del hogar", "", 9)])

        self.assertEqual(self.service.get_formatted_fields(entry.fields.all()), [("Foto del hogar", "")])

    def test_el_nombre_del_archivo_se_escapa(self):
        """El nombre lo elige quien sube la foto y termina dentro de un atributo HTML."""

        entry = self.make_entry([("Foto", "gallery/a' onerror='alert(1).jpg", 9)])

        _, value = self.service.get_formatted_fields(entry.fields.all(), photos_html=True)[0]

        self.assertNotIn("onerror='alert(1)", value)
