"""El slug de los campos de forms_builder entra como en la base de producción.

En producción la columna forms_field.slug es varchar(200) NULL desde siempre, y hay slugs de
hasta 195 caracteres, sacados de preguntas largas. Las migraciones decían 100: al armar el
staging (2026-11-09) con una copia de los datos, la carga falló con "Data too long for column
'slug'", y una base nueva no podía guardar esos campos ni editarlos desde el admin.
"""
from django.test import TestCase

from forms_builder.forms.models import Field, Form, SLUG_MAX_LENGTH

PREGUNTA_LARGA = ("¿Tenés balcón, terraza, patio o jardín? Indicá las alturas de las medianeras y, por "
                  "favor, adjuntá fotos donde se vea la protección de ventanas, rejas y balcones, sin "
                  "excluir ninguno de los lugares a los que el gato podría tener acceso desde adentro de la casa")


class SlugDeCamposTest(TestCase):

    def setUp(self):
        self.form = Form.objects.create(title="Pre adopción de prueba", slug="pre-adopcion-de-prueba")

    def test_un_slug_como_los_de_produccion_es_valido(self):

        campo = Field(form=self.form, label="Pregunta", field_type=1, slug="a" * 195)

        campo.full_clean()
        campo.save()

        self.assertEqual(Field.objects.get(id=campo.id).slug, "a" * 195)

    def test_la_columna_es_la_de_produccion(self):

        columna = Field._meta.get_field("slug")

        self.assertEqual((columna.max_length, columna.null), (200, True))
        self.assertEqual(SLUG_MAX_LENGTH, 200)

    def test_el_slug_de_una_pregunta_larguisima_entra_en_la_columna(self):

        campo = Field.objects.create(form=self.form, label=PREGUNTA_LARGA * 2, field_type=1)

        self.assertLessEqual(len(campo.slug), SLUG_MAX_LENGTH)
        campo.full_clean()

    def test_dos_preguntas_iguales_tienen_slugs_distintos_y_entran(self):

        primero = Field.objects.create(form=self.form, label=PREGUNTA_LARGA * 2, field_type=1)
        segundo = Field.objects.create(form=self.form, label=PREGUNTA_LARGA * 2, field_type=1)

        self.assertNotEqual(primero.slug, segundo.slug)
        self.assertLessEqual(len(segundo.slug), SLUG_MAX_LENGTH)
