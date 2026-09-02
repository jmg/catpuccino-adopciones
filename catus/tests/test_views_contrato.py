"""Tests del contrato de adopción.

Hay dos pantallas distintas y es importante no confundirlas:
  /formulario/<id>/contrato/  la usa el equipo, y muestra los datos personales
                              del adoptante. El id es correlativo.
  /contrato/<hash>/           la usa el adoptante para completar sus datos, sin
                              cuenta, entrando por el link que se le manda.
"""
import os
import shutil
import tempfile

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings

from catus.models import Contrato, ContratoPersona, EstadoFormulario
from catus.tests.factories import make_animal, make_estado_formulario, make_user


class ContratoViewTestCase(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.admin = make_user(email="admin@catpuccino.test", is_superuser=True, is_staff=True)
        self.animal = make_animal(nombre="Willy")
        self.estado_form = make_estado_formulario(animal=self.animal, hash="form-hash", estado="A")

        self.adoptante = ContratoPersona.objects.create(
            persona_nombre="Ana Gómez",
            persona_dni="30111222",
            persona_direccion="Calle Falsa 123",
            persona_email="ana@ejemplo.test",
        )
        self.contrato = Contrato.objects.create(
            hash="contrato-hash",
            estado_formulario=self.estado_form,
            gato=self.animal,
            adoptante=self.adoptante,
        )


class EditViewAccesoTest(ContratoViewTestCase):
    """La pantalla del equipo expone nombre, DNI, dirección y teléfono del adoptante."""

    def test_la_pantalla_del_equipo_pide_login(self):

        from catus.views.contrato import EditView

        self.assertTrue(EditView().requiere_login())

    def test_un_anonimo_no_entra_por_id(self):

        from catus.views.contrato import EditView

        request = self.factory.get("/formulario/{}/contrato/".format(self.estado_form.id))
        request.user = AnonymousUser()

        response = EditView.as_view()(request, estado_id=str(self.estado_form.id))

        self.assertEqual(response.status_code, 302, "los datos personales quedaron públicos")
        self.assertIn("/accounts/login/", response.url)

    def test_el_adoptante_si_entra_por_hash(self):
        """El adoptante no tiene cuenta: entra por el link con el hash."""

        from catus.views.contrato import EditPersonaView

        request = self.factory.get("/contrato/contrato-hash/")
        request.user = AnonymousUser()

        view = EditPersonaView()
        view.request = request
        view.kwargs = {"contrato_hash": "contrato-hash"}

        #no renderizamos el template (pide crispy/bootstrap4): alcanza con que no pida login
        self.assertFalse(view.requiere_login())


@override_settings()
class DownloadContractViewTest(ContratoViewTestCase):
    """Descargar el PDF ya completado del contrato."""

    def setUp(self):
        super().setUp()
        self.static_dir = tempfile.mkdtemp()
        self.override = override_settings(STATICFILES_DIRS=[self.static_dir])
        self.override.enable()

        os.makedirs(os.path.join(self.static_dir, "contrato", self.contrato.hash))

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.static_dir, ignore_errors=True)
        super().tearDown()

    def escribir_pdf_generado(self):
        """Escribe el PDF con el mismo nombre que usa generate_contrato_pdf()."""

        from catus.services.contrato import CONTRATO_COMPLETADO_FILE_NAME

        ruta = os.path.join(self.static_dir, "contrato", self.contrato.hash, CONTRATO_COMPLETADO_FILE_NAME)
        with open(ruta, "wb") as f:
            f.write(b"%PDF-1.4 contrato de prueba")
        return ruta

    def descargar(self, user, contrato_id):

        from catus.views.contrato import DownloadContractView

        request = self.factory.get("/contrato_adopcion/{}/download/".format(contrato_id))
        request.user = user
        return DownloadContractView.as_view()(request, contrato_id=str(contrato_id))

    def test_descarga_el_pdf_que_se_genero(self):
        """La vista leía un nombre de archivo que el generador nunca escribe."""

        self.escribir_pdf_generado()

        response = self.descargar(self.admin, self.contrato.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_un_contrato_inexistente_no_rompe(self):

        response = self.descargar(self.admin, 999999)

        self.assertEqual(response.status_code, 200)

    def test_sin_el_pdf_generado_avisa_en_vez_de_romper(self):

        response = self.descargar(self.admin, self.contrato.id)

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response["Content-Type"], "application/pdf")

    def test_un_anonimo_no_descarga(self):

        self.escribir_pdf_generado()

        response = self.descargar(AnonymousUser(), self.contrato.id)

        self.assertEqual(response.status_code, 302)


class ContratoPorPropiedadTest(ContratoViewTestCase):
    """El registro es abierto, así que "estar logueado" no alcanza como permiso.

    Los ids de formulario y de contrato son correlativos: sin chequeo de propiedad
    se podían recorrer los datos personales de todos los adoptantes.
    """

    def setUp(self):
        super().setUp()
        self.duenio = make_user(email="duenio@catpuccino.test")
        self.intruso = make_user(email="intruso@catpuccino.test")
        self.animal.cargado_por = self.duenio
        self.animal.save()

    def abrir_contrato(self, user):

        from catus.views.contrato import EditView

        request = self.factory.get("/formulario/{}/contrato/".format(self.estado_form.id))
        request.user = user

        view = EditView()
        view.request = request
        view.kwargs = {"estado_id": str(self.estado_form.id)}
        return view.req()

    def test_un_intruso_no_abre_el_contrato_de_otro(self):

        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            self.abrir_contrato(self.intruso)

    def test_el_equipo_puede_verlo(self):

        from catus.views.contrato import EditView

        request = self.factory.get("/")
        request.user = self.admin
        view = EditView()
        view.request = request

        self.assertTrue(view.puede_ver(self.estado_form))

    def test_el_duenio_del_animal_puede_verlo(self):

        from catus.views.contrato import EditView

        request = self.factory.get("/")
        request.user = self.duenio
        view = EditView()
        view.request = request

        self.assertTrue(view.puede_ver(self.estado_form))

    def test_el_adoptante_entra_por_hash_sin_cuenta(self):

        from catus.views.contrato import EditPersonaView

        request = self.factory.get("/")
        request.user = AnonymousUser()
        view = EditPersonaView()
        view.request = request

        self.assertTrue(view.puede_ver(self.estado_form))

    def test_un_intruso_no_descarga_el_pdf_de_otro(self):

        from django.core.exceptions import PermissionDenied
        from catus.views.contrato import DownloadContractView

        request = self.factory.get("/contrato_adopcion/{}/download/".format(self.contrato.id))
        request.user = self.intruso

        with self.assertRaises(PermissionDenied):
            DownloadContractView.as_view()(request, contrato_id=str(self.contrato.id))
