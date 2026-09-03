from catus.utils import clean_html, has_crop_fields, parse_crop
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
from django.db.models import Case, IntegerField, Q, Value, When


class ToolsIndexView(BaseView):

    url = r"^tools/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        return self.render_to_response({})


class GenerarImagenView(BaseView):

    url = r"^tools/generarimagen/(?P<animal_id>.+)/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = Animal.objects.filter(id=kwargs["animal_id"]).first()
        if animal is None:
            return self.response("No se encontró el animal.")

        ig_text = self.render("tools/generartexto.html", {"animal": animal})

        fonts = [150, 125, 100, 75, 50]

        return self.render_to_response({"animal": animal, "ig_text": ig_text, "fonts": fonts, "settings": settings})


class AnimalesPendientesView(BaseView):

    url = r"^tools/animalespendientes/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        # Animales que no han sido aprobados O que no tienen imágenes listas para Instagram
        # Y que no estén adoptados
        animals = Animal.objects.filter(
            (Q(aprobado=False) | Q(instagram_listo_para_publicar=False)) & ~Q(estado="A")
        ).select_related("cargado_por").prefetch_related("animalimage_set")

        #las que la revisión automática marcó van primero: son las que hay que mirar
        animals = animals.annotate(
            _para_revisar=Case(
                When(revision_ia_estado=Animal.REVISION_REVISAR, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("_para_revisar", "-created_at")

        return self.render_to_response({
            "animals": animals,
            "para_revisar": sum(1 for a in animals if a.necesita_revision_humana()),
        })


class AnimalesListosParaPublicarView(BaseView):

    url = r"^tools/animaleslistosparapublicar/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        # Animales que están listos para publicar pero aún no han sido publicados
        # Y que no estén adoptados
        animals = Animal.objects.filter(
            instagram_listo_para_publicar=True,
            instagram_publicado=False,
            aprobado=True,
            estado__in=["D", "R"]  # Solo disponibles o reservados, no adoptados
        ).select_related("cargado_por").prefetch_related("animalimage_set").order_by("-created_at")

        return self.render_to_response({"animals": animals})


class CropMixin():

    def get_crop(self, imagen, suffix):
        """Recorte a usar para esta imagen.

        Si el form trae los campos de recorte manda el form (vacio = volver al automatico).
        Si no los trae (la carga inicial de la galeria) vale el que ya estaba guardado.
        """

        if has_crop_fields(self.request.POST, suffix):
            return parse_crop(self.request.POST, suffix)

        return imagen.get_crop()


class MakeImagesView(CropMixin, BaseView):

    url = r"^tools/makeimages/$"

    def post(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        fonts = [150, 125, 100, 75, 50]
        animal = Animal.objects.filter(id=self.request.POST.get("animal_id")).first()
        if animal is None:
            return self.response("No se encontró el animal.")

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

            crop = self.get_crop(imagen, "_{}".format(imagen.id))

            if layout:
                image = ImageService().generate_logo_image(
                    animal,
                    imagen.image,
                    centered=centered,
                    nombre_font_size=nombre_font_size,
                    posicion_edad_sexo=posicion_edad_sexo,
                    posicion_nombre=posicion_nombre,
                    crop=crop
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
                imagen.set_crop(crop)

            elif not imagen.image_for_instagram:
                imagen.image_for_instagram.save(random_name, file, save=True)

            imagen.save()

        return self.render_to_response({"animal": animal, "fonts": fonts})


class MakeSingleImageView(CropMixin, BaseView):

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

        crop = self.get_crop(imagen, "_{}".format(imagen.id))

        # Procesar la imagen
        if layout:
            image = ImageService().generate_logo_image(
                animal,
                imagen.image,
                centered=centered,
                nombre_font_size=nombre_font_size,
                posicion_edad_sexo=posicion_edad_sexo,
                posicion_nombre=posicion_nombre,
                crop=crop
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
        imagen.set_crop(crop)
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

        animal = Animal.objects.filter(id=kwargs["animal_id"]).first()
        if animal is None:
            return self.response("No se encontró el animal.")

        response = HttpResponse(content_type='application/octet-stream')

        with zipfile.ZipFile(response, 'w') as zip_file:
            for i, imagen in enumerate(animal.get_images()):

                #las fotos que todavia no se procesaron no tienen imagen de instagram
                if not imagen.image_for_instagram:
                    continue

                zip_file.writestr("{}_{}.jpeg".format(animal.nombre, i+1), imagen.image_for_instagram.read())

        response['Content-Disposition'] = 'attachment; filename={}.zip'.format(animal.nombre)
        return response


class PublishView(BaseView):

    url = r"^tools/publish/$"

    def post(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = Animal.objects.filter(id=self.request.POST.get("animal_id")).first()
        if animal is None:
            return self.response("No se encontró el animal.")

        ig_text = self.render("tools/generartexto.txt", {"animal": animal})
        ig_text = clean_html(ig_text)

        return self.response(FacebookApiService.publish(animal, ig_text))


class SaveFormView(BaseView):

    url = r"^tools/saveform/$"

    def post(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = Animal.objects.filter(id=self.request.POST.get("animal_id")).first()
        if animal is None:
            return self.response("No se encontró el animal.")

        #el botón manda "" al desmarcar (no omite la clave), así que preguntar por
        #"is not None" lo dejaba siempre en True: desmarcar no tenía ningún efecto y
        #el cron publicaba igual el animal
        valor = (self.request.POST.get("instagram_listo_para_publicar") or "").strip().lower()
        animal.instagram_listo_para_publicar = valor in ("on", "true", "1", "si")
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

        #manda un mail con contenido libre al usuario que se le indique: sin este
        #chequeo cualquiera podia mandar cualquier cosa desde el dominio del sitio
        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        user = CatusUser.objects.filter(id=self.request.POST.get("user_id")).first()
        if user is None:
            return self.response("No se encontró el usuario.")

        content = self.request.POST.get("content")
        MailService().send_mail_pregunta(user, content)

        return self.render_to_response({})