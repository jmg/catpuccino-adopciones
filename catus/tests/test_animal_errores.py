"""Tests de los mensajes de error al cargar un animal.

Es el momento en el que un rescatista se traba y abandona la carga, así que el
cartel tiene que decir qué corregir.
"""
from django.forms import inlineformset_factory
from django.test import TestCase

from catus.forms import AnimalForm, AnimalImageForm, RequiredImageInlineFormset
from catus.models import Animal, AnimalImage
from catus.tests.factories import make_user, uploaded_photo
from catus.views.animal import EditView


def build_formset(data, files=None, instance=None):

    ImageFormSet = inlineformset_factory(
        Animal, AnimalImage, extra=0, can_delete=True,
        form=AnimalImageForm, formset=RequiredImageInlineFormset,
    )
    return ImageFormSet(data, files or {}, instance=instance)


def formset_data(total=0, **extra):

    data = {
        "animalimage_set-TOTAL_FORMS": str(total),
        "animalimage_set-INITIAL_FORMS": "0",
        "animalimage_set-MIN_NUM_FORMS": "0",
        "animalimage_set-MAX_NUM_FORMS": "1000",
    }
    data.update(extra)
    return data


class MensajesDeErrorTest(TestCase):

    def setUp(self):
        self.view = EditView()
        self.user = make_user()

    def mensajes(self, animal_data, formset_extra=None, files=None, total=0):

        datos = formset_data(total=total, **(formset_extra or {}))
        datos.update(animal_data)

        animal_form = AnimalForm(datos)
        animal_form.is_valid()

        image_form_set = build_formset(datos, files)
        image_form_set.is_valid()

        return self.view.get_error_messages(animal_form, image_form_set)

    def test_avisa_que_falta_la_foto(self):
        """Es el error más común y el que antes no se mostraba."""

        mensajes = self.mensajes({"nombre": "Willy", "tipo": "G", "estado": "D", "sexo": "M"})

        self.assertTrue(
            any("foto" in mensaje.lower() for mensaje in mensajes),
            "no se avisa que falta la foto: {}".format(mensajes),
        )

    def test_avisa_que_falta_el_nombre_con_la_etiqueta_del_campo(self):

        mensajes = self.mensajes({"tipo": "G", "estado": "D", "sexo": "M"})

        texto = " ".join(mensajes)
        self.assertIn("Nombre", texto, "el error no nombra el campo: {}".format(mensajes))

    def test_nunca_devuelve_una_lista_vacia(self):
        """Un cartel de error en blanco deja a la persona sin saber qué hacer."""

        mensajes = self.mensajes({})

        self.assertTrue(mensajes)
        self.assertTrue(all(mensaje.strip() for mensaje in mensajes))

    def test_los_mensajes_son_texto_plano(self):
        """Se muestran en una lista del template: no pueden traer HTML de Django."""

        mensajes = self.mensajes({})

        for mensaje in mensajes:
            self.assertIsInstance(mensaje, str)
            self.assertNotIn("<ul", mensaje)
            self.assertNotIn("errorlist", mensaje)

    def test_no_inventa_errores_cuando_todo_esta_bien(self):

        datos = formset_data(
            total=1,
            **{
                "animalimage_set-0-id": "",
                "animalimage_set-0-animal": "",
                "animalimage_set-0-crop_x": "",
                "animalimage_set-0-crop_y": "",
                "animalimage_set-0-crop_w": "",
                "animalimage_set-0-crop_h": "",
            }
        )
        datos.update({"nombre": "Willy", "tipo": "G", "estado": "D", "sexo": "M", "edad": "2 años"})

        animal_form = AnimalForm(datos)
        image_form_set = build_formset(datos, {"animalimage_set-0-image": uploaded_photo()})

        self.assertTrue(animal_form.is_valid(), animal_form.errors)
        self.assertTrue(image_form_set.is_valid(), image_form_set.errors)
