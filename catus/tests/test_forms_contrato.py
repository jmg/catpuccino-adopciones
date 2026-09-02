"""Tests del formulario del contrato de adopción.

El contrato se imprime y se firma, así que un campo que quedó opcional por error
termina en blanco en un papel firmado.
"""
from django.test import TestCase

from catus.forms import ContratoForm, ContratoPersonaForm


class FieldsRequiredTest(TestCase):
    """RequiredFieldsMixin ignora en silencio los nombres que no son campos del form.

    Un nombre viejo en fields_required no da error: simplemente deja de exigir
    ese dato y nadie se entera hasta ver el contrato impreso vacío.
    """

    def assert_fields_required_existen(self, form_class):

        form = form_class()
        declarados = set(getattr(form_class.Meta, "fields_required", []))
        reales = set(form.fields)

        inexistentes = declarados - reales
        self.assertEqual(
            inexistentes, set(),
            "{}.Meta.fields_required nombra campos que no existen: {}".format(
                form_class.__name__, sorted(inexistentes),
            ),
        )

    def test_contrato_form(self):

        self.assert_fields_required_existen(ContratoForm)

    def test_contrato_persona_form(self):

        self.assert_fields_required_existen(ContratoPersonaForm)

    def test_los_campos_declarados_quedan_obligatorios(self):

        form = ContratoForm()

        for nombre in ContratoForm.Meta.fields_required:
            self.assertTrue(
                form.fields[nombre].required,
                "{} tendría que ser obligatorio".format(nombre),
            )

    def test_la_persona_a_cargo_es_obligatoria(self):
        """Se imprime en el contrato firmado: no puede quedar en blanco."""

        form = ContratoForm(data={"gato_nombre": "Willy", "gato_color": "naranja",
                                  "gato_fecha_nacimiento": "01/01/2020", "gato_edad": "2 años"})

        self.assertFalse(form.is_valid())
        self.assertIn("miembro_adopcion_nombre", form.errors)
