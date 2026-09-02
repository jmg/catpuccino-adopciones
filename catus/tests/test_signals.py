"""Tests de la sincronización del desplegable de animales del formulario público.

Si esto se desincroniza, quien quiere adoptar no encuentra al animal en la lista,
y como corre dentro del save() de Animal, tampoco puede hacer fallar la carga.
"""
from django.test import TestCase

from forms_builder.forms.models import Field

from catus.signals import ANIMAL_FIELD_LABELS, _update_animal_field, _update_form_field
from catus.tests.factories import make_animal


class SincronizarDesplegableTest(TestCase):

    def setUp(self):
        self.campo_gatos = Field.objects.create(label=ANIMAL_FIELD_LABELS["G"], choices="0")
        self.campo_perros = Field.objects.create(label=ANIMAL_FIELD_LABELS["P"], choices="0")

    def test_lista_los_gatos_en_adopcion(self):

        gato = make_animal(nombre="Willy", tipo="G", estado="D", aprobado=True)

        _update_form_field()

        self.campo_gatos.refresh_from_db()
        self.assertEqual(self.campo_gatos.choices, "0,{}".format(gato.id))

    def test_no_mezcla_gatos_con_perros(self):

        gato = make_animal(nombre="Willy", tipo="G")
        perro = make_animal(nombre="Rocco", tipo="P")

        _update_form_field()

        self.campo_gatos.refresh_from_db()
        self.campo_perros.refresh_from_db()
        self.assertEqual(self.campo_gatos.choices, "0,{}".format(gato.id))
        self.assertEqual(self.campo_perros.choices, "0,{}".format(perro.id))

    def test_saca_a_los_que_ya_no_estan_en_adopcion(self):

        gato = make_animal(nombre="Willy", tipo="G", estado="D")
        _update_form_field()

        gato.estado = "A"
        gato.save()
        _update_form_field()

        self.campo_gatos.refresh_from_db()
        self.assertEqual(self.campo_gatos.choices, "0")

    def test_no_toca_campos_que_no_son_el_del_animal(self):
        """Buscar el campo por posición podía pisarle las opciones a otro campo."""

        otro = Field.objects.create(label="Nombre y Apellido", choices="")
        make_animal(tipo="G")

        _update_form_field()

        otro.refresh_from_db()
        self.assertEqual(otro.choices, "")

    def test_si_falta_el_campo_de_gatos_igual_actualiza_los_perros(self):
        """Un problema con una especie no puede dejar desactualizada a la otra."""

        self.campo_gatos.delete()
        perro = make_animal(nombre="Rocco", tipo="P")

        _update_form_field()

        self.campo_perros.refresh_from_db()
        self.assertEqual(self.campo_perros.choices, "0,{}".format(perro.id))

    def test_sin_campos_no_rompe(self):

        Field.objects.all().delete()

        _update_form_field()

    def test_guardar_un_animal_no_falla_si_la_sincronizacion_falla(self):
        """Corre dentro de post_save: un error acá no puede tumbar la carga del animal."""

        from unittest import mock

        with mock.patch("catus.signals._update_animal_field", side_effect=RuntimeError("boom")):
            with self.assertLogs("catus.signals", level="ERROR"):
                _update_form_field()

    def test_no_reescribe_si_no_cambio_nada(self):
        """Corre en cada save de animal: si nada cambió, no tiene que escribir."""

        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        make_animal(tipo="G")
        _update_form_field()

        with CaptureQueriesContext(connection) as queries:
            _update_form_field()

        escrituras = [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith("UPDATE")]
        self.assertEqual(escrituras, [], "reescribió el campo sin necesidad")

    def test_sin_animales_no_deja_una_opcion_vacia(self):
        """Un "0," suelto agrega una opción en blanco al desplegable público."""

        _update_form_field()

        self.campo_gatos.refresh_from_db()
        self.assertEqual(self.campo_gatos.choices, "0")
        self.assertNotIn(",,", self.campo_gatos.choices)
        self.assertFalse(self.campo_gatos.choices.endswith(","))
