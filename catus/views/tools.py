from catus.utils import clean_html, has_crop_fields, parse_crop
import uuid
import zipfile
from django.http import HttpResponse
from catus.models import Animal, AnimalImage, CatusUser
from catus.services.facebook import FacebookApiService
from catus.services.images import ImageService
from catus.services.instagram_auto import InstagramAutoService
from django.conf import settings
from .base import BaseView
from django.core.files import File
from django.core.files.base import ContentFile
from datetime import datetime, timedelta
from catus.services.mail import MailService
from catus.utils import rreplace
from django.db.models import Case, F, IntegerField, Prefetch, Q, Value, When
from django.utils import timezone


def animal_por_id(animal_id):
    """El animal con ese id, o None si el id no es un id.

    Django castea el filtro por id a entero: con un "abc" —un bot, un fetch a mano, un
    formulario a medio armar— filter(id=...) levantaba ValueError y la pantalla contestaba
    500 en vez del "No se encontró el animal." que ya estaba escrito abajo.
    """

    try:
        animal_id = int(animal_id)
    except (TypeError, ValueError):
        return None

    return Animal.objects.filter(id=animal_id).first()


class ToolsIndexView(BaseView):

    url = r"^tools/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        #cuántos posteos están esperando su hora, para que se vea desde acá que hay algo
        #por salir: la cola no figuraba en este índice y era el único lugar donde se frena
        #un posteo automático, así que había que saberse la URL de memoria.
        #Se le pide la cola a la vista de la cola y no una copia del filtro: una copia se
        #despega el día que el criterio cambie, y acá diría que no hay nada por salir.
        return self.render_to_response({
            "agendados": ColaInstagramView().agendados(timezone.now()).count(),
        })


class GenerarImagenView(BaseView):

    url = r"^tools/generarimagen/(?P<animal_id>.+)/$"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = animal_por_id(kwargs["animal_id"])
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
        # O que la revisión automática marcó para mirar
        # Y que no estén adoptados
        #lo marcado por la IA entra aunque ya esté aprobado y listo: la re-revisión al editar
        #existe justamente para el que carga un animal de verdad y después le cambia las fotos
        #y el texto, y esta pantalla es el único lugar donde se ve ese "R"
        animals = Animal.objects.filter(
            (
                Q(aprobado=False)
                | Q(instagram_listo_para_publicar=False)
                | Q(revision_ia_estado=Animal.REVISION_REVISAR)
            ) & ~Q(estado="A")
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


class ColaInstagramView(BaseView):
    """Qué está por salir a Instagram, qué salió mal, y el botón para frenarlo.

    Con el posteo automático el animal se agenda solo al aprobarse, y aprobado=True no
    quiere decir que alguien lo haya mirado: automatic_approve le regala la
    auto-aprobación a cualquiera que ya tenga un animal aprobado, así que del segundo
    animal en adelante nadie mira nada. La demora hasta que sale el posteo es el único
    gate humano que queda, y esta pantalla es donde se usa.
    """

    url = r"^tools/colainstagram/$"

    #instagram_error es TextField null: el cron lo limpia con None, pero un animal viejo
    #puede tenerlo en "", así que las dos formas cuentan como "sin problemas"
    SIN_ERROR = Q(instagram_error__isnull=True) | Q(instagram_error="")

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        ahora = timezone.now()

        #se le pregunta una vez sola y se reparte entre los tres grupos
        publicables = self.los_que_el_cron_publica()

        #los tres grupos van en una sola lista porque la tarjeta del animal es la misma en
        #los tres: repetida en el template es donde se cuelan las diferencias
        return self.render_to_response({"grupos": [
            {
                "clave": "agendados",
                "titulo": "Agendados",
                "detalle": "esperando su hora: hasta que salgan se pueden cancelar",
                "vacio": "No hay nada agendado.",
                "animales": self.preparar(self.agendados(ahora), publicables, ahora),
            },
            {
                "clave": "en_cola",
                "titulo": "En cola",
                "detalle": "les toca en la próxima corrida del cron",
                "vacio": "No hay nada esperando al cron.",
                "animales": self.preparar(self.en_cola(ahora), publicables, ahora),
            },
            {
                "clave": "con_problemas",
                "titulo": "Con problemas",
                "detalle": "fallaron y quedaron fuera de la cola: no los levanta ningún cron",
                "vacio": "Ninguno quedó trabado.",
                "animales": self.preparar(self.con_problemas(), publicables, ahora),
            },
        ]})

    def post(self, *args, **kwargs):

        #cancelar y publicar-ya cambian lo que va a salir a la cuenta de la organización:
        #por POST con token, nunca por un link, que cualquier prefetch del navegador o un
        #<img src> ajeno dispara sin que nadie apriete nada
        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        animal = animal_por_id(self.request.POST.get("animal_id"))
        if animal is None:
            return self.response("No se encontró el animal.")

        accion = self.request.POST.get("accion")

        if accion == "cancelar":
            return self.cancelar(animal)

        if accion == "publicar_ya":
            return self.publicar_ya(animal)

        return self.response("No se entendió qué hacer con el animal.")

    def cancelar(self, animal):
        """Saca al animal de la cola. Es el gate humano: mientras dura la demora, esto frena.

        Lo hace InstagramAutoService, que es quien agenda: cancelar apaga también
        instagram_listo_para_publicar, porque para el cron un animal listo y sin fecha es
        "publicá ya", así que limpiando sólo la fecha el posteo salía en la corrida
        siguiente. Esa regla vive en un solo lado a propósito: dos copias es lo mismo que
        ninguna el día que una cambie.
        """

        if not InstagramAutoService().cancelar(animal):
            return self.response("No se pudo cancelar: fijate si ya se publicó.")

        return self.response("ok")

    def publicar_ya(self, animal):
        """Vence la agenda: el animal deja de esperar y entra en la próxima corrida del cron.

        Vence la agenda y nada más. Antes prendía también la marca de listo, y la marca
        quiere decir "las imágenes del posteo ya están armadas": prendiéndola a mano el
        botón salteaba a preparar_publicaciones, que es quien las arma y quien se niega a
        marcar al animal que quedó con alguna sin armar. Así el botón mandaba a publicar
        carruseles a los que les faltaban fotos que el rescatista sí había cargado.

        Al que ya las tiene armadas se le prende igual: es el flujo viejo, el de armarlas a
        mano desde /tools/generarimagen/, donde no hay nada que preparar y sin la marca el
        cron no lo mira.

        Se escribe con update() y no con save() por lo mismo que el resto del pipeline: el
        post_save de Animal reescribe el desplegable de forms_builder.
        """

        campos = {"instagram_programado_para": timezone.now()}

        if self.tiene_las_imagenes_armadas(animal):
            campos["instagram_listo_para_publicar"] = True

        actualizados = Animal.objects.filter(id=animal.id, instagram_publicado=False).update(**campos)

        if not actualizados:
            return self.response("No se pudo publicar: fijate si ya se publicó.")

        return self.response("ok")

    def tiene_las_imagenes_armadas(self, animal):
        """Si no le queda ninguna foto sin su imagen de Instagram.

        Con una sola foto sin armar el carrusel sale incompleto, así que en ese caso la
        marca la tiene que poner preparar_publicaciones después de armarla, y no un botón.
        Sin fotos tampoco hay posteo, y ahí all() sobre una lista vacía diría que sí.
        """

        imagenes = list(animal.get_images())

        return bool(imagenes) and all(imagen.image_for_instagram for imagen in imagenes)

    def pendientes(self):
        """Lo que está en el pipeline de Instagram y todavía no salió.

        "En el pipeline" es tener la agenda puesta, la marca de listo, o un error anotado
        de un intento anterior: sin eso el animal no va camino a ningún lado, y filtrar
        sólo por instagram_publicado=False es listar el sitio entero.

        Viene con el rescatista y las fotos ya traídos. El prefetch repite el orden de
        Animal.get_images() para mostrar la misma portada que el carrusel. Pedir la foto
        adentro del for —como hacen las otras pantallas de la cola— es una consulta por
        animal, y acá se listan los tres grupos juntos.
        """

        fotos = AnimalImage.objects.order_by(F("posicion").asc(nulls_last=True), "id")

        return Animal.objects.filter(
            Q(instagram_programado_para__isnull=False)
            | Q(instagram_listo_para_publicar=True)
            | ~self.SIN_ERROR,
            instagram_publicado=False,
        ).select_related(
            "cargado_por",
        ).prefetch_related(
            Prefetch("animalimage_set", queryset=fotos, to_attr="fotos"),
        )

    def agendados(self, ahora):
        """Los que esperan su hora: es la ventana para cancelar, y por eso van primero.

        Un error encima no los mueve de acá. Antes los grupos se decidían por no tener
        error, así que a un agendado al que el cron le escribía un motivo se le caía la
        tarjeta a "Con problemas" y perdía el botón de cancelar, sin que el posteo se
        hubiera frenado: la agenda seguía puesta y el posteo salía igual al llegar la hora.
        El motivo se muestra como una nota adentro de la tarjeta.
        """

        return self.pendientes().filter(
            instagram_programado_para__gt=ahora,
        ).order_by("instagram_programado_para")

    def en_cola(self, ahora):
        """Vencidos o marcados a mano: los levanta el cron en la próxima corrida.

        Son las dos etapas del pipeline y una sola espera: al vencido sin la marca lo
        levanta preparar_publicaciones, que le arma las imágenes y recién ahí lo marca, y
        al marcado lo levanta publish.

        Un agendado a futuro que además esté marcado como listo es un agendado y nada más:
        si cayera en los dos grupos, el equipo lo cancelaría en uno y lo seguiría viendo
        como que está por salir en el otro.
        """

        return self.pendientes().filter(
            Q(instagram_programado_para__lte=ahora)
            | Q(instagram_programado_para__isnull=True, instagram_listo_para_publicar=True),
        ).order_by("instagram_programado_para", "id")

    def con_problemas(self):
        """Los que quedaron fuera de la cola: sin agenda y sin marca, con el motivo escrito.

        Es el resto del pipeline y no "los que tienen un error": el error de uno que sigue
        agendado o en cola es una nota de su tarjeta, porque ahí el posteo no se frenó.
        Definido como el complemento de los otros dos grupos a propósito: así los tres son
        excluyentes y ninguno de los que están en el pipeline queda sin aparecer.
        """

        return self.pendientes().filter(
            instagram_programado_para__isnull=True,
            instagram_listo_para_publicar=False,
        ).order_by("-instagram_ultimo_intento", "id")

    def preparar(self, animales, publicables, ahora):
        """Le cuelga a cada animal lo que la pantalla necesita y el modelo no tiene."""

        animales = list(animales)

        for animal in animales:
            animal.no_sale = self.motivo_para_no_salir(animal, publicables)
            animal.falta = self.falta_para(animal, ahora)

        return animales

    def falta_para(self, animal, ahora):
        """Cuánto falta para que salga, en castellano, o None si ya le tocó.

        A mano y no con el filtro timeuntil de Django porque el sitio corre con USE_I18N
        en False: Django no traduce nada y la pantalla, que está toda en castellano,
        decía "Sale en 41 minutes".
        """

        if not animal.instagram_programado_para or animal.instagram_programado_para <= ahora:
            return None

        minutos = int((animal.instagram_programado_para - ahora).total_seconds() // 60)

        if minutos < 1:
            return "menos de un minuto"

        if minutos < 60:
            return "{} {}".format(minutos, "minuto" if minutos == 1 else "minutos")

        horas, minutos = divmod(minutos, 60)

        if not minutos:
            return "{} {}".format(horas, "hora" if horas == 1 else "horas")

        return "{} h {} min".format(horas, minutos)

    def los_que_el_cron_publica(self):
        """Ids de los animales que el comando publish está dispuesto a publicar.

        Se le pregunta al comando en vez de copiar sus reglas acá: la cola es lo que el
        cron levanta, y una copia se despega en silencio el día que el criterio cambie.
        Entonces esta pantalla estaría diciendo "está por salir" de algo frenado, que es
        justo lo que no puede pasar con lo que la revisión automática marcó para mirar.
        """

        from catus.management.commands.publish import Command

        return set(Command().animales_a_publicar().values_list("id", flat=True))

    def motivo_para_no_salir(self, animal, publicables):
        """Por qué no va a salir, o None si sí va a salir. Sólo para poder explicarlo."""

        if animal.id in publicables:
            return None

        if not animal.aprobado:
            return "Todavía no está aprobado."

        if animal.estado not in ("D", "R"):
            return "Ya no está en adopción."

        if animal.necesita_revision_humana():
            return "La revisión automática lo marcó para mirar a mano."

        #El pipeline automático son dos etapas y `publicables` es sólo la segunda: la marca
        #de listo la prende preparar_publicaciones cuando le llega la hora al animal.
        #Preguntando nada más que por la etapa de publish, esta pantalla decía "No va a
        #salir" de todo lo agendado, o sea del camino feliz entero.
        #Los tres filtros de arriba son los mismos que mira preparar_publicaciones, así que
        #si llegó hasta acá con la agenda puesta, lo va a levantar y va a salir.
        if animal.instagram_programado_para:
            return None

        if not animal.instagram_listo_para_publicar:
            return "No está marcado como listo para publicar."

        return "El cron no lo va a levantar."


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
        animal = animal_por_id(self.request.POST.get("animal_id"))
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

        animal = animal_por_id(kwargs["animal_id"])
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

        animal = animal_por_id(self.request.POST.get("animal_id"))
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

        animal = animal_por_id(self.request.POST.get("animal_id"))
        if animal is None:
            return self.response("No se encontró el animal.")

        #el botón manda "" al desmarcar (no omite la clave), así que preguntar por
        #"is not None" lo dejaba siempre en True: desmarcar no tenía ningún efecto y
        #el cron publicaba igual el animal
        valor = (self.request.POST.get("instagram_listo_para_publicar") or "").strip().lower()

        if valor not in ("on", "true", "1", "si"):
            #destildar es un gesto de freno, y frenar tiene que sacarlo de la cola entera.
            #Apagando sólo la marca con un save(), la agenda quedaba puesta y vencida:
            #preparar_publicaciones volvía a levantar al animal en la corrida siguiente y le
            #volvía a prender la marca, así que el destildado se revertía solo y el posteo
            #salía igual. Lo hace InstagramAutoService, que es quien agenda: qué quiere
            #decir cancelar vive en un solo lado a propósito.
            if not InstagramAutoService().cancelar(animal):
                return self.response("No se pudo sacar de la cola: fijate si ya se publicó.")

            return self.response("ok")

        animal.instagram_listo_para_publicar = True
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