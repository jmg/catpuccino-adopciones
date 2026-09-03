import logging
from django.conf import settings
from catus.services.images import ImageService
from catus.services.mail import MailService
from catus.views.base import BaseView, SuperuserRequiredMixin, puede_editar_animal
from catus.utils import es_url_de_imagen_publica
from catus.services.gpt import GPTService
from django.forms import inlineformset_factory

from catus.models import Animal, AnimalImage, CatusUser
from catus.forms import AnimalImageForm, CatusUserForm, RequiredImageInlineFormset
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.core.files import File
from urllib.request import urlopen
from tempfile import NamedTemporaryFile
from django.utils import timezone
import os

from catus.forms import AnimalForm

logger = logging.getLogger(__name__)


class EditView(LoginRequiredMixin, BaseView):

    url = [r"^animales/(?P<animal_id>(\d+))/$", r"^animales/$"]

    def set_suggested_crop(self, animal_image):
        """Si nadie eligio el recorte, proponemos uno para que el animal no salga cortado.

        Es solo un punto de partida: se puede corregir despues desde el selector.
        """

        if animal_image.get_crop():
            return

        crop = ImageService().suggest_crop(animal_image.image)
        if crop:
            animal_image.set_crop(crop)
            animal_image.save()

    def get_error_messages(self, animal_form, image_form_set):
        """Arma la lista de errores que ve el rescatista cuando no se puede guardar.

        Antes se mostraba lo que devolviera Django: si faltaba una foto, el aviso
        "Al menos una foto del animal es requerida" vive en non_form_errors() y no
        se leía nunca, así que la persona veía un cartel de error vacío y no tenía
        forma de saber qué corregir.
        """

        mensajes = []

        for campo, errores in animal_form.errors.items():
            etiqueta = animal_form.fields[campo].label if campo in animal_form.fields else None
            for error in errores:
                mensajes.append("{}: {}".format(etiqueta, error) if etiqueta else error)

        mensajes.extend(image_form_set.non_form_errors())

        for form_errores in image_form_set.errors:
            #normalmente es un dict por foto, pero no confiamos: un solo error raro
            #no puede dejar a la persona sin saber que corregir
            if not hasattr(form_errores, "values"):
                mensajes.append("Fotos: {}".format(form_errores))
                continue

            for errores in form_errores.values():
                mensajes.extend("Fotos: {}".format(error) for error in errores)

        if not mensajes:
            mensajes.append("No pudimos guardar los cambios. Revisá los datos e intentá de nuevo.")

        return mensajes

    def req(self, is_post=False, **kwargs):

        ImageFormSet = inlineformset_factory(Animal, AnimalImage, extra=0, can_delete=True, form=AnimalImageForm, formset=RequiredImageInlineFormset)
        context = {}

        if kwargs.get("animal_id"):
            animal = get_object_or_404(Animal, id=kwargs.get("animal_id"))

            #sin esto cualquiera logueado editaba el animal de otra persona cambiando la URL
            if not puede_editar_animal(self.request.user, animal):
                raise PermissionDenied("Este animal lo cargó otra persona.")

            context["post_url"] = "/animales/{}/".format(kwargs.get("animal_id"))
        else:
            animal = None
            context["post_url"] = "/animales/"

        context["animal"] = animal
        context["is_post"] = is_post

        if is_post:

            animal_form = AnimalForm(self.request.POST, instance=animal)
            image_form_set = ImageFormSet(self.request.POST, self.request.FILES, instance=animal)
            instagram_images = self.request.POST.getlist("instagram_image")

            if animal_form.is_valid() and (image_form_set.is_valid() or len(instagram_images) > 0):

                is_new_animal = animal_form.instance.id is None

                animal = animal_form.save(commit=False)

                #el animal sigue siendo de quien lo cargó: si alguien del equipo entra
                #a corregirle un dato no puede quedárselo y sacarlo del listado del
                #rescatista (ni de los mails de sus formularios de pre-adopción)
                if animal.cargado_por_id is None:
                    animal.cargado_por = self.request.user
                if self.request.POST.get("ig_url_for_chatgpt"):
                    animal.ig_url_for_chatgpt = self.request.POST.get("ig_url_for_chatgpt")
                if self.request.POST.get("chatgpt_response"):
                    animal.chatgpt_response = self.request.POST.get("chatgpt_response")

                animal.save()

                image_form_set.instance = animal
                image_form_set.save()

                #optimize() reescribe el archivo con otro nombre, así que solo corre
                #sobre las fotos que realmente se subieron: si no, editarle la edad a un
                #animal recomprimía y renombraba todas sus fotos, y las URLs que ya
                #habían salido por mail quedaban rotas
                for form in image_form_set.forms:

                    if form.cleaned_data.get("DELETE") or "image" not in form.changed_data:
                        continue

                    animal_image = form.instance
                    if animal_image.pk is None:
                        continue

                    ImageService().optimize(animal_image.image, max_width=1200)
                    self.set_suggested_crop(animal_image)

                for image_url in instagram_images:

                    #urlopen abre lo que le den, incluido file:// y direcciones de la
                    #red interna: sin este chequeo se podía hacer que el server leyera
                    #su propio archivo de secretos y lo guardara como "foto" del animal
                    if not es_url_de_imagen_publica(image_url):
                        logger.warning("Se descartó una foto con URL no permitida: %s", image_url)
                        continue

                    img_temp = NamedTemporaryFile(delete=True, dir=os.path.join(settings.MEDIA_ROOT, "gallery"))
                    img_temp.write(urlopen(image_url, timeout=20).read())
                    img_temp.flush()

                    animal_image = AnimalImage.objects.create(animal=animal)
                    animal_image.image.save(img_temp.name, File(img_temp))
                    animal_image.save()
                    ImageService().optimize(animal_image.image, max_width=1200)
                    self.set_suggested_crop(animal_image)

                    os.remove(img_temp.name)

                self.request.session["animal_save_success"] = True
                if is_new_animal:
                    if animal.cargado_por.automatic_approve:
                        animal.aprobado = True
                        animal.save()
                        MailService().send_new_animal_mail(animal)
                        self.request.session["is_new_animal_approved"] = True
                    else:
                        MailService().send_new_animal_mail(animal)
                        self.request.session["is_new_animal"] = True

                return self.redirect(settings.LOGIN_REDIRECT_URL)
            else:
                context["success"] = False
                context["errors"] = self.get_error_messages(animal_form, image_form_set)

        else:
            animal_form = AnimalForm(instance=animal)
            image_form_set = ImageFormSet(instance=animal)

            if animal:
                animal_form.fields["estado"].initial = animal.get_estado()

        context["images_form"] = image_form_set
        context["animal_form"] = animal_form

        return self.render_to_response(context)

    def get(self, *args, **kwargs):

        return self.req(**kwargs)

    def post(self, *args, **kwargs):

        return self.req(is_post=True, **kwargs)


class AprobarView(SuperuserRequiredMixin, BaseView):

    def get(self, *a, **k):

        animal = Animal.objects.filter(id=self.request.GET.get("id")).first()
        if animal is None:
            return self.response("No se encontró el animal.")

        if not animal.aprobado:
            animal.aprobado = True
            MailService().send_mail_aprobacion(animal)
            animal.save()

            return self.response("{} aprobado!".format(animal.nombre))

        return self.response("{} ya habia sido aprobado".format(animal.nombre))


class ValidateNameView(LoginRequiredMixin, BaseView):

    def post(self, *a, **k):

        name = self.request.POST.get("name")
        if Animal.objects.filter(nombre=name, fecha_adopcion__isnull=True, estado="D").exists():
            return self.json_response({"valid": False})

        return self.json_response({"valid": True})


class PhotosView(BaseView):
    """La usa el formulario público de pre-adopción, así que solo muestra lo publicado."""

    def post(self, *a, **k):

        animal_id = self.request.POST.get("animal_id")
        if not animal_id:
            return self.json_response({"photos_count": 0, "html": "" })

        animal = Animal.objects.filter(id=animal_id, aprobado=True).first()
        if animal is None:
            return self.json_response({"photos_count": 0, "html": "" })

        html = self.render("animal/photos.html", {"animal": animal})

        return self.json_response({"photos_count": animal.animalimage_set.count(), "html": html })


class PullDataFromIg(LoginRequiredMixin, BaseView):

    def get(self, *a, **k):

        url = self.request.GET.get("url")

        #depende de Instagram y de la API de OpenAI: cuando algo de eso falla, el
        #rescatista tiene que poder seguir cargando el animal a mano
        try:
            data = GPTService().pull_data_from_ig(url)
        except ValueError as error:
            return self.json_response({"error": str(error)})
        except Exception:
            logger.exception("No se pudieron traer los datos de %s", url)
            return self.json_response({"error": "No pudimos leer ese post. Cargá los datos a mano."})

        return self.json_response(data)


class UpdateAnimal(LoginRequiredMixin, BaseView):

    response_status = "actualizados"

    def update(self, animal, post_data=None):

        pass

    def post(self, *a, **k):

        animal_id = self.request.POST.get("animal_id")
        if not animal_id:
            animal_ids = self.request.POST.getlist("animal_ids")
        else:
            animal_ids = [animal_id]

        animals = Animal.objects.filter(id__in=animal_ids)

        #cada quien maneja sus animales; el equipo maneja todos
        if not self.request.user.is_superuser:
            animals = animals.filter(cargado_por=self.request.user)

        animals = list(animals)

        for animal in animals:
            self.update(animal, post_data=self.request.POST)
            animal.save()

        if not animal_id:
            return self.response("Animales marcados como {}!".format(self.response_status))

        #con un id que no existe (o de otra persona) no hay animal que devolver
        if not animals:
            return self.json_response({"success": False, "error": "No se encontró el animal."})

        return self.json_response({"success": True, "nombre": animals[0].nombre })


class MarcarAdoptado(UpdateAnimal):

    response_status = "adoptados"

    def update(self, animal, post_data=None):

        animal.estado = "A"
        animal.fecha_adopcion = timezone.now()


class MarcarEnAdopcion(UpdateAnimal):

    response_status = "en adopción"

    def update(self, animal, post_data=None):

        animal.estado = "D"
        animal.fecha_adopcion = None


class MarcarExpirado(UpdateAnimal):

    response_status = "expirados"

    def update(self, animal, post_data=None):

        animal.estado = "E"


class ActualizarFechaIngreso(UpdateAnimal):

    response_status = "fecha ingreso"

    def update(self, animal, post_data=None):

        animal.fecha_ingreso = timezone.now()


class AddComment(SuperuserRequiredMixin, BaseView):

    template_name = "tools/_comment.html"

    def post(self, *args, **kwargs):

        user_id = self.request.POST.get("user_id")
        comment = self.request.POST.get("comment")

        user = CatusUser.objects.filter(id=user_id).first()
        if user is None:
            return self.response("No se encontró el usuario.")

        user.animales_comentario = comment
        user.save()

        return self.render_to_response({"user": {"user": user}})