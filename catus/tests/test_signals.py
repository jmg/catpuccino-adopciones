"""Tests de la sincronización del desplegable de animales del formulario público.

Si esto se desincroniza, quien quiere adoptar no encuentra al animal en la lista,
y como corre dentro del save() de Animal, tampoco puede hacer fallar la carga.
"""
from django.test import TestCase

from forms_builder.forms.models import Field, Form

from catus.signals import ANIMAL_FIELD_LABELS, _update_animal_field, _update_form_field
from catus.tests.factories import make_animal, make_field


class SincronizarDesplegableTest(TestCase):

    def setUp(self):
        self.form = Form.objects.create(title="Pre Adopción")
        self.campo_gatos = make_field(self.form, ANIMAL_FIELD_LABELS["G"], choices="0")
        self.campo_perros = make_field(self.form, ANIMAL_FIELD_LABELS["P"], choices="0")

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

        otro = make_field(self.form, "Nombre y Apellido", choices="")
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


class DesplegableDentroDelAltaTest(TestCase):
    """El alta guarda el animal y sus fotos adentro de un transaction.atomic(), todo o nada.

    La columna choices era varchar(1000) y la lista de gatos iba por 918 caracteres el
    2026-11-11. Pasado el límite, MySQL (estricto) rechaza el UPDATE del desplegable y Django
    deja la transacción del alta marcada para deshacer aunque el signal atrape el error: la
    consulta siguiente fallaba y quien cargaba cualquier animal veía un 500.
    """

    def setUp(self):
        self.form = Form.objects.create(title="Pre Adopción")
        make_field(self.form, ANIMAL_FIELD_LABELS["G"], choices="0")
        make_field(self.form, ANIMAL_FIELD_LABELS["P"], choices="0")

    def test_un_error_de_la_base_en_el_desplegable_no_tumba_el_alta(self):

        from unittest import mock
        from django.db import DataError, transaction
        from catus.models import Animal

        with mock.patch.object(Field, "_save_table", side_effect=DataError("Data too long for column 'choices'")):
            with self.assertLogs("catus.signals", level="ERROR"):
                #la sincronización corre al confirmar el alta: acá, al salir de este bloque
                with self.captureOnCommitCallbacks(execute=True):
                    with transaction.atomic():
                        gato = make_animal(nombre="Willy", tipo="G", estado="D", aprobado=True)

                        #lo que sigue en el alta después de guardar el animal
                        gato.nombre = "Willy II"
                        gato.save()

        self.assertTrue(Animal.objects.filter(nombre="Willy II").exists())

    def test_la_columna_alcanza_para_muchos_gatos(self):
        """Con 1000 caracteres entraban unos 190 gatos; con ids de 4 cifras, cada uno ocupa 5."""

        self.assertGreaterEqual(Field._meta.get_field("choices").max_length, 5000)

        lista = ",".join(["0"] + [str(1000 + n) for n in range(900)])
        campo = make_field(self.form, "Otro campo", choices=lista)
        campo.refresh_from_db()
        self.assertEqual(campo.choices, lista)


class CuandoSeSincronizaTest(TestCase):
    """El desplegable se reescribe después de confirmar, y solo si cambió algo que lo afecta.

    Corría sincrónico en cada post_save de Animal, también en los save(update_fields=...) del
    posteo de Instagram o de la revisión con IA, y armaba get_all_for_adoption() -con el
    prefetch de las fotos de todos los animales en adopción- solo para sacar los ids: Jentry
    lo marcaba como N+1 en /animales/.
    """

    def setUp(self):
        self.form = Form.objects.create(title="Pre Adopción")
        self.campo_gatos = make_field(self.form, ANIMAL_FIELD_LABELS["G"], choices="0")
        make_field(self.form, ANIMAL_FIELD_LABELS["P"], choices="0")

    def opciones(self):
        self.campo_gatos.refresh_from_db()
        return self.campo_gatos.choices

    def test_corre_al_confirmar_y_no_antes(self):

        with self.captureOnCommitCallbacks(execute=True) as pendientes:
            gato = make_animal(nombre="Willy", tipo="G")
            self.assertEqual(self.opciones(), "0", "sincronizó antes de confirmar")

        self.assertEqual(len(pendientes), 1)
        self.assertEqual(self.opciones(), "0,{}".format(gato.id))

    def test_un_alta_que_se_deshace_no_toca_el_desplegable(self):
        """Si falla una foto el alta se deshace entera: no tiene que quedar ofrecido un animal
        que no existe."""

        from django.db import transaction

        with self.captureOnCommitCallbacks(execute=True) as pendientes:
            try:
                with transaction.atomic():
                    make_animal(nombre="Willy", tipo="G")
                    raise RuntimeError("se cortó la foto")
            except RuntimeError:
                pass

        self.assertEqual(pendientes, [])
        self.assertEqual(self.opciones(), "0")

    def test_un_save_que_no_toca_el_desplegable_no_lo_sincroniza(self):

        gato = make_animal(nombre="Willy", tipo="G")

        for campos in (["instagram_publicado"], ["revision_ia_estado", "revision_ia_motivo"], ["nombre"], []):
            with self.captureOnCommitCallbacks() as pendientes:
                gato.save(update_fields=campos)
            self.assertEqual(pendientes, [], campos)

    def test_cambiar_estado_aprobado_o_tipo_si_lo_sincroniza(self):

        gato = make_animal(nombre="Willy", tipo="G")

        for campos in (["estado"], ["aprobado"], ["tipo"], ["estado", "expiro_el"]):
            with self.captureOnCommitCallbacks() as pendientes:
                gato.save(update_fields=campos)
            self.assertEqual(len(pendientes), 1, campos)

        with self.captureOnCommitCallbacks() as pendientes:
            gato.save()
        self.assertEqual(len(pendientes), 1, "un save() entero puede haber cambiado cualquier cosa")

    def test_borrar_un_animal_lo_saca(self):

        gato = make_animal(nombre="Willy", tipo="G")
        _update_form_field()

        with self.captureOnCommitCallbacks(execute=True):
            gato.delete()

        self.assertEqual(self.opciones(), "0")

    def test_no_trae_las_fotos_de_los_animales(self):
        """Dos consultas por especie (el campo y los ids), haya los animales y las fotos
        que haya. Las otras son los savepoints de cada especie."""

        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from catus.tests.factories import make_animal_image

        for n in range(5):
            make_animal_image(animal=make_animal(nombre="Gato {}".format(n), tipo="G"))
        _update_form_field()

        with CaptureQueriesContext(connection) as consultas:
            _update_form_field()

        lecturas = [q["sql"] for q in consultas if q["sql"].lstrip().upper().startswith("SELECT")]
        self.assertEqual(len(lecturas), 4, lecturas)
        self.assertFalse([sql for sql in lecturas if "animalimage" in sql], "trajo las fotos")
