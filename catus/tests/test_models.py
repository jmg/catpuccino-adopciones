"""Tests de los modelos y sus reglas de negocio."""
from django.test import TestCase
from django.utils import timezone

from catus.models import Animal, EstadoFormulario
from catus.tests.factories import make_animal, make_estado_formulario, make_user


class BaseEntityTest(TestCase):

    def test_pone_created_at_y_updated_at_solo(self):

        animal = make_animal()

        self.assertIsNotNone(animal.created_at)
        self.assertIsNotNone(animal.updated_at)

    def test_se_puede_releer_de_la_base(self):
        """BaseEntity.__init__ toca kwargs; Django instancia con args posicionales al leer."""

        animal = make_animal(nombre="Pelusa")

        releido = Animal.objects.get(id=animal.id)

        self.assertEqual(releido.nombre, "Pelusa")
        self.assertIsNotNone(releido.created_at)

    def test_respeta_un_created_at_explicito(self):

        fecha = timezone.now() - timezone.timedelta(days=30)

        animal = make_animal(created_at=fecha)

        self.assertEqual(animal.created_at, fecha)


class AnimalTest(TestCase):

    def test_get_all_for_adoption_solo_trae_aprobados_y_disponibles(self):

        disponible = make_animal(nombre="Disponible", estado="D", aprobado=True)
        make_animal(nombre="Sin aprobar", estado="D", aprobado=False)
        make_animal(nombre="Adoptado", estado="A", aprobado=True)
        make_animal(nombre="Reservado", estado="R", aprobado=True)

        resultado = list(Animal.get_all_for_adoption())

        self.assertEqual([a.nombre for a in resultado], [disponible.nombre])

    def test_get_all_for_adoption_filtra_por_tipo(self):

        gato = make_animal(nombre="Gato", tipo="G")
        make_animal(nombre="Perro", tipo="P")

        resultado = list(Animal.get_all_for_adoption(tipo="G"))

        self.assertEqual([a.nombre for a in resultado], [gato.nombre])

    def test_set_estado_adoptado_pone_fecha_de_adopcion(self):

        animal = make_animal()
        self.assertIsNone(animal.fecha_adopcion)

        animal.set_estado("A")

        self.assertIsNotNone(animal.fecha_adopcion)

    def test_set_estado_adoptado_no_pisa_una_fecha_ya_puesta(self):

        fecha = timezone.now() - timezone.timedelta(days=10)
        animal = make_animal(fecha_adopcion=fecha)

        animal.set_estado("A")

        self.assertEqual(animal.fecha_adopcion, fecha)

    def test_get_adoption_url_segun_tipo(self):

        gato = make_animal(tipo="G")
        perro = make_animal(tipo="P")

        self.assertEqual(gato.get_adoption_url(), "/pre-adopcion/?id={}".format(gato.id))
        self.assertEqual(perro.get_adoption_url(), "/pre-adopcion/perros/?id={}".format(perro.id))

    def test_custom_link_gana_sobre_la_url_por_tipo(self):

        animal = make_animal(custom_link="https://ejemplo.test/adoptar")

        self.assertEqual(animal.get_adoption_url(), "https://ejemplo.test/adoptar")

    def test_esta_reservado_refleja_el_estado(self):
        """La tarjeta pública necesita saber si el animal está reservado.

        Antes se consultaba animal.reservado, un campo que no existe: en el template
        eso da siempre falso (Django calla el atributo faltante) y el cartel de
        "Reservado" no aparecía nunca.
        """

        reservado = make_animal(estado="R")
        disponible = make_animal(estado="D")

        self.assertTrue(reservado.esta_reservado())
        self.assertFalse(disponible.esta_reservado())

    def test_fecha_ingreso_se_completa_sola(self):

        animal = Animal.objects.create(nombre="Sin fecha")

        self.assertIsNotNone(animal.fecha_ingreso)


class EstadoFormularioTest(TestCase):

    def test_get_fecha_ingreso_vacio_no_rompe(self):

        estado = make_estado_formulario(fecha_ingreso=None)

        self.assertEqual(estado.get_fecha_ingreso(), "")

    def test_get_persona_devuelve_el_nombre_guardado(self):

        estado = make_estado_formulario(persona_nombre="Ana Gómez")

        self.assertEqual(estado.get_persona(), "Ana Gómez")

    def test_get_persona_sin_datos_devuelve_texto_vacio(self):
        """Se muestra directo en la tabla del admin: None ahí sale como "None"."""

        estado = make_estado_formulario(persona_nombre=None, form_entry=None)

        self.assertEqual(estado.get_persona(), "")

    def test_get_estado_badge_cubre_todos_los_estados(self):

        for estado_valor, _ in EstadoFormulario.choices:
            estado = make_estado_formulario(estado=estado_valor)

            self.assertIsNotNone(
                estado.get_estado_badge(),
                "el estado {} no tiene color de badge".format(estado_valor),
            )


class CatusUserTest(TestCase):

    def test_get_instagram_normaliza_el_arroba(self):

        user = make_user(instagram="catpuccino")

        self.assertEqual(user.get_instagram(), "@catpuccino")

    def test_get_instagram_respeta_una_url(self):

        user = make_user(instagram="https://instagram.com/catpuccino")

        self.assertEqual(user.get_instagram(), "https://instagram.com/catpuccino")

    def test_get_instagram_sin_valor_devuelve_vacio(self):

        self.assertEqual(make_user().get_instagram(), "")

    def test_get_handle_url_usa_el_handle_si_existe(self):

        user = make_user(handle="catpuccino")

        self.assertEqual(user.get_handle_url(), "/catpuccino/")

    def test_get_handle_url_cae_al_id(self):

        user = make_user()

        self.assertEqual(user.get_handle_url(), "/usuario/{}/animales/".format(user.id))
