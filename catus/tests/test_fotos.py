"""Tests del formset de fotos y del widget que las muestra.

Un animal publicado sin fotos no sirve para nada en un sitio de adopciones, así
que el formulario tiene que impedir quedarse sin ninguna.
"""
from django.forms import inlineformset_factory
from django.test import TestCase

from catus.forms import AnimalImageForm, RequiredImageInlineFormset
from catus.models import Animal, AnimalImage
from catus.tests.factories import make_animal, make_animal_image, uploaded_photo


def build_formset(data, files=None, instance=None):

    ImageFormSet = inlineformset_factory(
        Animal, AnimalImage, extra=0, can_delete=True,
        form=AnimalImageForm, formset=RequiredImageInlineFormset,
    )
    return ImageFormSet(data, files or {}, instance=instance)


def base_data(total, initial=0):

    return {
        "animalimage_set-TOTAL_FORMS": str(total),
        "animalimage_set-INITIAL_FORMS": str(initial),
        "animalimage_set-MIN_NUM_FORMS": "0",
        "animalimage_set-MAX_NUM_FORMS": "1000",
    }


def fila(indice, imagen_id=None, borrar=False):

    prefijo = "animalimage_set-{}-".format(indice)
    datos = {
        prefijo + "id": str(imagen_id) if imagen_id else "",
        prefijo + "animal": "",
        prefijo + "crop_x": "", prefijo + "crop_y": "",
        prefijo + "crop_w": "", prefijo + "crop_h": "",
    }
    if borrar:
        datos[prefijo + "DELETE"] = "on"
    return datos


class AlMenosUnaFotoTest(TestCase):

    def test_un_animal_nuevo_con_una_foto_es_valido(self):

        datos = base_data(1)
        datos.update(fila(0))

        formset = build_formset(datos, {"animalimage_set-0-image": uploaded_photo()})

        self.assertTrue(formset.is_valid(), formset.errors)

    def test_un_animal_nuevo_sin_fotos_no_es_valido(self):

        formset = build_formset(base_data(0))

        self.assertFalse(formset.is_valid())
        self.assertTrue(any("foto" in e.lower() for e in formset.non_form_errors()))

    def test_no_se_puede_borrar_la_unica_foto(self):

        animal = make_animal()
        imagen = make_animal_image(animal=animal)

        datos = base_data(1, initial=1)
        datos.update(fila(0, imagen_id=imagen.id, borrar=True))

        formset = build_formset(datos, instance=animal)

        self.assertFalse(formset.is_valid())

    def test_no_se_pueden_borrar_todas_las_fotos(self):
        """Con dos o más fotos se podían tildar todas y el animal quedaba sin ninguna."""

        animal = make_animal()
        primera = make_animal_image(animal=animal)
        segunda = make_animal_image(animal=animal)

        datos = base_data(2, initial=2)
        datos.update(fila(0, imagen_id=primera.id, borrar=True))
        datos.update(fila(1, imagen_id=segunda.id, borrar=True))

        formset = build_formset(datos, instance=animal)

        self.assertFalse(formset.is_valid(), "dejó al animal publicado sin fotos")

    def test_se_puede_borrar_una_de_dos(self):

        animal = make_animal()
        primera = make_animal_image(animal=animal)
        segunda = make_animal_image(animal=animal)

        datos = base_data(2, initial=2)
        datos.update(fila(0, imagen_id=primera.id, borrar=True))
        datos.update(fila(1, imagen_id=segunda.id))

        formset = build_formset(datos, instance=animal)

        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())

    def test_se_puede_borrar_la_vieja_si_se_sube_una_nueva(self):

        animal = make_animal()
        vieja = make_animal_image(animal=animal)

        datos = base_data(2, initial=1)
        datos.update(fila(0, imagen_id=vieja.id, borrar=True))
        datos.update(fila(1))

        formset = build_formset(datos, {"animalimage_set-1-image": uploaded_photo()}, instance=animal)

        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())


class ImagePreviewWidgetTest(TestCase):
    """El widget del input de foto."""

    def test_el_input_conserva_su_id(self):
        """Sin id, la etiqueta no apunta al input y el selector de recorte no lo encuentra."""

        form = AnimalImageForm(prefix="animalimage_set-0")

        html = str(form["image"])

        self.assertIn('id="id_animalimage_set-0-image"', html)

    def test_muestra_la_foto_ya_cargada(self):

        imagen = make_animal_image()

        form = AnimalImageForm(instance=imagen, prefix="animalimage_set-0")
        html = str(form["image"])

        self.assertIn("<img", html)

    def test_el_nombre_del_archivo_va_escapado(self):

        from catus.forms import ImagePreviewWidget

        html = ImagePreviewWidget().render("image", "gallery/a'><script>alert(1)</script>.jpg")

        self.assertNotIn("<script>", html)
