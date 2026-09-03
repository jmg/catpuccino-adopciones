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


class CatusUserAdminTest(TestCase):
    """CatusUser es el modelo de login: el admin no puede escribirle la contraseña."""

    def setUp(self):
        from catus.admin import CatusUserAdmin
        from catus.models import CatusUser

        self.admin = CatusUserAdmin(CatusUser, AdminSite())

    def test_la_contrasena_no_es_editable(self):
        """Un ModelAdmin común la mostraba como texto y la guardaba sin hashear."""

        self.assertIn("password", self.admin.get_readonly_fields(None))

    def test_el_formulario_no_expone_la_contrasena_como_campo(self):

        form = self.admin.get_form(None)

        self.assertNotIn("password", form.base_fields)

    def test_cuenta_los_animales_del_rescatista(self):

        user = make_user(instagram="catpuccino")
        make_animal(cargado_por=user)
        make_animal(cargado_por=user)
        make_animal(cargado_por=make_user(email="otra@catpuccino.test"))

        self.assertEqual(self.admin.animal_count(user), 2)


class AprobarAnimalesTest(TestCase):
    """La acción en lote del listado de animales."""

    def setUp(self):
        from catus.admin import AnimalAdmin

        self.admin = AnimalAdmin(Animal, AdminSite())
        self.request = None

    def aprobar(self, queryset):

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        request = RequestFactory().post("/")
        request.session = {}
        request._messages = FallbackStorage(request)

        self.admin.aprobar_animales(request, queryset)

    def test_aprueba_los_seleccionados(self):

        make_animal(nombre="Uno", aprobado=False, cargado_por=make_user())

        self.aprobar(Animal.objects.all())

        self.assertTrue(Animal.objects.get(nombre="Uno").aprobado)

    def test_un_animal_sin_rescatista_no_corta_la_tanda(self):
        """Antes el mail de aviso explotaba y los siguientes quedaban sin aprobar."""

        make_animal(nombre="Huérfano", aprobado=False, cargado_por=None)
        make_animal(nombre="Con dueño", aprobado=False, cargado_por=make_user())

        self.aprobar(Animal.objects.all())

        self.assertTrue(Animal.objects.get(nombre="Huérfano").aprobado)
        self.assertTrue(Animal.objects.get(nombre="Con dueño").aprobado)

    def test_no_reprocesa_los_ya_aprobados(self):

        make_animal(nombre="Ya estaba", aprobado=True, cargado_por=make_user())

        self.aprobar(Animal.objects.all())

        self.assertTrue(Animal.objects.get(nombre="Ya estaba").aprobado)
