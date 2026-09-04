import logging
from datetime import timedelta
from django.conf import settings
from catus.services.images import ImageService
from catus.services.instagram_auto import InstagramAutoService
from catus.services.mail import MailService
from catus.services.moderacion import ModeracionService
from catus.views.base import BaseView, SuperuserRequiredMixin, puede_editar_animal
from catus.utils import es_url_de_imagen_publica
from catus.services.gpt import GPTService
from django.forms import inlineformset_factory

from catus.models import Animal, AnimalImage, CatusUser, ChatGTPResponse
from catus.forms import AnimalImageForm, CatusUserForm, RequiredImageInlineFormset
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.core.files import File
from urllib.request import urlopen
from tempfile import NamedTemporaryFile
from django.utils import timezone
from django.utils.html import escape
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

    def get_instagram_images(self):
        """Las URLs de fotos de Instagram que el server puede ir a buscar.

        urlopen abre lo que le den, incluido file:// y direcciones de la red interna:
        sin este filtro se podía hacer que el server leyera su propio archivo de
        secretos y lo guardara como "foto" del animal. Se filtra acá y no dentro del
        bucle porque esta lista es la que habilita el guardado: con un campo vacío o
        de un host que no aceptamos se salteaba la validación de "al menos una foto".
        """

        urls = []

        for image_url in self.request.POST.getlist("instagram_image"):

            if not es_url_de_imagen_publica(image_url):
                logger.warning("Se descartó una foto con URL no permitida: %s", image_url)
                continue

            urls.append(image_url)

        return urls

    def hay_fotos_subidas(self, image_form_set):
        """¿Este POST trae alguna foto subida desde el equipo del rescatista?

        Se mira el archivo que llegó y no cleaned_data: cuando el formset no valida, sus
        forms pueden no tener cleaned_data y justo ahí es donde hace falta preguntar.
        """

        return any(
            image_form_set.files.get(form.add_prefix("image"))
            for form in image_form_set.forms
        )

    def cambio_alguna_foto(self, image_form_set):
        """¿Cambió alguna foto de verdad, o sólo su recorte para Instagram?

        La revisión automática mira el archivo de la foto y el texto: el recorte no lo ve.
        Mientras la condición era `any(f.has_changed())`, mover el selector de recorte
        contaba como cambio y gastaba una llamada paga al pedo; y si la IA contestaba 'R',
        encima le sacaba al animal el posteo automático por haberle corregido el encuadre.
        """

        recorte = set(AnimalImageForm.CROP_FIELDS)

        return any(set(form.changed_data) - recorte for form in image_form_set.forms)

    def invalidar_imagenes_de_instagram(self, animal, imagenes):
        """Borra la imagen compuesta de esas fotos, para que se rearme con lo que hay ahora.

        image_for_instagram lleva el nombre, la edad y el sexo quemados en el pixel, y
        generar_imagen_para_instagram se saltea la foto que ya la tiene: sin esto, el
        rescatista corregía la edad —o reemplazaba la foto— y el posteo salía igual, con
        los datos viejos. Borrarla no frena nada: preparar_publicaciones la vuelve a armar
        en la corrida siguiente, y publish ya sabe dejar afuera al que todavía no la tiene.

        Sólo mientras el posteo no salió. Después de publicado ese archivo es lo que se
        subió a Instagram: rearmarlo no cambia el post que ya está en la cuenta (el cron
        ni lo mira, preparar_publicaciones filtra instagram_publicado=False) y borrarlo
        sólo pierde el registro de lo que se publicó.
        """

        if animal.instagram_publicado:
            return

        for imagen in imagenes:
            if imagen.image_for_instagram:
                imagen.image_for_instagram.delete(save=True)

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
            instagram_images = self.get_instagram_images()

            #el formset se valida por separado y no adentro del or: con el or se
            #entraba al bloque con un formset inválido, image_form_set.save() tiraba
            #ValueError con el animal ya guardado, y el rescatista veía un 500 en vez
            #de los errores que tenía que corregir
            formset_ok = image_form_set.is_valid()

            #el formset inválido se puede saltear sólo si no traía ninguna foto: ese es el
            #caso legítimo, el alta hecha desde un post de Instagram, donde el formset
            #viene vacío y por eso no pasa la validación de "al menos una foto".
            #Con fotos adentro es un error y hay que mostrarlo: alcanzaba una URL de
            #Instagram para entrar acá con el formset inválido, adentro save() corría sólo
            #si había validado, y las fotos que el rescatista subió se descartaban en
            #silencio mientras la pantalla le decía que había salido todo bien
            solo_fotos_de_instagram = bool(instagram_images) and not self.hay_fotos_subidas(image_form_set)

            if animal_form.is_valid() and (formset_ok or solo_fotos_de_instagram):

                is_new_animal = animal_form.instance.id is None
                cambiaron_las_fotos = False
                fotos_a_recomponer = []

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

                if formset_ok:

                    image_form_set.save()

                    #borrar una foto también cambia lo que se revisó
                    if image_form_set.deleted_forms:
                        cambiaron_las_fotos = True

                    #optimize() reescribe el archivo con otro nombre, así que solo corre
                    #sobre las fotos que realmente se subieron: si no, editarle la edad a un
                    #animal recomprimía y renombraba todas sus fotos, y las URLs que ya
                    #habían salido por mail quedaban rotas
                    for form in image_form_set.forms:

                        animal_image = form.instance

                        if form.cleaned_data.get("DELETE") or animal_image.pk is None:
                            continue

                        #el recorte también va dibujado: es el cuadrado que se publica, así
                        #que corregir el encuadre sin rearmar la imagen no cambia el posteo
                        if set(form.changed_data) & set(AnimalImageForm.CROP_FIELDS):
                            fotos_a_recomponer.append(animal_image)

                        if "image" not in form.changed_data:
                            continue

                        ImageService().optimize(animal_image.image, max_width=1200)
                        self.set_suggested_crop(animal_image)

                        #la foto ya no es la que se compuso para Instagram
                        fotos_a_recomponer.append(animal_image)

                for image_url in instagram_images:

                    img_temp = NamedTemporaryFile(delete=True, dir=os.path.join(settings.MEDIA_ROOT, "gallery"))
                    img_temp.write(urlopen(image_url, timeout=20).read())
                    img_temp.flush()

                    animal_image = AnimalImage.objects.create(animal=animal)
                    animal_image.image.save(img_temp.name, File(img_temp))
                    animal_image.save()
                    ImageService().optimize(animal_image.image, max_width=1200)
                    self.set_suggested_crop(animal_image)

                    #estas fotos se crean fuera del formset, así que no aparecen en sus
                    #forms ni marcan has_changed(): sin esto se podían reemplazar todas
                    #las fotos sin tocar el texto y la publicación se quedaba con el
                    #"OK" de la revisión vieja
                    cambiaron_las_fotos = True

                    os.remove(img_temp.name)

                #El nombre, la edad y el sexo van dibujados adentro de la imagen del
                #posteo, así que si cambia alguno hay que rearmar las de todas las fotos:
                #si no, el animal sale publicado con los datos que tenía cuando se armó.
                #El tipo no se dibuja hoy, pero va en la lista igual: es "qué animal es",
                #cambiarlo es rarísimo y rearmar de más no le cuesta nada a nadie.
                if any(c in animal_form.changed_data for c in ("nombre", "edad", "sexo", "tipo")):
                    fotos_a_recomponer = list(animal.get_images())

                self.invalidar_imagenes_de_instagram(animal, fotos_a_recomponer)

                #Si cambiaron las fotos o el texto, lo revisado ya no es lo que hay: sin
                #esto alguien podía cargar un gato de verdad, quedar aprobado, y después
                #editarlo para reemplazar las fotos por otra cosa manteniendo el "OK".
                cambio_lo_revisable = (
                    is_new_animal
                    or any(c in animal_form.changed_data for c in ("nombre", "datos", "tipo"))
                    or cambiaron_las_fotos
                    or self.cambio_alguna_foto(image_form_set)
                )

                self.request.session["animal_save_success"] = True

                if cambio_lo_revisable and not is_new_animal:
                    ModeracionService().revisar_y_guardar(animal)

                if is_new_animal:

                    #Revisión automática de la publicación. Es una ayuda para el equipo:
                    #nunca impide guardar ni publicar por el camino normal. Lo único que
                    #cambia es que, si marca algo raro, no se auto-aprueba y queda para
                    #que lo mire una persona.
                    revision = ModeracionService().revisar_y_guardar(animal)

                    #Quien aprueba es la revisión, no el historial del rescatista: si vio
                    #el animal en las fotos y el texto no es spam, la publicación sale.
                    #Se exige OK y no "distinto de R": 'E' es que NO se pudo revisar
                    #(API caída, sin crédito, foto ilegible) y eso no es un veredicto,
                    #así que no alcanza para publicar sin que mire nadie.
                    #
                    #Cuando la revisión no pudo correr queda el criterio viejo, el
                    #historial: al rescatista con animales ya aprobados a mano no se le
                    #frena la carga porque OpenAI esté caída, y al que recién llega
                    #tampoco se le abre la puerta por el mismo motivo.
                    reviso_bien = revision == Animal.REVISION_OK

                    tiene_historial = (
                        animal.cargado_por is not None
                        and animal.cargado_por.automatic_approve
                    )

                    auto_aprobar = reviso_bien or (
                        revision == Animal.REVISION_ERROR and tiene_historial
                    )

                    if auto_aprobar:
                        animal.aprobado = True
                        animal.save()

                        #la auto-aprobación es uno de los caminos por los que un animal
                        #pasa a aprobado, así que también agenda el posteo. Es el que más
                        #lo necesita: acá no miró nadie, y la demora es la única ventana
                        #que tiene el equipo para frenarlo.
                        InstagramAutoService().agendar(animal)

                        MailService().send_new_animal_mail(animal)
                        self.request.session["is_new_animal_approved"] = True
                    else:
                        MailService().send_new_animal_mail(animal)
                        #el mensaje que ve el rescatista es el mismo de siempre ("estamos
                        #revisando la publicación"): si el filtro se equivoca, acusar a
                        #alguien que acaba de rescatar un animal es peor que esperar a que
                        #una persona lo mire. El motivo lo ve el equipo en /tools/.
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
            animal.save()

            #aprobar es lo que agenda el posteo en Instagram. Agendar no puede hacer
            #fallar la aprobación: el servicio se traga sus propios errores, igual que
            #el mail de acá abajo.
            InstagramAutoService().agendar(animal)

            #un problema mandando el mail no puede perder la aprobación: se mandaba
            #antes de guardar y, cuando el proveedor fallaba, el animal quedaba sin
            #aprobar y quien apretó "Aprobar!" en el mail veía un 500
            try:
                MailService().send_mail_aprobacion(animal)
            except Exception:
                logger.exception("No se pudo avisar de la aprobación de %s", animal.nombre)

            #el nombre lo escribe cualquiera que se registre y esto sale como text/html
            #en la sesión de quien aprueba, que es del equipo: sin escapar, un animal
            #llamado "<script>..." corría en su navegador
            return self.response("{} aprobado!".format(escape(animal.nombre)))

        return self.response("{} ya habia sido aprobado".format(escape(animal.nombre)))


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

    #Cada pedido sale a buscar el post a Instagram y hace una llamada paga a OpenAI, y
    #el registro es abierto: sin tope, cualquiera que se registre puede vaciarle la
    #cuenta de OpenAI al refugio con un bucle de curl. Nadie carga 20 animales en un
    #día, así que a un rescatista real no le molesta.
    MAX_POR_USUARIO_POR_DIA = 20

    def get_limite_diario(self):

        return getattr(settings, "GPT_IG_MAX_POR_DIA", self.MAX_POR_USUARIO_POR_DIA)

    def paso_el_limite(self, usuario):
        """True si esta persona ya gastó su cupo de pedidos del día.

        Cuenta pedidos y no animales: lo que se paga es la llamada, y pedirle veinte
        veces los datos del mismo post cuesta lo mismo que cargar veinte animales.
        """

        limite = self.get_limite_diario()
        if not limite:
            return False

        desde = timezone.now() - timedelta(days=1)

        return ChatGTPResponse.objects.filter(
            pedido_por=usuario, created_at__gte=desde,
        ).count() >= limite

    def get(self, *a, **k):

        url = self.request.GET.get("url")

        if self.paso_el_limite(self.request.user):
            logger.warning("El usuario %s pasó el límite diario de pedidos a ChatGPT", self.request.user.id)
            return self.json_response({"error": "Por hoy llegaste al límite de posts que podemos leer. Cargá los datos a mano y probá de nuevo mañana."})

        #el pedido se anota antes de hacerlo: contando solo los que salen bien alcanza
        #con hacerlos fallar para gastar llamadas sin tope
        ChatGTPResponse.objects.create(pedido_por=self.request.user, ig_url_for_chatgpt=(url or "")[:255])

        #depende de Instagram y de la API de OpenAI: cuando algo de eso falla, el
        #rescatista tiene que poder seguir cargando el animal a mano
        try:
            data = GPTService().pull_data_from_ig(url)
        except ValueError as error:
            return self.json_response({"error": str(error)})
        except Exception as error:
            #Sentry manda a nivel ERROR el contexto del request, cookie de sesión
            #incluida. Que Instagram o la API de OpenAI fallen es esperable: va como
            #warning, sin exc_info, para no crear un evento con la sesión adentro.
            logger.warning("No se pudieron traer los datos de %s: %s", url, type(error).__name__)
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