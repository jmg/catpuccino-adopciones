"""El recuadro "Ya adoptó por Catpuccino" de la página de un formulario (services/historial.py):
otras adopciones de la misma persona en el sitio, reconocida por su mail o su celular."""
from datetime import datetime, timezone as tz

from django.test import TestCase
from forms_builder.forms.models import FieldEntry, Form

from catus.models import Animal
from catus.services.historial import adopciones_anteriores
from catus.tests.factories import make_animal, make_estado_formulario, make_field, make_form_entry, make_user


class AdopcionesAnterioresTest(TestCase):

    def setUp(self):
        self.rescatista = make_user(email="rescatista@catpuccino.test")
        self.form = Form.objects.create(title="Pre adopción", slug="formulario-de-pre-adopcion")
        self.campos = {etiqueta: make_field(self.form, etiqueta) for etiqueta in ("Nombre y Apellido", "Email", "Celular")}
        self.michi = make_animal(nombre="Michi", cargado_por=self.rescatista)
        self.actual = self.formulario("actual", self.michi, "Ana Gómez", "ana.gomez@ejemplo.test", "11 5555-1234")

    def formulario(self, hash, animal, nombre, mail, celular, estado="N", tipo="A"):
        entry = make_form_entry(self.form)
        for etiqueta, valor in (("Nombre y Apellido", nombre), ("Email", mail), ("Celular", celular)):
            FieldEntry.objects.create(entry=entry, field_id=self.campos[etiqueta].id, value=valor)
        return make_estado_formulario(animal=animal, hash=hash, tipo=tipo, estado=estado, form_entry=entry)

    def adoptado(self, nombre, fecha, **kwargs):
        return make_animal(nombre=nombre, estado="A", fecha_adopcion=fecha, cargado_por=self.rescatista, **kwargs)

    def test_lo_encuentra_por_el_mail(self):

        tom = self.adoptado("Tom", datetime(2026, 10, 2, tzinfo=tz.utc))
        self.formulario("previo", tom, "Ana", "ANA.GOMEZ@ejemplo.test ", "", estado="A")

        self.assertEqual(adopciones_anteriores(self.actual), [{"animal": "Tom", "tipo": "gato", "fecha": datetime(2026, 10, 2, tzinfo=tz.utc)}])

    def test_lo_encuentra_por_el_celular_escrito_de_otra_forma(self):

        rex = self.adoptado("Rex", datetime(2026, 9, 1, tzinfo=tz.utc), tipo="P")
        self.formulario("previo", rex, "Ana G.", "otra@ejemplo.test", "+54 9 11 5555-1234", estado="A", tipo="AP")

        self.assertEqual([(a["animal"], a["tipo"]) for a in adopciones_anteriores(self.actual)], [("Rex", "perro")])

    def test_cuenta_el_formulario_vinculado_al_elegir_quien_lo_adopto(self):

        luna = self.adoptado("Luna", datetime(2026, 8, 1, tzinfo=tz.utc))
        previo = self.formulario("previo", None, "Ana", "ana.gomez@ejemplo.test", "", estado="P")
        Animal.objects.filter(id=luna.id).update(estado_formulario=previo)

        self.assertEqual([a["animal"] for a in adopciones_anteriores(self.actual)], ["Luna"])

    def test_no_cuenta_lo_que_no_es_una_adopcion_ni_a_otra_persona(self):

        tom = self.adoptado("Tom", datetime(2026, 10, 2, tzinfo=tz.utc))
        self.formulario("pendiente", tom, "Ana", "ana.gomez@ejemplo.test", "", estado="N")
        self.formulario("de-otra", tom, "Beto", "beto@ejemplo.test", "11 4444-0000", estado="A")

        self.assertEqual(adopciones_anteriores(self.actual), [])

    def test_un_dato_de_relleno_no_identifica_a_nadie(self):

        actual = self.formulario("relleno", self.michi, "Ana", "no@no.com", "0000000000")
        tom = self.adoptado("Tom", datetime(2026, 10, 2, tzinfo=tz.utc))
        self.formulario("previo", tom, "Otra persona", "no@no.com", "0000000000", estado="A")

        self.assertEqual(adopciones_anteriores(actual), [])

    def test_el_mismo_animal_no_es_una_adopcion_anterior(self):
        """Dos formularios por el mismo animal: es la misma adopción."""

        Animal.objects.filter(id=self.michi.id).update(estado="A", fecha_adopcion=datetime(2026, 11, 1, tzinfo=tz.utc))
        self.formulario("duplicado", self.michi, "Ana", "ana.gomez@ejemplo.test", "", estado="A")

        self.assertEqual(adopciones_anteriores(self.actual), [])

    def test_la_pagina_muestra_el_recuadro_solo_si_adopto_antes(self):

        self.client.force_login(self.rescatista)
        self.assertNotIn("Ya adoptó por Catpuccino", self.client.get("/formularios/actual/").content.decode())

        tom = self.adoptado("Tom <b>", datetime(2026, 10, 2, 15, tzinfo=tz.utc))
        self.formulario("previo", tom, "Ana", "ana.gomez@ejemplo.test", "", estado="A")
        pagina = self.client.get("/formularios/actual/").content.decode()

        self.assertIn("Ya adoptó por Catpuccino", pagina)
        self.assertIn("Tom &lt;b&gt;", pagina, "el nombre del animal sale escapado")
        self.assertIn("02/10/2026", pagina)
