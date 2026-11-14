import logging
from io import BytesIO

import requests
from PIL import Image
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from catus.services.duplicados import DuplicadosService
from catus.services.images import ImageService
from catus.services.instagram_auto import InstagramAutoService
from catus.services.mail import MailService
from catus.services.moderacion import ModeracionService
from catus.views.base import BaseView, SoloPostMixin, SuperuserRequiredMixin, puede_editar_animal
from catus.services.gpt import GPTService
from django.forms import inlineformset_factory

from catus.models import Animal, AnimalImage, CatusUser, ChatGTPResponse, EstadoFormulario
from catus.services.buenadoptante import TIPOS_PREADOPCION, BuenAdoptanteService
from catus.forms import AnimalImageForm, CatusUserForm, RequiredImageInlineFormset
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.core.files import File
from django.core.files.uploadedfile import UploadedFile
from tempfile import NamedTemporaryFile
from django.utils import timezone
from django.utils.html import escape, format_html
import os

from catus.forms import AnimalForm
from catus.utils import DescargaRechazada, descargar, es_url_de_foto_de_instagram

logger = logging.getLogger(__name__)

#una foto de un post de Instagram pesa unos cientos de KB; esto es para que una URL
#no pueda llenar la memoria ni el disco
MAX_FOTO_INSTAGRAM_BYTES = 15 * 1024 * 1024

#el ancho con el que se optimiza cada foto del alta. La búsqueda de duplicados rehace esa
#misma cuenta para comparar contra lo guardado: tiene que ser el mismo número
MAX_ANCHO_FOTO = 1200


def bajar_foto_de_instagram(image_url):
    """Los bytes de una foto de un post de Instagram, o None si no se puede.

    La URL la manda el navegador: solo se va a buscar a los CDN de Instagram, por
    https, con timeout y tope de tamaño, y lo que vuelve tiene que ser una imagen.
    """

    try:
        contenido = descargar(image_url, es_url_de_foto_de_instagram, MAX_FOTO_INSTAGRAM_BYTES)
        Image.open(BytesIO(contenido)).verify()
    except DescargaRechazada as error:
        logger.warning("Se descartó una foto de Instagram: %s", error)
        return None
    except (requests.RequestException, OSError, SyntaxError, ValueError) as error:
        logger.warning("No se pudo traer la foto %s: %s", image_url, error)
        return None

    return contenido


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

            if not es_url_de_foto_de_instagram(image_url):
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
        los datos viejos.

        Y borrarlas obliga a devolver el animal a la etapa de preparación. La agenda es de
        un solo uso: cuando preparar_publicaciones marca el animal como listo, la consume.
        De ahí en más lo único que lo levanta es publish, que publica lo que tenga imagen
        compuesta y no exige que las tengan todas. Editando en esa ventana —entre un cron
        y el otro, o durante el backoff de un intento fallido— el posteo salía sin la foto
        que el rescatista acababa de tocar; y si el cambio fue en el nombre, la edad, el
        sexo o el tipo se invalidan todas y el animal no salía nunca más, con
        /tools/colainstagram/ diciendo que iba a salir.

        Sólo mientras el posteo no salió. Después de publicado ese archivo es lo que se
        subió a Instagram: rearmarlo no cambia el post que ya está en la cuenta (el cron
        ni lo mira, preparar_publicaciones filtra instagram_publicado=False) y borrarlo
        sólo pierde el registro de lo que se publicó.
        """
        from catus.services.instagram_auto import InstagramAutoService

        if animal.instagram_publicado:
            return

        for imagen in imagenes:
            if imagen.image_for_instagram:
                imagen.image_for_instagram.delete(save=True)

        if not animal.instagram_listo_para_publicar:
            return

        #la pregunta no es "¿borré alguna?" sino "¿le falta alguna?". Una foto AGREGADA no
        #tiene imagen compuesta que borrar, así que mirando sólo lo que se borró el animal
        #se quedaba listo y publish posteaba el carrusel sin la foto nueva.
        if all(imagen.image_for_instagram for imagen in animal.get_images()):
            return

        #se apaga la marca y se vuelve a agendar, así preparar_publicaciones lo levanta y
        #rehace lo que falta. De paso se recupera la ventana para frenarlo, que es lo que
        #corresponde: el contenido cambió después de haber sido aprobado.
        Animal.objects.filter(id=animal.id).update(instagram_listo_para_publicar=False)
        animal.instagram_listo_para_publicar = False

        InstagramAutoService().agendar(animal)

    def avisar_del_animal_nuevo(self, animal):
        """Le avisa al equipo del alta. Un fallo del mail no puede voltear el alta.

        `send_html_email` reintenta tres veces y después vuelve a lanzar (utils.py), así
        que una API key vencida de SendGrid o un 429 le devolvían un 500 al rescatista con
        el animal YA guardado, ya revisado, ya aprobado y ya agendado para Instagram: la
        persona ve un error, no sabe que quedó cargado, y si vuelve a intentar carga un
        duplicado. Es el mismo criterio que `aprobar_animales` en admin.py y que
        `AprobarView`, que ya lo tenían.
        """

        try:
            MailService().send_new_animal_mail(animal)
        except Exception:
            logger.exception("No se pudo avisar del alta de %s", animal.id)

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

    def fotos_subidas(self, image_form_set):
        """Los archivos que este POST trae para guardar, sin las filas tildadas para borrar.

        Sólo tiene sentido con el formset validado: es cleaned_data lo que se guarda.
        """

        fotos = []

        for form in image_form_set.forms:

            datos = getattr(form, "cleaned_data", None) or {}
            foto = datos.get("image")

            if datos.get("DELETE") or not isinstance(foto, UploadedFile):
                continue

            fotos.append(foto)

        return fotos

    def buscar_duplicado(self, animal_form, image_form_set, formset_ok, instagram_images):
        """¿Esta persona ya tiene cargado este mismo animal? Se pregunta al dar de alta.

        En producción una cuenta cargó al mismo perro dos veces con 29 minutos de
        diferencia, con el mismo texto y las mismas seis fotos: el primero estaba
        esperando la aprobación y la persona, como no lo veía publicado, lo volvió a
        cargar. Se pregunta antes de guardar nada, así no queda ni el animal ni sus fotos.

        No es atómico: busca y después guarda, sin lock. Frena a un segundo POST sólo si
        llega después de que el primero se guardó; dos pegados, como los de un doble clic,
        pasan los dos. Contra eso protege la guarda del botón en animal/edit.html.

        Las fotos que vienen de un post de Instagram se bajan después de guardar: para esas
        queda la comparación de los datos.
        """

        return DuplicadosService().buscar(
            self.request.user,
            animal_form.cleaned_data,
            fotos_subidas=self.fotos_subidas(image_form_set) if formset_ok else [],
            hay_fotos_de_instagram=bool(instagram_images),
            max_width=MAX_ANCHO_FOTO,
        )

    def aviso_de_duplicado(self, duplicado):
        """El error que ve quien está cargando de nuevo un animal que ya cargó.

        Le dice dónde está el que ya cargó y en qué anda, que es lo que no sabía: la
        persona lo vuelve a cargar porque no lo ve publicado. Lleva el link para editarlo,
        así que va armado con format_html: el nombre lo escribió el usuario y sale
        escapado, el resto es nuestro.
        """

        animal = duplicado.animal

        if not animal.aprobado:
            situacion = "Está esperando que el equipo lo revise y lo apruebe"
        elif animal.estado == "R":
            situacion = "Ya está publicado, como reservado"
        else:
            situacion = "Ya está publicado"

        #"fotos" es que tiene exactamente las mismas fotos: lo que lo destraba es sumar una que
        #no esté en esa publicación (decirle "subí sus propias fotos" a un gatito cuyas fotos
        #son las de su camada no le servía). Con "datos" y con "nombre y foto" lo que los
        #confunde es el nombre
        if duplicado.motivo == "fotos":
            salida = "Si es otro animal, sumale al menos una foto que no esté en esa publicación."
        else:
            salida = "Si es otro animal, cambiale el nombre para distinguirlo."

        url = "/animales/{}/".format(animal.id)
        fecha = timezone.localtime(animal.created_at).strftime("%d/%m/%Y a las %H:%M")

        return format_html(
            'Ya cargaste a {} el {}. {}: no hace falta cargarlo de nuevo. '
            'Si querés cambiarle algo, editalo desde <a href="{}">{}</a>. {}',
            animal.nombre, fecha, situacion, url, url, salida,
        )

    def req(self, is_post=False, **kwargs):

        ImageFormSet = inlineformset_factory(Animal, AnimalImage, extra=0, can_delete=True, form=AnimalImageForm, formset=RequiredImageInlineFormset)
        context = {}

        if kwargs.get("animal_id"):
            animal = get_object_or_404(Animal, id=kwargs.get("animal_id"))

            #el registro es abierto: sin esto cualquier cuenta abría y editaba el animal
            #de otra persona cambiando el id de la URL, y se lo quedaba
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

            se_puede_guardar = animal_form.is_valid() and (formset_ok or solo_fotos_de_instagram)

            #sólo en el alta (editar un animal no lo duplica) y antes de guardar nada
            duplicado = None
            if se_puede_guardar and animal is None:
                duplicado = self.buscar_duplicado(animal_form, image_form_set, formset_ok, instagram_images)

            if se_puede_guardar and duplicado is None:

                is_new_animal = animal_form.instance.id is None
                cambiaron_las_fotos = False
                fotos_a_recomponer = []

                #Todo o nada: el animal, sus fotos (las subidas y las que se bajan de Instagram),
                #su optimización y su recorte se guardan juntos. Antes el animal se guardaba primero
                #y, si después fallaba una foto (ADOPCIONES-3SVEZ, un disco lleno, una foto que no
                #se pudo procesar), quedaba publicado a medias, sin fotos y sin revisión, y el
                #reintento del rescatista chocaba con el control de duplicados. Lo que sale para
                #afuera (la revisión con IA, la aprobación, el agendado de Instagram, los mails)
                #corre después, con esto ya confirmado. Los archivos que se alcanzaron a escribir
                #no vuelven atrás, pero no queda nada en la base que apunte a ellos.
                with transaction.atomic():
                    animal = animal_form.save(commit=False)

                    #el animal sigue siendo de quien lo cargó: si alguien del equipo entra a
                    #corregirle un dato no se lo queda, ni lo saca del listado del rescatista
                    #ni de los mails de sus formularios
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

                            ImageService().optimize(animal_image.image, max_width=MAX_ANCHO_FOTO)
                            self.set_suggested_crop(animal_image)

                            #la foto ya no es la que se compuso para Instagram
                            fotos_a_recomponer.append(animal_image)

                    for image_url in instagram_images:
                        contenido = bajar_foto_de_instagram(image_url)
                        if contenido is None:
                            continue

                        img_temp = NamedTemporaryFile(delete=True, dir=os.path.join(settings.MEDIA_ROOT, "gallery"))
                        img_temp.write(contenido)
                        img_temp.flush()

                        animal_image = AnimalImage.objects.create(animal=animal)
                        # By its name: Django 3.2+ refuses a path (the file lands in the
                        # same folder, MEDIA_ROOT/gallery, as before).
                        animal_image.image.save(os.path.basename(img_temp.name), File(img_temp))
                        animal_image.save()
                        ImageService().optimize(animal_image.image, max_width=MAX_ANCHO_FOTO)
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
                    moderacion = ModeracionService()
                    revision = moderacion.revisar_y_guardar(animal)

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

                    #...pero sólo cuando el 'E' es una falla ajena. Quedarse sin cupo
                    #también devuelve 'E' y lo provoca el propio usuario: gastando las
                    #revisiones del día (cargar y editar en bucle alcanza) se apagaba la
                    #revisión a sí mismo, y a partir de ahí todo lo que cargara se
                    #auto-aprobaba por historial sin que lo mirara nadie, ni una persona
                    #ni la IA. Y el historial se lo podía fabricar antes con cinco altas
                    #inocuas. El veredicto sigue siendo 'E' y no bloquea nada: lo único
                    #que no hace es aprobar sola. Ese animal espera a que lo mire alguien.
                    falla_ajena = revision == Animal.REVISION_ERROR and not moderacion.sin_cupo

                    auto_aprobar = reviso_bien or (falla_ajena and tiene_historial)

                    if auto_aprobar:
                        animal.aprobado = True
                        animal.save()

                        #la auto-aprobación es uno de los caminos por los que un animal
                        #pasa a aprobado, así que también agenda el posteo. Es el que más
                        #lo necesita: acá no miró nadie, y la demora es la única ventana
                        #que tiene el equipo para frenarlo.
                        InstagramAutoService().agendar(animal)

                        self.avisar_del_animal_nuevo(animal)
                        self.request.session["is_new_animal_approved"] = True
                    else:
                        self.avisar_del_animal_nuevo(animal)
                        #el mensaje que ve el rescatista es el mismo de siempre ("estamos
                        #revisando la publicación"): si el filtro se equivoca, acusar a
                        #alguien que acaba de rescatar un animal es peor que esperar a que
                        #una persona lo mire. El motivo lo ve el equipo en /tools/.
                        self.request.session["is_new_animal"] = True

                return self.redirect(settings.LOGIN_REDIRECT_URL)
            elif duplicado is not None:
                context["success"] = False
                context["errors"] = [self.aviso_de_duplicado(duplicado)]

                logger.info(
                    "Alta frenada: el usuario %s ya cargó este animal (%s, por %s)",
                    self.request.user.id, duplicado.animal.id, duplicado.motivo,
                )
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
    """Publica un animal en el sitio y le avisa a quien lo cargó. Es del equipo: el
    link va en el mail de "Nuevo Ingreso", y no pedía ni login."""

    def get(self, *a, **k):

        animal = Animal.objects.filter(id=self.request.GET.get("id")).first()
        if animal is None:
            return self.response("No se encontró el animal.")

        if not animal.aprobado:
            animal.aprobado = True

            #acá hay una persona del equipo mirando: es lo que cuenta el cron
            #automatic_approve para dar el "historial". Antes contaba cualquier animal
            #aprobado, y como la revisión automática aprueba sola, el historial se lo
            #fabricaba el propio rescatista con cinco altas que la IA dejó pasar.
            animal.aprobado_por_persona = True
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


class ValidateNameView(SoloPostMixin, LoginRequiredMixin, BaseView):

    def post(self, *a, **k):

        name = self.request.POST.get("name")
        if Animal.objects.filter(nombre=name, fecha_adopcion__isnull=True, estado="D").exists():
            return self.json_response({"valid": False})

        return self.json_response({"valid": True})


class PhotosView(SoloPostMixin, BaseView):
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
    #cuenta de OpenAI al refugio con un bucle de curl. En todo el sitio se cargan a lo
    #sumo 7 animales por día, así que a un rescatista real no le molesta.
    MAX_POR_USUARIO_POR_DIA = 10

    #...y el tope por persona solo no alcanza: cada cuenta nueva trae su propio cupo, y
    #crear cuentas es gratis. El total del día es lo único que acota el gasto, que
    #además sale de una clave compartida con otra app.
    MAX_TOTAL_POR_DIA = 30

    def get_limite_diario(self):

        return getattr(settings, "GPT_IG_MAX_POR_DIA", self.MAX_POR_USUARIO_POR_DIA)

    def get_limite_total_diario(self):

        return getattr(settings, "GPT_IG_MAX_TOTAL_POR_DIA", self.MAX_TOTAL_POR_DIA)

    def paso_el_limite_total(self):
        """True si entre todos ya se gastó el cupo de pedidos del día."""

        limite = self.get_limite_total_diario()
        if not limite:
            return False

        desde = timezone.now() - timedelta(days=1)

        return ChatGTPResponse.objects.filter(created_at__gte=desde).count() >= limite

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

        if self.paso_el_limite_total():
            logger.warning("Se llegó al tope diario total de pedidos a ChatGPT (%s)", self.get_limite_total_diario())
            return self.json_response({"error": "Por hoy ya leímos todos los posts que podemos. Cargá los datos a mano y probá de nuevo mañana."})

        #el pedido se anota antes de hacerlo: contando solo los que salen bien alcanza
        #con hacerlos fallar para gastar llamadas sin tope
        pedido = ChatGTPResponse.objects.create(pedido_por=self.request.user, ig_url_for_chatgpt=(url or "")[:255])

        #depende de Instagram y de la API de OpenAI: cuando algo de eso falla, el
        #rescatista tiene que poder seguir cargando el animal a mano
        try:
            data = GPTService().pull_data_from_ig(url, pedido=pedido)
        except ValueError as error:
            return self.json_response({"error": str(error)})
        except Exception as error:
            #Sentry manda a nivel ERROR el contexto del request, cookie de sesión
            #incluida. Que Instagram o la API de OpenAI fallen es esperable: va como
            #warning, sin exc_info, para no crear un evento con la sesión adentro.
            logger.warning("No se pudieron traer los datos de %s: %s", url, type(error).__name__)
            return self.json_response({"error": "No pudimos leer ese post. Cargá los datos a mano."})

        return self.json_response(data)


class UpdateAnimal(SoloPostMixin, LoginRequiredMixin, BaseView):

    response_status = "actualizados"

    def update(self, animal, post_data=None):

        pass

    def after_save(self, animal, post_data=None):

        pass

    def post(self, *a, **k):

        animal_id = self.request.POST.get("animal_id")
        if not animal_id:
            animal_ids = self.request.POST.getlist("animal_ids")
        else:
            animal_ids = [animal_id]

        animals = Animal.objects.filter(id__in=animal_ids)

        #cada quien maneja sus animales; el equipo maneja todos. Sin esto cualquier cuenta
        #marcaba como adoptado (y sacaba del sitio) el animal de otra persona
        if not self.request.user.is_superuser:
            animals = animals.filter(cargado_por=self.request.user)

        animals = list(animals)

        for animal in animals:
            self.update(animal, post_data=self.request.POST)
            animal.save()
            self.after_save(animal, post_data=self.request.POST)

        if not animal_id:
            return self.response("Animales marcados como {}!".format(self.response_status))

        #con un id que no existe (o de otra persona) no hay animal que devolver
        if not animals:
            return self.json_response({"success": False, "error": "No se encontró el animal."})

        return self.json_response({"success": True, "nombre": animals[0].nombre })


class MarcarAdoptado(UpdateAnimal):
    """Marca el animal como adoptado y, si el rescatista dice quién lo adoptó entre los
    formularios de pre-adopción que recibió, lo deja vinculado a ese formulario y manda la
    adopción a BuenAdoptante (la manda el cron)."""

    response_status = "adoptados"

    def formulario_elegido(self, animal, post_data):

        elegido = (post_data or {}).get("estado_formulario_id")
        if not elegido or not str(elegido).isdigit():
            return None

        #un formulario de pre-adopción del mismo rescatista: quien pidió un gato a veces
        #termina adoptando otro. UpdateAnimal ya dejó afuera los animales de otra persona, y
        #así no se puede vincular el formulario de un rescatista ajeno.
        return (EstadoFormulario.objects
                .filter(id=elegido, gato__cargado_por_id=animal.cargado_por_id, tipo__in=TIPOS_PREADOPCION)
                .exclude(estado__in=["B", "U"]).first())

    def update(self, animal, post_data=None):

        #a un animal ya adoptado se le puede decir después quién lo adoptó: no se le pisa
        #la fecha de adopción
        if animal.estado != "A" or animal.fecha_adopcion is None:
            animal.fecha_adopcion = timezone.now()
        animal.estado = "A"

        elegido = self.formulario_elegido(animal, post_data)
        animal._formulario_adoptante = elegido
        if elegido is not None:
            animal.estado_formulario = elegido
            animal.adoptante = (elegido.get_persona() or "")[:255] or None

    def after_save(self, animal, post_data=None):

        elegido = getattr(animal, "_formulario_adoptante", None)
        if elegido is None:
            return

        if elegido.estado != "A":
            elegido.estado = "A"
            elegido.save(update_fields=["estado"])

        BuenAdoptanteService().registrar_adopcion(elegido, animal)


class PosponerPreguntaAdopcion(UpdateAnimal):
    """"Todavía no" a la pregunta "¿se adoptó?" del panel: no se vuelve a preguntar por
    este animal por dos semanas. Con para_siempre ("no lo adoptó nadie de la lista", sobre
    un animal ya adoptado) no se pregunta más."""

    response_status = "pospuestos"
    DIAS = 14

    def update(self, animal, post_data=None):

        dias = 3650 if (post_data or {}).get("para_siempre") == "1" else self.DIAS
        animal.pregunta_adopcion_hasta = timezone.now() + timedelta(days=dias)


class BuscarFormularios(LoginRequiredMixin, BaseView):
    """Busca por nombre entre los formularios de pre-adopción del rescatista de un animal,
    para elegir quién lo adoptó (panel, "Marcar adoptado")."""

    MAXIMO = 20

    def get(self, *a, **k):

        animal_id = self.request.GET.get("animal_id") or ""
        texto = " ".join((self.request.GET.get("q") or "").split())[:60]

        animal = Animal.objects.filter(id=animal_id).first() if animal_id.isdigit() else None
        if animal is None or not puede_editar_animal(self.request.user, animal):
            return self.json_response({"resultados": []})

        if len(texto) < 2:
            return self.json_response({"resultados": []})

        formularios = (EstadoFormulario.objects
                       .filter(gato__cargado_por_id=animal.cargado_por_id, tipo__in=TIPOS_PREADOPCION,
                               persona_nombre__icontains=texto)
                       .exclude(estado__in=["B", "U"])
                       .select_related("gato")
                       .order_by("-id")[:self.MAXIMO])

        resultados = []
        for formulario in formularios:
            fecha = formulario.fecha_ingreso or formulario.created_at
            resultados.append({
                "id": formulario.id,
                "persona": (formulario.persona_nombre or "Sin nombre")[:80],
                "fecha": timezone.localtime(fecha).strftime("%d/%m/%Y") if fecha else "",
                "animal": (formulario.gato.nombre if formulario.gato else "")[:60],
            })
        return self.json_response({"resultados": resultados})


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


class AddComment(SoloPostMixin, SuperuserRequiredMixin, BaseView):
    """La nota del equipo sobre un rescatista (/tools/): cualquier cuenta podía
    pisar la de cualquiera."""

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