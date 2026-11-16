"""Cuántas consultas cuesta un formulario de pre-adopción.

AdoptionService lee las respuestas por la etiqueta de su pregunta, y FieldEntry.field_id no
es una FK: cada lectura buscaba la pregunta de cada respuesta con su propia consulta, y la
página del formulario y el envío leen las respuestas cuatro o cinco veces. Con las ~40
preguntas del formulario de gatos eran unas doscientas consultas a forms_field por página
(Jentry las marcaba como N+1 en /formularios/<hash>/ y /pre-adopcion/). Ahora se leen una
vez por pedido: lo que se mide acá es que no crezca con la cantidad de preguntas.
"""
import shutil
import tempfile

from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from forms_builder.forms.models import FieldEntry, Form

from catus.services.adoption import AdoptionService
from catus.test_login_throttle import fake_memcached
from catus.tests.factories import make_animal, make_estado_formulario, make_field, make_form_entry, make_user
from catus.views.forms import FormView


def consultas_a_preguntas(consultas):
    return [q["sql"] for q in consultas if "forms_field" in q["sql"] and "forms_fieldentry" not in q["sql"]]


class ServicioTest(TestCase):

    def setUp(self):
        self.animal = make_animal(nombre="Willy")
        self.form = Form.objects.create(title="Pre Adopción")
        self.entry = make_form_entry(self.form)
        for etiqueta, valor in [("Nombre del gato a adoptar", str(self.animal.id)), ("Nombre y Apellido", "Ana Pérez"),
                                ("Email", "ana@ejemplo.test"), ("Edad", "34.0")]:
            campo = make_field(self.form, etiqueta, 13 if etiqueta == "Edad" else 1)
            FieldEntry.objects.create(entry=self.entry, field_id=campo.id, value=valor)

    def test_varias_lecturas_del_mismo_formulario_son_dos_consultas(self):

        with self.assertNumQueries(2):
            AdoptionService().get_form_attr(self.entry, "Nombre y Apellido")
            AdoptionService().get_form_attrs(self.entry, ["Email", "Edad"], exact=True, convert_to_str=True)
            AdoptionService().get_form_attr(self.entry, "Email")

    def test_sigue_leyendo_por_la_etiqueta(self):

        servicio = AdoptionService()

        self.assertEqual(servicio.get_form_attr(self.entry, "nombre y apellido"), "Ana Pérez")
        self.assertEqual(servicio.get_form_attrs(self.entry, ["Email", "Edad"], exact=True, convert_to_str=True),
                         [("Email", "ana@ejemplo.test"), ("Edad", 34)])
        self.assertEqual(servicio.get_animal_obj(self.entry), self.animal)

    def test_convertir_la_edad_no_cambia_lo_que_leen_los_demas(self):
        """La conversión pisaba form_field.value; con las respuestas compartidas, lo que
        leyera después cualquier otro en el mismo pedido salía convertido."""

        AdoptionService().get_form_attrs(self.entry, ["Edad"], exact=True, convert_to_str=True)

        self.assertEqual(AdoptionService().get_form_attr(self.entry, "Edad"), "34.0")

    def test_lo_que_cambia_set_animal_name_otro_se_ve_en_el_mismo_pedido(self):

        from catus.views.adoption import PreAdoptionView

        AdoptionService().get_form_attr(self.entry, "Email")
        PreAdoptionView().set_animal_name_otro(self.entry, "Michi")

        self.assertEqual(AdoptionService().get_form_attr(self.entry, "Nombre del gato"), "Michi")
        self.assertEqual(FieldEntry.objects.get(entry=self.entry, value="Michi").value, "Michi")


class PaginaDelFormularioTest(TestCase):
    """/formularios/<hash>/, la que abren el rescatista y el equipo."""

    def setUp(self):
        self.rescatista = make_user()
        self.animal = make_animal(nombre="Willy", cargado_por=self.rescatista)

    def formulario(self, preguntas, hash_):
        form = Form.objects.create(title="Pre Adopción {}".format(hash_))
        entry = make_form_entry(form)
        etiquetas = ["Nombre del gato a adoptar", "Nombre y Apellido", "Email", "Celular"]
        etiquetas += ["Pregunta {}".format(n) for n in range(preguntas)]
        for etiqueta in etiquetas:
            campo = make_field(form, etiqueta)
            valor = str(self.animal.id) if etiqueta.startswith("Nombre del gato") else "respuesta"
            FieldEntry.objects.create(entry=entry, field_id=campo.id, value=valor)
        return make_estado_formulario(animal=self.animal, hash=hash_, form_entry=entry, tipo="A")

    def abrir(self, hash_):
        request = RequestFactory().get("/formularios/{}/".format(hash_))
        request.user = self.rescatista
        with CaptureQueriesContext(connection) as consultas:
            respuesta = FormView.as_view()(request, form_hash=hash_)
            respuesta.render()
        self.assertEqual(respuesta.status_code, 200)
        return consultas

    def test_no_crece_con_la_cantidad_de_preguntas(self):

        self.formulario(5, "corto")
        self.formulario(40, "largo")

        corto, largo = self.abrir("corto"), self.abrir("largo")

        self.assertEqual(len(largo), len(corto), "cada pregunta de más suma consultas")
        #las respuestas (1), la lista de abajo (1) y las adopciones anteriores
        #(services/historial.py, 2): cada una trae todas las preguntas de una vez
        self.assertLessEqual(len(consultas_a_preguntas(largo)), 4, consultas_a_preguntas(largo))
        self.assertLessEqual(len(largo), 25)


@override_settings(ENV="TEST", SEND_MAIL="sitio@catpuccino.test")
class EnvioDelFormularioTest(TestCase):
    """El POST de /pre-adopcion/, que completa cualquiera desde la ficha del animal."""

    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)

        self.animal = make_animal(nombre="Willy", cargado_por=make_user())

        #el contador del embudo (services/embudo.py) crea su fila del día con el primer
        #envío (3 consultas) y después la actualiza (1): no depende de las preguntas, pero
        #corriéndolo antes los dos envíos que se comparan hacen lo mismo
        from catus.services import embudo
        embudo.contar("G", "enviado")

    def enviar(self, preguntas, visitante):
        Form.objects.all().delete()
        form = Form.objects.create(title="Pre adopción", slug="formulario-de-pre-adopcion", response="Recibido, gracias")
        valores = {}
        for etiqueta in ["Nombre del gato a adoptar", "Nombre y Apellido", "Email"] + ["Pregunta {}".format(n) for n in range(preguntas)]:
            campo = make_field(form, etiqueta)
            valores[campo.slug] = {"Nombre del gato a adoptar": str(self.animal.id), "Nombre y Apellido": "Ana Pérez",
                                   "Email": "ana@ejemplo.test"}.get(etiqueta, "una respuesta")

        with CaptureQueriesContext(connection) as consultas:
            respuesta = self.client.post("/pre-adopcion/?id={}".format(self.animal.id), valores, HTTP_X_FORWARDED_FOR=visitante)

        self.assertContains(respuesta, "Recibido, gracias")
        return consultas

    def test_no_crece_con_la_cantidad_de_preguntas(self):

        corto = self.enviar(5, "190.2.3.4")
        largo = self.enviar(40, "190.2.3.5")

        self.assertEqual(len(largo), len(corto), "cada pregunta de más suma consultas")
        self.assertLessEqual(len(consultas_a_preguntas(largo)), 4, consultas_a_preguntas(largo))
