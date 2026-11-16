"""La edad en meses que se estima del texto libre de la edad (services/edad.py), lo que
hace Animal.save() con ella y la migración que la completó en los animales que ya estaban.

La portada filtra por Cachorros (menos de 12 meses) y Adultos con Animal.edad_en_meses,
que casi nunca se completaba: la edad se escribe como sale ("6/7 meses", "1 año y medio
aprox", "45 días", "bebés"). Un animal mal estimado aparece en el filtro que no es, así que
ante la duda el parser devuelve None y el animal solo aparece con "Todos".
"""
import importlib
from datetime import date
from unittest import mock

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from catus.models import Animal
from catus.services.edad import estimar_meses
from catus.tests.factories import make_animal

HOY = date(2024, 11, 15)


class EstimarMesesTest(SimpleTestCase):

    def assertMeses(self, casos):

        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(estimar_meses(texto, hoy=HOY), esperado)

    def test_una_cantidad_con_su_unidad(self):

        self.assertMeses([
            ("2 meses", 2), ("3 años", 36), ("10 años", 120), ("45 días", 1), ("40 dias", 1),
            ("3 semanas", 0), ("5 semanas", 1), ("8 meses aprox.", 8), ("2 años aproximadamente", 24),
            ("aprox 2 años", 24), ("+5 años", 60), ("más de 10 años", 120), ("Tiene 4 meses", 4),
        ])

    def test_numeros_en_letras_y_medio(self):

        self.assertMeses([
            ("Un año", 12), ("dos años", 24), ("once meses", 11), ("un mes", 1),
            ("medio año", 6), ("año y medio", 18), ("AÑO Y MEDIO", 18), ("mes y medio", 1),
            ("un mes y medio", 1), ("2 meses y medio", 2), ("5 años y medio", 66),
            ("1 año y medio aprox", 18), ("1 y medio años", 18),
        ])

    def test_decimales_con_coma_o_con_punto(self):

        self.assertMeses([("1,5 años", 18), ("1.5 años", 18), ("6,7 meses", 6)])

    def test_rangos_dan_el_punto_medio(self):

        self.assertMeses([
            ("6/7 meses", 6), ("4-5 meses", 4), ("2 a 3 años", 30), ("entre 3 y 4 meses", 3),
            ("2 o 3 meses", 2), ("1/2 años", 18), ("3/4 años", 42),
        ])

    def test_una_fraccion_en_singular_es_una_parte_de_la_unidad(self):
        """"1/2 año" es medio año; "1/2 años", de uno a dos."""

        self.assertMeses([("1/2 año", 6)])

    def test_se_suman_las_partes(self):

        self.assertMeses([
            ("1 año y 2 meses", 14), ("1 año, 3 meses", 15), ("1 año 2 meses", 14),
            ("11 meses y 3 semanas", 11), ("dos meses y tres semanas", 2),
        ])

    def test_menos_de_y_casi_restan(self):
        """"Menos de un año" es un cachorro: con 12 caía en Adultos."""

        self.assertMeses([("menos de un año", 11), ("casi 1 año", 11), ("menos de 2 meses", 1)])

    def test_unidades_pegadas_y_diminutivos(self):

        self.assertMeses([("7m", 7), ("12meses", 12), ("1año", 12), ("2 mesecitos", 2), ("3 añitos", 36)])

    def test_vale_la_primera_edad_que_aparece(self):
        """Una camada con la mamá: no se suman las dos edades."""

        self.assertMeses([("2 meses los gatitos, la mamá 2 años", 2), ("1 año y 6/7 meses", 12)])

    def test_una_fecha_de_nacimiento(self):

        self.assertMeses([
            ("Nació el 15/03/2024", 8), ("nacido el 16/03/2024", 7), ("03/2024", 8),
            ("marzo de 2024", 8), ("Nacidos el 20/10/24", 0),
        ])

    def test_si_hay_edad_y_fecha_gana_la_edad(self):

        self.assertMeses([("2 meses (nacidos el 1/9/2024)", 2)])

    def test_una_fecha_futura_o_imposible_no_es_una_edad(self):

        self.assertMeses([("nace el 10/12/2025", None), ("31/13/2024", None)])

    def test_palabras_sin_numero(self):

        self.assertMeses([
            ("bebés", 2), ("recién nacidos", 0), ("Cachorro", 6), ("cachorrita", 6),
            ("Adulto", 24), ("Adulta joven", 24), ("Senior", 96), ("Adulto mayor", 96), ("abuelito", 96),
        ])

    def test_lo_que_no_se_puede_saber_es_none(self):
        """Mejor sin edad que en el filtro que no es."""

        self.assertMeses([
            ("", None), (None, None), ("No sé", None), ("desconocida", None), ("?", None),
            ("Joven", None), ("2", None), ("3 gatitos", None), ("año", None), ("meses", None),
        ])

    def test_un_numero_absurdo_es_none(self):

        self.assertMeses([("2000 meses", None), ("9" * 300 + " años", None), ("31 años", None)])

    def test_no_levanta_con_nada(self):
        """Corre adentro de Animal.save(): ningún texto lo puede hacer fallar."""

        raros = [
            12, b"2 meses", "🐱🐱", "\u0301\u0301", "<b>2</b> meses", "&amp; 3 años", "1e999 años",
            "/" * 500, "- - - 1", "1/0 años", "0/0 meses", "a" * 10000, "y medio", "medio",
            "31/02/2024", "00/2024", "1 " * 5000,
        ]
        for texto in raros:
            with self.subTest(texto=str(texto)[:30]):
                resultado = estimar_meses(texto)
                self.assertTrue(resultado is None or 0 <= resultado <= 360)


class EdadEnMesesAlGuardarTest(TestCase):
    """Animal.save() completa edad_en_meses cuando está vacío o cambió el texto."""

    def test_se_completa_al_crear(self):

        animal = make_animal(edad="6/7 meses")

        animal.refresh_from_db()
        self.assertEqual(animal.edad_en_meses, 6)

    def test_sin_edad_queda_vacio(self):

        self.assertIsNone(make_animal(edad=None).edad_en_meses)
        self.assertIsNone(make_animal(edad="no sabemos").edad_en_meses)

    def test_se_recalcula_si_cambia_el_texto(self):

        animal = make_animal(edad="2 meses")
        animal = Animal.objects.get(id=animal.id)

        animal.edad = "1 año y medio"
        animal.save()

        animal.refresh_from_db()
        self.assertEqual(animal.edad_en_meses, 18)

    def test_cambiar_dos_veces_la_misma_instancia(self):
        """Después de guardar, lo guardado es la edad nueva: el segundo cambio también cuenta."""

        animal = make_animal(edad="2 meses")
        animal.edad = "3 años"
        animal.save()
        animal.edad = "4 meses"
        animal.save()

        animal.refresh_from_db()
        self.assertEqual(animal.edad_en_meses, 4)

    def test_un_valor_puesto_a_mano_se_respeta_si_la_edad_no_cambia(self):
        """El admin deja editar edad_en_meses: guardar otra cosa no lo pisa."""

        animal = make_animal(edad="2 meses")
        Animal.objects.filter(id=animal.id).update(edad_en_meses=5)
        animal = Animal.objects.get(id=animal.id)

        animal.nombre = "Otro nombre"
        animal.save()

        animal.refresh_from_db()
        self.assertEqual(animal.edad_en_meses, 5)

    def test_completa_uno_viejo_que_no_lo_tenia(self):

        animal = make_animal(edad="3 años")
        Animal.objects.filter(id=animal.id).update(edad_en_meses=None)
        animal = Animal.objects.get(id=animal.id)

        animal.save()

        animal.refresh_from_db()
        self.assertEqual(animal.edad_en_meses, 36)

    def test_update_fields_con_la_edad_guarda_tambien_los_meses(self):

        animal = Animal.objects.get(id=make_animal(edad="2 meses").id)
        animal.edad = "2 años"
        animal.save(update_fields=["edad"])

        animal.refresh_from_db()
        self.assertEqual(animal.edad_en_meses, 24)

    def test_update_fields_sin_la_edad_no_la_toca(self):

        animal = make_animal(edad="2 meses")
        Animal.objects.filter(id=animal.id).update(edad_en_meses=None)
        animal = Animal.objects.get(id=animal.id)

        animal.estado = "R"
        animal.save(update_fields=["estado"])

        animal.refresh_from_db()
        self.assertEqual(animal.estado, "R")
        self.assertIsNone(animal.edad_en_meses)

    def test_con_la_edad_diferida_no_la_lee(self):
        """Con only() la edad no está cargada: leerla sería una consulta más por animal."""

        animal = make_animal(edad="2 meses")
        diferido = Animal.objects.only("id", "nombre", "fecha_ingreso").get(id=animal.id)

        diferido.nombre = "Renombrado"
        diferido.save(update_fields=["nombre"])

        self.assertIn("edad", diferido.get_deferred_fields())
        self.assertEqual(Animal.objects.get(id=animal.id).edad_en_meses, 2)

    def test_si_el_parser_falla_el_animal_se_guarda_igual(self):
        """Lo peor que puede pasar es quedarse sin edad en meses, como estaban casi todos."""

        with mock.patch("catus.services.edad.estimar_meses", side_effect=RuntimeError("roto")), \
                self.assertLogs("catus.models", level="ERROR"):
            animal = make_animal(nombre="Michi", edad="2 meses")

        self.assertTrue(Animal.objects.filter(id=animal.id, nombre="Michi").exists())


class MigracionEdadEnMesesTest(TestCase):
    """0046_edad_en_meses: completa los animales que ya estaban, con su copia del parser."""

    migracion = importlib.import_module("catus.migrations.0046_edad_en_meses")

    def test_completa_solo_los_que_no_tienen_valor(self):

        sin_valor = make_animal(nombre="Sin valor", edad="1 año y medio")
        con_valor = make_animal(nombre="Con valor", edad="2 meses")
        sin_edad = make_animal(nombre="Sin edad", edad=None)
        incierto = make_animal(nombre="Incierto", edad="joven")
        Animal.objects.filter(id=sin_valor.id).update(edad_en_meses=None)
        Animal.objects.filter(id=con_valor.id).update(edad_en_meses=40)

        self.migracion.completar_edad_en_meses(apps, None)

        meses = dict(Animal.objects.values_list("nombre", "edad_en_meses"))
        self.assertEqual(meses, {"Sin valor": 18, "Con valor": 40, "Sin edad": None, "Incierto": None})

    def test_la_copia_entiende_los_casos_de_siempre(self):
        """La copia congelada no se mantiene al día, pero al escribirla era el mismo parser."""

        for texto, esperado in [("6/7 meses", 6), ("1 año y medio aprox", 18), ("45 días", 1), ("bebés", 2)]:
            with self.subTest(texto=texto):
                self.assertEqual(self.migracion.estimar_meses(texto, HOY), esperado)
