"""Tests de editar un animal ya cargado, sin tocar las fotos.

Las URLs de las fotos ya viajaron por mail (el aviso de animal nuevo las embebe),
así que renombrar archivos al guardar deja esos mails con imágenes rotas.
"""
import shutil
import tempfile

from django.forms import inlineformset_factory
from django.test import TestCase, override_settings

from catus.forms import AnimalImageForm, RequiredImageInlineFormset
from catus.models import Animal, AnimalImage
from catus.tests.factories import make_animal, make_animal_image, make_user


class EditarSinTocarFotosTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.user = make_user()
        self.animal = make_animal(nombre="Willy", cargado_por=self.user)
        self.primera = make_animal_image(animal=self.animal)
        self.segunda = make_animal_image(animal=self.animal)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def build_formset(self):
        """Reconstruye el POST tal como lo manda el navegador con el form sin tocar."""

        ImageFormSet = inlineformset_factory(
            Animal, AnimalImage, extra=0, can_delete=True,
            form=AnimalImageForm, formset=RequiredImageInlineFormset,
        )

        datos = {
            "animalimage_set-TOTAL_FORMS": "2",
            "animalimage_set-INITIAL_FORMS": "2",
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
        }

        for indice, imagen in enumerate([self.primera, self.segunda]):
            prefijo = "animalimage_set-{}-".format(indice)
            datos[prefijo + "id"] = str(imagen.id)
            datos[prefijo + "animal"] = str(self.animal.id)
            #el navegador manda de vuelta lo que el widget renderizó
            for campo in AnimalImageForm.CROP_FIELDS:
                valor = getattr(imagen, campo)
                datos[prefijo + campo] = "" if valor is None else str(valor)

        return ImageFormSet(datos, {}, instance=self.animal)

    def test_guardar_sin_tocar_las_fotos_no_las_reescribe(self):
        """save() solo debe devolver las fotos que cambiaron de verdad."""

        nombres_antes = [self.primera.image.name, self.segunda.image.name]

        formset = self.build_formset()
        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())
        guardadas = formset.save()

        self.assertEqual(
            guardadas, [],
            "se reescribieron fotos que nadie tocó: {}".format([i.image.name for i in guardadas]),
        )

        self.primera.refresh_from_db()
        self.segunda.refresh_from_db()
        self.assertEqual([self.primera.image.name, self.segunda.image.name], nombres_antes)

    def test_guardar_con_recorte_ya_puesto_tampoco_las_reescribe(self):
        """El recorte automático se aplica al subir, así que las fotos ya vienen con uno."""

        for imagen in (self.primera, self.segunda):
            imagen.set_crop((0.0, 0.4166666666666667, 1.0, 0.5625))
            imagen.save()

        formset = self.build_formset()
        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())

        self.assertEqual(formset.save(), [], "el recorte guardado hizo que se reescribieran las fotos")

    def test_una_foto_que_falta_en_el_disco_no_rompe_la_edicion(self):
        """clean_image abría la foto ya guardada para ver si se podía decodificar: si el
        archivo no estaba en el disco, FileNotFoundError y editar ese animal (aunque fuera
        solo para cambiarle la edad) daba 500."""

        import os
        os.remove(self.primera.image.path)

        formset = self.build_formset()

        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())
        self.assertEqual(formset.save(), [])

    def test_el_recorte_sobrevive_a_guardar_sin_tocarlo(self):

        crop = (0.0, 0.25, 1.0, 0.5625)
        self.primera.set_crop(crop)
        self.primera.save()

        formset = self.build_formset()
        formset.is_valid()
        formset.save()

        self.primera.refresh_from_db()
        self.assertEqual(self.primera.get_crop(), crop, "se perdió el recorte al guardar")


class RecorteEnLaPantallaDeToolsTest(TestCase):
    """La galería de /tools/generarimagen/ devuelve el recorte guardado en el POST."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.animal = make_animal(nombre="Willy", edad="2 años", cargado_por=make_user())
        self.imagen = make_animal_image(animal=self.animal)
        self.imagen.set_crop((0.0, 0.25, 1.0, 0.5625))
        self.imagen.save()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def render(self):

        from django.template.loader import render_to_string

        return render_to_string("tools/makeimages.html", {
            "animal": self.animal, "fonts": [150, 125, 100, 75, 50],
        })

    def test_los_decimales_van_con_punto(self):
        """Con el locale es-ar Django escribía "0,25" y el server no lo podía leer:
        el recorte se borraba solo en cada regeneración."""

        html = self.render()

        self.assertIn('name="crop_y_{}" value="0.25"'.format(self.imagen.id), html)
        self.assertNotIn('value="0,25"', html)

    def test_el_recorte_renderizado_vuelve_a_leerse(self):
        """Ida y vuelta completa: lo que sale en el HTML tiene que poder volver a entrar."""

        import re

        from catus.utils import parse_crop

        html = self.render()
        post = {}
        for campo in ("x", "y", "w", "h"):
            nombre = "crop_{}_{}".format(campo, self.imagen.id)
            post[nombre] = re.search(r'name="{}" value="([^"]*)"'.format(nombre), html).group(1)

        self.assertEqual(
            parse_crop(post, "_{}".format(self.imagen.id)),
            self.imagen.get_crop(),
            "el recorte no sobrevivió la vuelta por el HTML",
        )

    def test_sin_recorte_el_campo_va_vacio(self):

        self.imagen.set_crop(None)
        self.imagen.save()

        html = self.render()

        self.assertIn('name="crop_x_{}" value=""'.format(self.imagen.id), html)


class PosicionesParaLaVistaPreviaTest(TestCase):
    """El selector de recorte de la edición muestra el nombre y la edad donde los va a
    dibujar el server.

    generar_imagen_para_instagram arma el posteo con las posiciones que la foto tiene
    guardadas (las elige el equipo en /tools/generarimagen/, nombre y edad por separado)
    y, si no tiene, con las automáticas. El JS del template las lee de cada fila del
    formset: si no estuvieran, la vista previa mostraba arriba la edad de una foto que
    el posteo iba a llevar con la edad abajo.
    """

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.user = make_user()
        self.animal = make_animal(nombre="Willy", edad="2 años", sexo="M", cargado_por=self.user)
        self.compuesta = make_animal_image(
            animal=self.animal,
            image_posicion_nombre="Izquierda (abajo)",
            image_posicion_edad_sexo="Izquierda (arriba)",
        )
        self.sin_componer = make_animal_image(animal=self.animal)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def pagina(self):

        self.client.force_login(self.user)
        response = self.client.get("/animales/{}/".format(self.animal.id))
        self.assertEqual(response.status_code, 200)

        return response.content.decode()

    def test_cada_foto_lleva_las_posiciones_que_tiene_guardadas(self):

        html = self.pagina()

        self.assertIn(
            'data-posicion-nombre="Izquierda (abajo)" data-posicion-edad-sexo="Izquierda (arriba)"', html,
            "la foto compuesta por el equipo no le pasa sus posiciones al selector",
        )

    def test_una_foto_sin_posiciones_las_lleva_vacias(self):
        """Vacío y no "None": el JS toma cualquier texto como posición, y "None" no es
        ninguna de las que dibuja el server."""

        html = self.pagina()

        self.assertIn('data-posicion-nombre="" data-posicion-edad-sexo=""', html)
        self.assertNotIn('data-posicion-nombre="None"', html)

    def test_sin_posiciones_cae_a_la_misma_automatica_que_el_server(self):
        """El JS tiene escrita la posición automática para las fotos nuevas, una sola para
        las dos: si el server cambia la suya, la vista previa tiene que cambiar con él."""

        from catus.services.images import ImageService

        self.assertEqual(ImageService.POSICION_NOMBRE_AUTOMATICA, ImageService.POSICION_EDAD_SEXO_AUTOMATICA)
        self.assertIn(
            "|| '{}'".format(ImageService.POSICION_NOMBRE_AUTOMATICA), self.pagina(),
            "la posición automática del template ya no es la de ImageService",
        )
