from catus.utils import clean_html
import uuid
import zipfile
from django.http import HttpResponse
from catus.models import Animal, CatusUser
from catus.services.facebook import FacebookApiService
from catus.services.images import ImageService
from django.conf import settings
from .base import BaseView
from django.core.files import File
from django.core.files.base import ContentFile
from datetime import datetime, timedelta
from catus.services.mail import MailService
from catus.utils import rreplace
from django.db.models import Q


class GenerarImagenView(BaseView):

    url = r"^tools/generarimagen/(?P<animal_id>.+)/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = Animal.objects.get(id=kwargs["animal_id"])
        ig_text = self.render("tools/generartexto.html", {"animal": animal})

        fonts = [150, 125, 100, 75, 50]

        return self.render_to_response({"animal": animal, "ig_text": ig_text, "fonts": fonts, "settings": settings})


class AnimalesPendientesView(BaseView):

    url = r"^tools/animalespendientes/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        # Animales que no han sido aprobados O que no tienen imágenes listas para Instagram
        animals = Animal.objects.filter(
            Q(aprobado=False) | Q(instagram_listo_para_publicar=False)
        ).select_related("cargado_por").prefetch_related("animalimage_set").order_by("-created_at")

        return self.render_to_response({"animals": animals})


class MakeImagesView(BaseView):

    url = r"^tools/makeimages/$"

    def post(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        fonts = [150, 125, 100, 75, 50]
        animal = Animal.objects.get(id=self.request.POST["animal_id"])

        for imagen in animal.get_images():

            centered = True
            if self.request.POST.get("centrado_{}".format(imagen.id)) == "no":
                centered = False

            layout = True
            if self.request.POST.get("layout_{}".format(imagen.id)) == "no":
                layout = False

            try:
                nombre_font_size = int(self.request.POST.get("nombre_font_size_{}".format(imagen.id), 150))
            except:
                nombre_font_size = 150

            posicion_edad_sexo = self.request.POST.get("posicion_edad_sexo_{}".format(imagen.id), "Izquierda")
            posicion_nombre = self.request.POST.get("posicion_nombre_{}".format(imagen.id), "Izquierda")

            if layout:
                image = ImageService().generate_logo_image(
                    animal,
                    imagen.image,
                    centered=centered,
                    nombre_font_size=nombre_font_size,
                    posicion_edad_sexo=posicion_edad_sexo,
                    posicion_nombre=posicion_nombre
                )
            else:
                image = imagen.image

            content_file = ContentFile(image.read())
            file = File(content_file)

            random_name = f'{uuid.uuid4()}.jpeg'

            if not self.request.POST.get("is_load") == "1":
                imagen.image_for_instagram.save(random_name, file, save=True)
                imagen.image_layout = layout
                imagen.image_centered = centered
                imagen.image_font_size = nombre_font_size
                imagen.image_posicion_edad_sexo = posicion_edad_sexo
                imagen.image_posicion_nombre = posicion_nombre

            elif not imagen.image_for_instagram:
                imagen.image_for_instagram.save(random_name, file, save=True)

            imagen.save()

        return self.render_to_response({"animal": animal, "fonts": fonts})


class MakeSingleImageView(BaseView):

    url = r"^tools/makesingleimage/$"

    def post(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        from catus.models import AnimalImage

        fonts = [150, 125, 100, 75, 50]
        image_id = self.request.POST.get("image_id")

        try:
            imagen = AnimalImage.objects.get(id=image_id)
        except AnimalImage.DoesNotExist:
            return self.response("Imagen no encontrada.")

        animal = imagen.animal

        # Obtener configuración de la imagen específica
        centered = True
        if self.request.POST.get("centrado_{}".format(imagen.id)) == "no":
            centered = False

        layout = True
        if self.request.POST.get("layout_{}".format(imagen.id)) == "no":
            layout = False

        try:
            nombre_font_size = int(self.request.POST.get("nombre_font_size_{}".format(imagen.id), 150))
        except:
            nombre_font_size = 150

        posicion_edad_sexo = self.request.POST.get("posicion_edad_sexo_{}".format(imagen.id), "Izquierda (abajo)")
        posicion_nombre = self.request.POST.get("posicion_nombre_{}".format(imagen.id), "Izquierda (abajo)")

        # Procesar la imagen
        if layout:
            image = ImageService().generate_logo_image(
                animal,
                imagen.image,
                centered=centered,
                nombre_font_size=nombre_font_size,
                posicion_edad_sexo=posicion_edad_sexo,
                posicion_nombre=posicion_nombre
            )
        else:
            image = imagen.image

        content_file = ContentFile(image.read())
        file = File(content_file)

        random_name = f'{uuid.uuid4()}.jpeg'

        # Guardar la imagen procesada
        imagen.image_for_instagram.save(random_name, file, save=True)
        imagen.image_layout = layout
        imagen.image_centered = centered
        imagen.image_font_size = nombre_font_size
        imagen.image_posicion_edad_sexo = posicion_edad_sexo
        imagen.image_posicion_nombre = posicion_nombre
        imagen.save()

                # Renderizar solo esta imagen específica
        context = {
            "image": imagen,
            "animal": animal,
            "fonts": fonts
        }

        return HttpResponse(self.render("tools/single_image_result.html", context))


class DownloadImagesView(BaseView):

    url = r"^tools/downloadimages/(?P<animal_id>.+)/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = Animal.objects.get(id=kwargs["animal_id"])

        response = HttpResponse(content_type='application/octet-stream')

        with zipfile.ZipFile(response, 'w') as zip_file:
            for i, imagen in enumerate(animal.get_images()):
                zip_file.writestr("{}_{}.jpeg".format(animal.nombre, i+1), imagen.image_for_instagram.read())

        response['Content-Disposition'] = 'attachment; filename={}.zip'.format(animal.nombre)
        return response


class PublishView(BaseView):

    url = r"^tools/publish/$"

    def post(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = Animal.objects.get(id=self.request.POST.get("animal_id"))
        ig_text = self.render("tools/generartexto.txt", {"animal": animal})
        ig_text = clean_html(ig_text)

        return self.response(FacebookApiService.publish(animal, ig_text))


class SaveFormView(BaseView):

    url = r"^tools/saveform/$"

    def post(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = Animal.objects.get(id=self.request.POST.get("animal_id"))
        animal.instagram_listo_para_publicar = self.request.POST.get("instagram_listo_para_publicar") is not None
        animal.save()

        return self.response("ok")


class PreguntarAdopcion(BaseView):

    url = r"^tools/preguntaradopcion/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        users = []
        i = 0
        for user in CatusUser.objects.filter(no_preguntar_adoptado=False):
            days_ago = datetime.now() - timedelta(days=30)
            animals = Animal.objects.filter(cargado_por=user, estado="D", aprobado=True, fecha_ingreso__lte=days_ago)

            if not animals:
                continue

            animals_names = ", ".join([animal.nombre for animal in animals])
            animals_names = rreplace(animals_names, ", ", " y ", 1)

            users.append((i, {
                "user": user,
                "animals": animals,
                "animals_names": animals_names,
                "already_sent_email": all(animal.mail_preguntar_adopcion_enviado for animal in animals),
                "is_plural": len(animals) > 1
            }))

            i += 1

        return self.render_to_response({"users": users })


class SendPreguntarEmailView(BaseView):

    template_name = "tools/_already_sent_email.html"

    def post(self, *args, **kwargs):

        user = CatusUser.objects.get(id=self.request.POST.get("user_id"))
        content = self.request.POST.get("content")
        MailService().send_mail_pregunta(user, content)

        return self.render_to_response({})