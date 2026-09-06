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


def por_id(entidad, id_):
    """La fila de esa entidad con ese id, o None si el id no es un id.

    Django castea el filtro por id a entero: con un "abc" —un bot, un fetch a mano, un
    formulario a medio armar— filter(id=...) levantaba ValueError y la pantalla contestaba
    500 en vez del "No se encontró..." que ya estaba escrito abajo.
    """

    try:
        id_ = int(id_)
    except (TypeError, ValueError):
        return None

    return entidad.objects.filter(id=id_).first()


def animal_por_id(animal_id):
    """El animal con ese id, o None si el id no es un id."""

    return por_id(Animal, animal_id)


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

    #Lo que dice la pantalla cuando el posteo automático está apagado, que es el default:
    #preparar_publicaciones corta de entrada y publish sólo levanta lo que NO está
    #agendado, así que el agendado espera a dos crones que no lo van a mirar nunca.
    POSTEO_APAGADO = "El posteo automático está apagado: ningún cron va a levantar lo agendado."

    #Y lo que hay que hacer mientras tanto, que es el flujo de siempre: las imágenes se
    #arman a mano desde /tools/generarimagen/ y ahí se marca al animal como listo.
    A_MANO = (
        "El posteo automático está apagado: no hay ningún cron que le arme las imágenes. "
        "Armalas en \"Imágenes de Instagram\" y marcalo como listo para publicar."
    )

    DETALLE_AGENDADOS = "esperando su hora: hasta que salgan se pueden cancelar"
    DETALLE_AGENDADOS_APAGADO = "esperando una hora que no los va a levantar nadie"
    DETALLE_EN_COLA = "les toca en la próxima corrida del cron"
    DETALLE_EN_COLA_APAGADO = "sólo sale lo que está marcado como listo para publicar"

    def get(self, *args, **kwargs):

        if not self.request.user.is_superuser:
            return self.response("No tenes permisos para esto.")

        ahora = timezone.now()

        #se le pregunta una vez sola y se reparte entre los tres grupos
        publicables = self.los_que_el_cron_publica()

        #que el pipeline automático esté andando o no cambia todo lo que esta pantalla
        #puede prometer, así que se pregunta una vez y baja hasta las tarjetas
        activo = self.posteo_automatico_activo()

        #los tres grupos van en una sola lista porque la tarjeta del animal es la misma en
        #los tres: repetida en el template es donde se cuelan las diferencias
        return self.render_to_response({
            "posteo_automatico_activo": activo,
            "grupos": [
                {
                    "clave": "agendados",
                    "titulo": "Agendados",
                    "detalle": self.DETALLE_AGENDADOS if activo else self.DETALLE_AGENDADOS_APAGADO,
                    "vacio": "No hay nada agendado.",
                    "animales": self.preparar(self.agendados(ahora), publicables, ahora, activo),
                },
                {
                    "clave": "en_cola",
                    "titulo": "En cola",
                    "detalle": self.DETALLE_EN_COLA if activo else self.DETALLE_EN_COLA_APAGADO,
                    "vacio": "No hay nada esperando al cron.",
                    "animales": self.preparar(self.en_cola(ahora), publicables, ahora, activo),
                },
                {
                    "clave": "con_problemas",
                    "titulo": "Con problemas",
                    "detalle": "fallaron y quedaron fuera de la cola: no los levanta ningún cron",
                    "vacio": "Ninguno quedó trabado.",
                    "animales": self.preparar(self.con_problemas(ahora), publicables, ahora, activo),
                },
            ],
        })

    def posteo_automatico_activo(self):
        """Si el pipeline automático está andando de verdad.

        Se le pregunta al servicio que agenda en vez de mirar el setting: el flag puede
        llegar como texto desde el JSON de config y desde una máquina de desarrollo no
        cuenta, y esas dos reglas ya viven allá. Una copia acá diría que sí en casos en los
        que el cron dice que no, que es justo lo que esta pantalla no puede hacer.
        """

        return InstagramAutoService().esta_activo()

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

        Con el posteo automático apagado esto no aplica y el botón hace otra cosa: vencer
        la agenda ahí es sacar al animal de los dos crones para siempre.

        Se escribe con update() y no con save() por lo mismo que el resto del pipeline: el
        post_save de Animal reescribe el desplegable de forms_builder.
        """

        #devolverle los intentos al que una corrida puede estar subiendo ahora mismo es
        #sacarle el único candado contra el post duplicado: con el contador en cero la
        #corrida siguiente lo reclama mientras la primera todavía sube fotos
        if self.agoto_los_intentos(animal) and self.se_esta_publicando(animal):
            return self.response("Se intentó publicar recién: esperá un rato o puede salir dos veces.")

        if not self.posteo_automatico_activo():
            return self.publicar_ya_a_mano(animal)

        campos = {"instagram_programado_para": timezone.now()}
        campos.update(self.devolverle_los_intentos(animal))

        if self.tiene_las_imagenes_armadas(animal):
            campos["instagram_listo_para_publicar"] = True

        return self.guardar(animal, campos)

    def publicar_ya_a_mano(self, animal):
        """"Publicar ya" con el posteo automático apagado: no hay cron al que mandarlo.

        Vencer la agenda es lo que hace salir al animal cuando el pipeline está andando,
        pero con el flag apagado lo saca de los dos crones para siempre:
        preparar_publicaciones corta de entrada y publish sólo levanta lo que NO tiene
        agenda. El botón dejaba al animal agendado y vencido, esperando a nadie, y la
        pantalla seguía diciendo que iba a salir. El flag arranca apagado, así que ese era
        el caso más común de todos.

        Lo que queda es el flujo de siempre: las imágenes se arman a mano desde
        /tools/generarimagen/ y ahí se marca listo. Por eso acá se limpia la agenda en vez
        de vencerla —con la agenda puesta, publish no lo mira ni marcándolo a mano— y al
        que ya tiene las imágenes armadas se lo marca de una, que es todo lo que le falta.
        Al que no, le queda escrito qué hacer, que es lo que muestra "Con problemas".
        """

        campos = {"instagram_programado_para": None}
        campos.update(self.devolverle_los_intentos(animal))

        if self.tiene_las_imagenes_armadas(animal):
            campos["instagram_listo_para_publicar"] = True
        else:
            campos["instagram_error"] = self.A_MANO

        return self.guardar(animal, campos)

    def guardar(self, animal, campos):
        """El UPDATE de las acciones de la pantalla, con el candado de lo ya publicado.

        Se escribe con update() y no con save() por lo mismo que el resto del pipeline: el
        post_save de Animal reescribe el desplegable de forms_builder.
        """

        actualizados = Animal.objects.filter(id=animal.id, instagram_publicado=False).update(**campos)

        if not actualizados:
            return self.response("No se pudo publicar: fijate si ya se publicó.")

        return self.response("ok")

    def devolverle_los_intentos(self, animal):
        """Los campos para que el que agotó los intentos vuelva a la cola, o nada.

        `publish` deja de intentar después de MAX_INTENTOS y el animal queda con la marca
        puesta, sin agenda y sin que ningún cron lo mire nunca más: reintentar sin
        devolverle el contador es no reintentar nada. El motivo del último fallo se borra
        en la misma movida, que es justo cuando deja de describir lo que va a pasar.
        """

        if not self.agoto_los_intentos(animal):
            return {}

        return {"instagram_intentos": 0, "instagram_error": None}

    def agoto_los_intentos(self, animal):
        """Si `publish` ya se dio por vencido con este animal.

        El número se le pregunta al comando en vez de copiarlo: es él quien deja de
        intentar, y una copia se despega en silencio el día que el número cambie.
        """

        from catus.management.commands.publish import Command

        return animal.instagram_intentos >= Command.MAX_INTENTOS

    def se_esta_publicando(self, animal):
        """Si una corrida lo reclamó hace tan poco que puede seguir subiéndolo.

        Es el mismo criterio con el que `publish` se protege del post duplicado: mientras
        no pasa su primera espera, el animal cuenta como "lo está publicando otra corrida",
        porque un carrusel son minutos de subida.
        """

        from catus.management.commands.publish import Command

        if not animal.instagram_ultimo_intento:
            return False

        return timezone.now() - animal.instagram_ultimo_intento < Command.ESPERA_BASE

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

    def q_en_la_cola_del_cron(self, ahora):
        """Los dos caminos por los que a un animal le toca en la próxima corrida.

        Al vencido sin la marca lo levanta preparar_publicaciones, que le arma las
        imágenes y recién ahí lo marca; al marcado sin agenda lo levanta publish.
        """

        return (
            Q(instagram_programado_para__lte=ahora)
            | Q(instagram_programado_para__isnull=True, instagram_listo_para_publicar=True)
        )

    def q_sin_intentos(self):
        """Q de los que ya gastaron todos los intentos que hace `publish`.

        El número se le pregunta al comando, que es quien deja de intentar: una copia se
        despega en silencio el día que el número cambie.
        """

        from catus.management.commands.publish import Command

        return Q(instagram_intentos__gte=Command.MAX_INTENTOS)

    def en_cola(self, ahora):
        """Vencidos o marcados a mano: los levanta el cron en la próxima corrida.

        Son las dos etapas del pipeline y una sola espera.

        Un agendado a futuro que además esté marcado como listo es un agendado y nada más:
        si cayera en los dos grupos, el equipo lo cancelaría en uno y lo seguiría viendo
        como que está por salir en el otro.

        El que agotó los intentos no está esperando nada: `publish` lo saltea para
        siempre. Quedaba acá diciendo que le tocaba en la próxima corrida, que es la
        pantalla mintiendo justo sobre el que necesita que alguien lo mire.
        """

        return self.pendientes().filter(
            self.q_en_la_cola_del_cron(ahora),
        ).exclude(
            self.q_sin_intentos(),
        ).order_by("instagram_programado_para", "id")

    def con_problemas(self, ahora):
        """Los que quedaron fuera de la cola, con el motivo escrito: sin agenda y sin
        marca, o con los intentos agotados.

        Es el resto del pipeline y no "los que tienen un error": el error de uno que sigue
        agendado o en cola es una nota de su tarjeta, porque ahí el posteo no se frenó.
        Definido como el complemento de los otros dos grupos a propósito: así los tres son
        excluyentes y ninguno de los que están en el pipeline queda sin aparecer.
        """

        return self.pendientes().filter(
            Q(instagram_programado_para__isnull=True, instagram_listo_para_publicar=False)
            | (self.q_sin_intentos() & self.q_en_la_cola_del_cron(ahora)),
        ).order_by("-instagram_ultimo_intento", "id")

    def preparar(self, animales, publicables, ahora, activo):
        """Le cuelga a cada animal lo que la pantalla necesita y el modelo no tiene."""

        animales = list(animales)

        for animal in animales:
            animal.no_sale = self.motivo_para_no_salir(animal, publicables, activo)
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

    def motivo_para_no_salir(self, animal, publicables, activo):
        """Por qué no va a salir, o None si sí va a salir. Sólo para poder explicarlo."""

        #Estos dos van antes que `publicables`, que es la cola de `publish`: esa cola dice
        #quién tiene permiso de salir, no quién va a salir. Los intentos gastados y la
        #agenda los mira animales_de_esta_corrida, así que preguntándole sólo a la cola la
        #pantalla decía "está por salir" de los dos.
        if self.agoto_los_intentos(animal):
            return "Se dejó de intentar después de {} intentos: hay que reintentarlo a mano.".format(
                animal.instagram_intentos,
            )

        if animal.instagram_programado_para and not activo:
            return self.POSTEO_APAGADO

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
        #si llegó hasta acá con la agenda puesta, lo va a levantar y va a salir. Que el
        #pipeline automático esté prendido ya se preguntó arriba: con el flag apagado
        #preparar_publicaciones corta de entrada y no levanta nada.
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

        fonts = [150, 125, 100, 75, 50]

        #por_id y no un get() a pelo: con un image_id vacío o no numérico —el botón que
        #se apretó antes de que cargara la galería, un bot— el filtro por id levantaba
        #ValueError y la pantalla contestaba 500 en vez de "Imagen no encontrada."
        imagen = por_id(AnimalImage, self.request.POST.get("image_id"))
        if imagen is None:
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

        #por_id y no filter() a pelo: con un user_id vacío o no numérico el filtro por id
        #levantaba ValueError y esto contestaba 500 en vez de "No se encontró el usuario."
        user = por_id(CatusUser, self.request.POST.get("user_id"))
        if user is None:
            return self.response("No se encontró el usuario.")

        content = self.request.POST.get("content")
        MailService().send_mail_pregunta(user, content)

        return self.render_to_response({})