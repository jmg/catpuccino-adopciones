"""Tests de las columnas calculadas del admin de Django.

Son las que arman los listados que el equipo abre todos los días. Si una tira
excepción con una fila, no se rompe esa celda: no abre el listado entero.
"""
from django.contrib.admin.sites import AdminSite
from django.test import TestCase

from catus.admin import AnimalAdmin, EstadoFormularioAdmin
from catus.models import Animal, EstadoFormulario
from catus.tests.factories import make_animal, make_estado_formulario, make_user


class AnimalAdminTest(TestCase):

    def setUp(self):
        self.admin = AnimalAdmin(Animal, AdminSite())

    def test_las_columnas_andan_con_un_animal_normal(self):

        animal = make_animal(cargado_por=make_user(instagram="catpuccino"))

        self.assertIn("catpuccino", self.admin.usuario(animal))
        self.assertIn("Generar Imagen", self.admin.utilidades(animal))

    def test_las_columnas_andan_sin_rescatista(self):
        """Al dar de baja a un rescatista sus animales quedan con cargado_por en NULL."""

        animal = make_animal(cargado_por=None)

        self.assertEqual(self.admin.usuario(animal), " ()")
        self.assertIn("Generar Imagen", self.admin.utilidades(animal))

    def test_sin_rescatista_no_ofrece_acciones_sobre_el_rescatista(self):

        animal = make_animal(cargado_por=None)

        utilidades = self.admin.utilidades(animal)

        self.assertNotIn("settingslogin", utilidades)
        self.assertNotIn("preguntaradopcion", utilidades)

    def test_el_link_de_instagram_sin_publicar(self):

        animal = make_animal(instagram_media_url=None)

        self.assertEqual(self.admin.ig_link(animal), "")


class EstadoFormularioAdminTest(TestCase):

    def setUp(self):
        self.admin = EstadoFormularioAdmin(EstadoFormulario, AdminSite())

    def test_muestra_el_rescatista_del_animal(self):

        animal = make_animal(cargado_por=make_user(instagram="catpuccino"))
        estado = make_estado_formulario(animal=animal)

        self.assertIn("catpuccino", self.admin.animal_cargado_por(estado))

    def test_anda_con_un_formulario_sin_animal(self):
        """Al borrar un animal, los formularios de sus candidatos quedan con gato en NULL."""

        estado = make_estado_formulario(animal=None)

        self.assertEqual(self.admin.animal_cargado_por(estado), "")

    def test_anda_con_un_animal_sin_rescatista(self):

        estado = make_estado_formulario(animal=make_animal(cargado_por=None))

        self.assertEqual(self.admin.animal_cargado_por(estado), "")
