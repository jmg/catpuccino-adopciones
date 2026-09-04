"""Tests de los mensajes de error al cargar un animal.

Es el momento en el que un rescatista se traba y abandona la carga, así que el
cartel tiene que decir qué corregir.
"""
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import inlineformset_factory
from django.test import RequestFactory, TestCase, override_settings

from catus.forms import AnimalForm, AnimalImageForm, RequiredImageInlineFormset
from catus.models import Animal, AnimalImage
from catus.services.mail import MailService
from catus.tests.factories import make_user, photo_bytes, uploaded_photo
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


class FotoRotaConFotoDeInstagramTest(TestCase):
    """Subir un archivo que no es una imagen junto con una foto de Instagram.

    Guardar se habilita con "el formset validó O hay alguna URL de Instagram", así
    que alcanzaba una URL para entrar al bloque con el formset inválido. La primera
    versión llamaba image_form_set.save() sin preguntar y Django tiraba ValueError
    ("The AnimalImage could not be created because the data didn't validate") con el
    animal ya guardado una línea antes: el rescatista veía un 500.

    Guardar sólo si el formset validaba sacó el 500 y dejó algo peor de ver: el animal
    se guardaba igual, las fotos que el rescatista subió se descartaban sin ningún
    aviso, y la pantalla le decía que había salido todo bien. Una foto que no se pudo
    leer es un error y hay que mostrarlo.
    """

    URL_DE_INSTAGRAM = "https://scontent.cdninstagram.com/v/foto.jpg"

    def setUp(self):
        #las fotos de Instagram se bajan a un temporal adentro de MEDIA_ROOT/gallery
        self.media = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.media, "gallery"))
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

        self.factory = RequestFactory()
        self.user = make_user()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def guardar(self, foto=None):
        """POST de alta con una foto de Instagram y, si viene, una foto subida."""

        campos = {
            "animalimage_set-0-id": "",
            "animalimage_set-0-animal": "",
            "animalimage_set-0-crop_x": "",
            "animalimage_set-0-crop_y": "",
            "animalimage_set-0-crop_w": "",
            "animalimage_set-0-crop_h": "",
        }

        if foto is None:
            #el alta hecha desde un post de Instagram: el formset viene vacío
            campos = {}

        datos = formset_data(total=0 if foto is None else 1, **campos)

        if foto is not None:
            datos["animalimage_set-0-image"] = foto

        datos.update({
            "nombre": "Willy", "tipo": "G", "estado": "D", "sexo": "M", "edad": "2 años",
            "instagram_image": self.URL_DE_INSTAGRAM,
        })

        request = self.factory.post("/animales/", datos)
        request.user = self.user
        SessionMiddleware().process_request(request)
        request.session.save()

        descarga = mock.MagicMock()
        descarga.read.return_value = photo_bytes().getvalue()

        #el template_name lo pone el URLconf, que necesita el proyecto entero levantado:
        #acá alcanza con que la respuesta se pueda armar, no se renderiza nada
        #no salimos a la red: se mockea solo el borde (la descarga y el mail)
        with mock.patch.object(EditView, "template_name", "animal/edit.html"), \
                mock.patch("catus.views.animal.urlopen", return_value=descarga) as urlopen, \
                mock.patch.object(MailService, "send_new_animal_mail"):
            response = EditView.as_view()(request)

        return response, urlopen

    def foto_rota(self):

        return SimpleUploadedFile("foto.jpg", b"esto no es una imagen", content_type="image/jpeg")

    def test_la_foto_rota_no_tira_un_500(self):
        """Vuelve al formulario, que es donde se muestran los errores.

        No alcanza con "no explotó": un 302 acá es el guardado que se comió las fotos.
        """

        response, _ = self.guardar(foto=self.foto_rota())

        self.assertEqual(response.status_code, 200)

    def test_avisa_de_la_foto_que_no_se_pudo_leer(self):
        """Antes se guardaba en silencio: la persona se enteraba de que le faltaba una
        foto cuando entraba a ver la publicación, si es que entraba."""

        response, _ = self.guardar(foto=self.foto_rota())

        errores = " ".join(response.context_data["errors"])

        self.assertIn("Fotos", errores, "no se avisa de la foto que se descartó: {}".format(errores))
        self.assertFalse(response.context_data["success"])

    def test_no_se_guarda_nada_a_medias(self):
        """El animal se guarda antes que las fotos y no hay ATOMIC_REQUESTS."""

        _, urlopen = self.guardar(foto=self.foto_rota())

        self.assertFalse(Animal.objects.exists(), "quedó el animal guardado sin las fotos que subieron")
        self.assertFalse(AnimalImage.objects.exists())
        self.assertFalse(urlopen.called, "se bajó la foto de Instagram para un animal que no se guardó")

    def test_una_foto_buena_con_una_de_instagram_se_guarda_igual(self):
        """El arreglo no puede frenar el caso que sí anda."""

        response, _ = self.guardar(foto=uploaded_photo())

        self.assertEqual(response.status_code, 302, "no se completó el guardado")
        self.assertEqual(AnimalImage.objects.filter(animal__nombre="Willy").count(), 2)

    def test_solo_con_fotos_de_instagram_se_sigue_pudiendo_cargar(self):
        """El alta desde un post: el formset viene vacío y por eso no valida."""

        from PIL import Image

        response, urlopen = self.guardar()

        self.assertEqual(response.status_code, 302, "no se completó el guardado")
        self.assertTrue(urlopen.called, "no se buscó la foto de Instagram")

        imagenes = list(AnimalImage.objects.filter(animal__nombre="Willy"))

        self.assertEqual(len(imagenes), 1)
        Image.open(imagenes[0].image).verify()
