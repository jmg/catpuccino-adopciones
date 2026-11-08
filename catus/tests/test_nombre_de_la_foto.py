"""El nombre del archivo de una foto no puede impedir cargar un animal.

Lo motivó un caso de producción (2026-11-07): un rescatista subió una foto con el archivo
llamado como la descripción del animal, que tenía un punto al terminar la primera oración.
Django guarda la foto con el nombre que manda el navegador y, si no entra en los 100
caracteres de AnimalImage.image, lo acorta. Pero el Django de ahora toma como extensión
todo lo que sigue al PRIMER punto (para respetar los .tar.gz) y acorta sólo lo de antes:
esa "extensión" no entraba ni dejando vacío lo de antes. SuspiciousFileOperation adentro
de image_form_set.save(), un 400 para el rescatista, y el animal guardado sin fotos,
porque EditView lo guarda antes que las fotos. Lo volvió a intentar y le pasó lo mismo.
Con Django 2.0, hasta el 2026-11-03, la extensión era sólo la última y esto andaba.

Pasa cuando desde el primer punto hay 84 caracteres o más y el nombre no entra en la
columna. Y el nombre que manda el navegador no le sirve a nadie: optimize() vuelve a
guardar cada foto subida como <uuid>.jpeg.
"""
import shutil
import tempfile
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings
from PIL import Image

from catus.models import Animal, AnimalImage
from catus.tests.factories import make_animal, make_animal_image, make_user, uploaded_photo
from catus.views.animal import EditView

#inventado, con la forma del caso real: la descripción del animal como nombre del archivo,
#con un punto temprano. Desde ese punto hasta el final pasa de largo los 84 caracteres
NOMBRE_DE_LA_FOTO = (
    "Pelusa busca familia. Es una gata muy mimosa, juguetona y tranquila, "
    "se lleva bien con otros gatos y con perros chicos.jpg"
)


class NombreDeLaFotoTest(TestCase):

    def setUp(self):
        #las altas guardan fotos de verdad: que caigan en un directorio descartable
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(self.override.disable)

        self.factory = RequestFactory()
        self.rescatista = make_user(email="rescatista@catpuccino.test")

    def guardar(self, url, datos, **kwargs):
        """El POST de la pantalla del animal, por EditView como lo manda el navegador."""

        request = self.factory.post(url, datos)
        request.user = self.rescatista

        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()

        #se mockea sólo lo que sale a la red: el mail del alta
        with mock.patch("catus.views.animal.MailService"):
            return EditView.as_view(template_name="animal/edit.html")(request, **kwargs)

    def datos_del_animal(self, filas, ya_guardadas=0):

        return {
            "tipo": "G", "estado": "D", "nombre": "Pelusa", "edad": "1 año", "sexo": "H",
            "zona": "CABA", "datos": "<p>Muy mimosa.</p>",
            "animalimage_set-TOTAL_FORMS": str(filas),
            "animalimage_set-INITIAL_FORMS": str(ya_guardadas),
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
        }

    def foto_nueva(self, indice):

        prefijo = "animalimage_set-{}-".format(indice)

        return {
            prefijo + "id": "", prefijo + "animal": "",
            prefijo + "crop_x": "", prefijo + "crop_y": "",
            prefijo + "crop_w": "", prefijo + "crop_h": "",
            prefijo + "image": uploaded_photo(name=NOMBRE_DE_LA_FOTO),
        }

    def animal_cargado(self):

        return make_animal(
            nombre="Pelusa", tipo="G", sexo="H", edad="1 año", zona="CABA",
            cargado_por=self.rescatista, aprobado=False,
        )

    def test_se_carga_el_animal_con_su_foto(self):
        """El caso de producción: el alta daba 400 y el animal quedaba sin fotos."""

        datos = self.datos_del_animal(filas=1)
        datos.update(self.foto_nueva(0))

        response = self.guardar("/animales/", datos)

        self.assertEqual(response.status_code, 302, "no se completó el alta")

        animal = Animal.objects.get(cargado_por=self.rescatista)
        imagenes = list(AnimalImage.objects.filter(animal=animal))

        self.assertEqual(len(imagenes), 1, "el animal quedó cargado sin la foto que subieron")
        with Image.open(imagenes[0].image.path) as imagen:
            imagen.verify()

    def test_se_le_puede_subir_la_foto_al_animal_que_quedo_sin_fotos(self):
        """Lo que haría el rescatista después del alta a medias: entrar al animal que quedó
        guardado sin fotos y volver a subirla. Es el mismo formset y le pasaba lo mismo: otro
        400, con los cambios del texto guardados y la foto no."""

        animal = self.animal_cargado()

        datos = self.datos_del_animal(filas=1)
        datos.update(self.foto_nueva(0))

        response = self.guardar("/animales/{}/".format(animal.id), datos, animal_id=str(animal.id))

        self.assertEqual(response.status_code, 302, "no se guardó la edición")
        self.assertEqual(AnimalImage.objects.filter(animal=animal).count(), 1, "no se guardó la foto")

    def test_las_fotos_ya_guardadas_conservan_su_nombre(self):
        """El nombre se cambia sólo en la foto que se está subiendo. La que ya estaba llega
        a clean_image como la misma FieldFile del modelo: cambiárselo ahí lo cambia en la
        base sin mover el archivo, y al rescatista que le corrige el recorte a una foto ya
        cargada se le rompe la foto."""

        animal = self.animal_cargado()
        foto = make_animal_image(animal=animal)
        nombre = foto.image.name

        datos = self.datos_del_animal(filas=1, ya_guardadas=1)
        datos.update({
            "animalimage_set-0-id": str(foto.id),
            "animalimage_set-0-animal": str(animal.id),
            "animalimage_set-0-crop_x": "0.1",
            "animalimage_set-0-crop_y": "0.0",
            "animalimage_set-0-crop_w": "0.5",
            "animalimage_set-0-crop_h": "0.5",
        })

        response = self.guardar("/animales/{}/".format(animal.id), datos, animal_id=str(animal.id))

        self.assertEqual(response.status_code, 302, "no se guardó la edición")

        foto.refresh_from_db()
        self.assertEqual(foto.crop_x, 0.1, "no se guardó el recorte: el test no probó nada")
        self.assertEqual(foto.image.name, nombre, "se le cambió el nombre a la foto ya guardada")
        with Image.open(foto.image.path) as imagen:
            imagen.verify()
