from django.db import models
from forms_builder.forms.models import FormEntry
from django.contrib.auth.models import AbstractUser
from catus.managers import UserManager
from django.utils.timezone import localtime
from django.utils import timezone
import random
from django.db.models import F

import json
import logging
import os
import pathlib
import re
import uuid
import requests
from django.conf import settings
from django.utils.text import slugify

logger = logging.getLogger(__name__)

#la edad de un animal leído de la base todavía no se conoce (ver Animal.from_db)
_EDAD_SIN_LEER = object()


def ruta_de_imagen(instance, filename):
    """Dónde y con qué nombre se guarda una imagen subida: gallery/<uuid><extensión>.

    El nombre que manda el navegador no se usa. Django 5 toma como extensión todo lo que
    sigue al PRIMER punto y, si el nombre no entra en los 100 caracteres de la columna,
    acorta solo lo de antes: una imagen llamada como la descripción del animal, con puntos
    en el medio, no se podía guardar (ADOPCIONES-3SVEZ). El arreglo del #553 lo cubrió en el
    formulario del animal; acá queda para toda imagen de los modelos: el banner y el logo
    del perfil, el admin, y lo que se agregue. Queda la última extensión, en minúscula,
    cuando es una extensión de verdad.
    """
    extension = pathlib.PurePath(filename).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
        extension = ""
    return "gallery/{}{}".format(uuid.uuid4(), extension)


class BaseEntity(models.Model):

    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    def __init__(self, *args, **kwargs):

        # A row read from the database comes with every field positionally:
        # its dates stay as they are (Django 2.0 dropped these defaults then,
        # Django 5 refuses a field given both ways).
        given = {f.name for f in self._meta.concrete_fields[:len(args)]}
        now = timezone.now()
        for name in ("created_at", "updated_at"):
            if name not in given:
                kwargs.setdefault(name, now)
        models.Model.__init__(self, *args, **kwargs)

    class Meta:
        abstract = True

    def get_created_at(self):

        created_at = localtime(self.created_at)
        return created_at.strftime("%d/%m/%Y %H:%M")


class Animal(BaseEntity):

    nombre = models.CharField(max_length=255)
    edad = models.CharField(max_length=255, null=True, blank=True)
    edad_en_meses = models.PositiveIntegerField(null=True, blank=True)
    zona = models.CharField(max_length=255, null=True, blank=True)
    datos = models.TextField(null=True, blank=True)
    sexo = models.CharField(max_length=1, default="M", choices=(("M", "Macho"), ("H", "Hembra"), ("A", "Macho y Hembra"), ("D", "Desconocido")))

    fecha_ingreso = models.DateTimeField(null=True, blank=True)
    fecha_adopcion = models.DateTimeField(null=True, blank=True)
    tipo = models.CharField(max_length=2, choices=settings.ANIMAL_TIPO, default="G")
    estado = models.CharField(max_length=2, choices=settings.ANIMAL_ESTADO_CHOICES, default="D") #D: Disponible, #A: Adoptado, #R: Reservado, #E: Expirado

    aprobado = models.BooleanField(default=False)

    #Quién aprobó, no sólo que está aprobado. El cron automatic_approve otorga el
    #"historial" contando animales aprobados, y desde que la revisión automática aprueba
    #sola esa cuenta incluía sus propias aprobaciones: con cinco altas inocuas —que la IA
    #aprueba sin pedirle historial a nadie— cualquiera se ganaba la aprobación automática
    #y, con ella, que las altas siguientes salieran solas a Instagram. Sólo lo marcan los
    #caminos donde mira una persona: AprobarView y el admin (la acción y el tilde).
    #db_default además de default: con un default solo en Python la columna queda NOT NULL sin
    #default en MySQL, y el código de antes de estas migraciones (un rollback) no podía dar de
    #alta un animal: IntegrityError 1364. Ver 0036.
    aprobado_por_persona = models.BooleanField(default=False, db_default=False)

    destacado = models.BooleanField(default=False)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    adoptante = models.CharField(max_length=255, null=True, blank=True)
    estado_formulario = models.ForeignKey("EstadoFormulario", null=True, blank=True, on_delete=models.SET_NULL)

    instagram_publicado = models.BooleanField(default=False)
    instagram_listo_para_publicar = models.BooleanField(default=False)
    instagram_post_id = models.CharField(max_length=255, null=True, blank=True)
    instagram_media_url = models.CharField(max_length=255, null=True, blank=True)
    instagram_comment_id = models.CharField(max_length=255, null=True, blank=True)

    #El posteo automático: al aprobarse, el animal se agenda para más tarde en vez de
    #publicarse al toque, así queda una ventana para cancelarlo desde /tools/. Hace falta
    #porque aprobado=True no garantiza que alguien haya mirado: el comando
    #automatic_approve le regala automatic_approve a cualquiera con un animal aprobado.
    instagram_programado_para = models.DateTimeField(null=True, blank=True)

    #Sin esto el cron reintenta para siempre y en silencio: los errores se escribían por
    #stdout, que nadie mira, y no quedaba nada en el animal para mostrar en una pantalla.
    instagram_intentos = models.PositiveIntegerField(default=0, db_default=0)
    instagram_ultimo_intento = models.DateTimeField(null=True, blank=True)
    instagram_error = models.TextField(null=True, blank=True)

    mail_preguntar_adopcion_enviado = models.BooleanField(default=False)

    #el panel del rescatista pregunta "¿se adoptó?" por los animales con formularios
    #que siguen publicados; "Todavía no" lo deja de preguntar hasta esta fecha
    pregunta_adopcion_hasta = models.DateTimeField(null=True, blank=True)

    #cuándo lo expiró el cron expirar_animales por llevar un mes publicado. Vacío en los
    #que expiró una persona a mano: por esos no se pregunta. El panel pregunta por los que
    #lo tienen ("¿siguen en adopción?") y republicarlo lo vacía.
    expiro_el = models.DateTimeField(null=True, blank=True)

    #cuándo se le mandó al rescatista el mail "¿Siguen en adopción?" de esa expiración
    #(services/expiracion.py). Vale para el expiro_el de ese momento: si después se lo
    #republica y vuelve a expirar, expiro_el es más nuevo y corresponde otro mail.
    expiro_avisado_el = models.DateTimeField(null=True, blank=True)

    #Si el rescatista, al marcarlo adoptado, eligió avisarles a los demás que se postularon que
    #ya encontró familia (services/aviso_candidatos.py). None es que nadie lo eligió (el
    #admin, o antes de que existiera la casilla): entonces no se avisa. Se borra al salir de
    #"Adoptado", así un cambio de estado por error no deja un aviso pendiente.
    avisar_candidatos = models.BooleanField(null=True, blank=True)

    #El equipo decidió no publicarlo: "No publicar" en /tools/animalespendientes/, o el
    #comando archivar_pendientes con lo que esperó demasiado sin que nadie lo mirara. Queda
    #en "E", sin aprobar y sin expiro_el (así el panel no pregunta "¿siguen en adopción?"),
    #y el panel lo muestra como "No se publicó" con el motivo. Si el dueño lo edita, vuelve a
    #la cola (EditView). Antes no había forma de decir que no: quedaba "En revisión" para
    #siempre y tapaba la cola del equipo.
    no_publicar_el = models.DateTimeField(null=True, blank=True)
    no_publicar_motivo = models.TextField(null=True, blank=True)

    custom_link = models.CharField(max_length=255, null=True, blank=True)

    ig_url_for_chatgpt = models.CharField(max_length=255, null=True, blank=True)
    chatgpt_response = models.TextField(null=True, blank=True)

    #Revisión automática de la publicación: que las fotos sean del animal que dice
    #ser y que el texto sea una publicación de adopción de verdad. Es una ayuda para
    #el equipo, no un veredicto: nunca rechaza sola.
    REVISION_PENDIENTE = "P"
    REVISION_OK = "OK"
    REVISION_REVISAR = "R"
    REVISION_ERROR = "E"

    REVISION_IA_CHOICES = (
        (REVISION_PENDIENTE, "Sin revisar"),
        (REVISION_OK, "Parece correcta"),
        (REVISION_REVISAR, "Revisar a mano"),
        (REVISION_ERROR, "No se pudo revisar"),
    )

    revision_ia_estado = models.CharField(
        max_length=2, choices=REVISION_IA_CHOICES, default=REVISION_PENDIENTE, db_default=REVISION_PENDIENTE,
    )
    revision_ia_motivo = models.TextField(null=True, blank=True)
    revision_ia_fecha = models.DateTimeField(null=True, blank=True)

    #Cuántas veces el cron volvió a intentar una revisión que no pudo correr ('E')
    #(services/revision_pendiente.py). Vuelve a 0 con un veredicto o cuando el dueño edita
    #lo revisable; al llegar al tope el cron deja de intentar y le avisa a una persona.
    revision_ia_intentos = models.PositiveSmallIntegerField(default=0, db_default=0)

    #Lo devolvió a la cola su dueño después de que el equipo decidiera no publicarlo: lo
    #decide una persona, así que ni el alta, ni la edición, ni el cron lo aprueban aunque la
    #revisión dé OK. Se apaga cuando una persona lo aprueba (AprobarView).
    espera_a_una_persona = models.BooleanField(default=False, db_default=False)

    def necesita_revision_humana(self):

        return self.revision_ia_estado == self.REVISION_REVISAR

    def no_se_publico(self):
        """Si el equipo decidió no publicarlo y sigue así.

        Se pregunta también por el estado y la aprobación, y no sólo por no_publicar_el:
        si alguien lo vuelve a poner en adopción o lo aprueba por otro camino (el tilde del
        admin, "Republicar" del panel) la fecha puede quedar puesta, y el panel le seguiría
        diciendo al rescatista que no se publicó un animal que está en la cola o en el sitio.
        """

        return self.no_publicar_el is not None and self.estado == "E" and not self.aprobado

    def get_revision_ia_badge(self):

        return {
            self.REVISION_OK: "success",
            self.REVISION_REVISAR: "danger",
            self.REVISION_ERROR: "secondary",
        }.get(self.revision_ia_estado, "light")

    #el texto de la edad como estaba en la base, para saber en save() si cambió
    _edad_guardada = _EDAD_SIN_LEER

    @classmethod
    def from_db(cls, db, field_names, values):

        animal = super().from_db(db, field_names, values)
        #con only()/defer() la edad puede no estar leída: ahí queda sin leer
        animal._edad_guardada = animal.__dict__.get("edad", _EDAD_SIN_LEER)
        return animal

    def save(self, *args, **kwargs):
        from catus.services.cache import CacheService

        if not self.fecha_ingreso:
            self.fecha_ingreso = timezone.now()

        if "update_fields" in kwargs:
            kwargs["update_fields"] = self._completar_edad_en_meses(kwargs["update_fields"])
        else:
            self._completar_edad_en_meses(None)

        result = super(Animal, self).save(*args, **kwargs)
        self._edad_guardada = self.__dict__.get("edad", _EDAD_SIN_LEER)
        #CacheService().set("animals-for-adoption", self.get_all_for_adoption(destacado=True, sort="-fecha_ingreso"))
        return result

    def _completar_edad_en_meses(self, update_fields):
        """Estima edad_en_meses del texto de la edad, que es lo que filtra la portada por
        Cachorros y Adultos (services/edad.py).

        Se calcula cuando no hay un valor o cuando cambió el texto: uno puesto a mano en el
        admin se respeta mientras la edad siga diciendo lo mismo. Un save con update_fields
        que no incluye la edad no la toca. Y nunca hace fallar el guardado: lo peor que
        puede pasar es que el animal quede sin edad en meses, como estaban casi todos.
        Devuelve update_fields, con edad_en_meses agregado si hace falta guardarlo.
        """
        from catus.services.edad import estimar_meses

        if "edad" not in self.__dict__:
            return update_fields

        if update_fields is not None and "edad" not in update_fields:
            return update_fields

        try:
            guardada = self._edad_guardada
            cambio = guardada is not _EDAD_SIN_LEER and guardada != self.edad

            if self.edad_en_meses is None or cambio:
                self.edad_en_meses = estimar_meses(self.edad)
                if update_fields is not None and "edad_en_meses" not in update_fields:
                    update_fields = list(update_fields) + ["edad_en_meses"]

        except Exception:
            logger.exception("No se pudo estimar la edad en meses del animal %s", self.pk)

        return update_fields

    def __str__(self, *a, **k):

        return self.nombre if self.nombre else self.id

    def get_datos(self):

        return self.datos.strip()

    def get_fecha_ingreso(self):

        if not self.fecha_ingreso:
            return

        return self.fecha_ingreso.strftime("%d/%m/%Y")

    @classmethod
    def get_all_for_adoption(cls, sort=None, destacado=None, extra_filters=None, tipo=None):

        if extra_filters is None:
            extra_filters = {}

        extra_filters["estado"] = "D"

        animals = Animal.objects.filter(aprobado=True, **extra_filters).select_related("cargado_por").prefetch_related("animalimage_set")

        if tipo is not None:
            animals = animals.filter(tipo=tipo)

        sort_list = ["estado"]
        if sort:
            sort_list.append(sort)

        animals = animals.order_by(*sort_list)
        return animals

    def get_estado_display(self):
        estado = self.get_estado()
        for _estado, display in settings.ANIMAL_ESTADO_CHOICES:
            if estado == _estado:
                return display

    def get_estado_badge(self):

        estado = self.get_estado()
        if estado == "D":
            return "success"
        elif estado == "R":
            return "primary"
        elif estado == "A":
            return "info"
        elif self.estado == "E":
            return "secondary"

    def get_estado(self):

        return self.estado

    def esta_reservado(self):

        return self.get_estado() == "R"

    def esta_adoptado(self):

        return self.get_estado() == "A"

    def set_estado(self, estado):

        if estado == "A" and self.fecha_adopcion is None:
            self.fecha_adopcion = timezone.now()

        self.estado = estado

    def get_adoption_url(self):

        if self.custom_link:
            return self.custom_link

        if self.tipo == "P":
            return "/pre-adopcion/perros/?id={}".format(self.id)

        return "/pre-adopcion/?id={}".format(self.id)

    def get_slug(self):
        """El nombre como va en la URL de la ficha. Es decorativo: la ficha se busca por id."""

        return slugify(self.nombre or "")[:60].strip("-")

    def get_ficha_url(self):
        """La página pública del animal (views/ficha.py), la que se comparte."""

        slug = self.get_slug()
        if slug:
            return "/adoptar/{}-{}/".format(self.id, slug)

        #un nombre sin letras ni números ("🐱") no deja nada para la URL
        return "/adoptar/{}/".format(self.id)

    def get_images(self):

        #el desempate por id importa: posicion no se escribe en ningún lado, así que sin
        #él quedan todas en NULL y el orden lo elige la base. En el carrusel de Instagram
        #eso significa que la foto de portada puede cambiar entre una corrida y la otra.
        return self.animalimage_set.order_by(F("posicion").asc(nulls_last=True), "id")

    def __str__(self):

        return self.nombre


class AnimalImage(BaseEntity):

    animal = models.ForeignKey("Animal", null=True, blank=True, on_delete=models.SET_NULL)
    image = models.ImageField(upload_to=ruta_de_imagen)
    posicion = models.PositiveIntegerField(null=True, blank=True)

    image_for_instagram = models.ImageField(upload_to=ruta_de_imagen, null=True, blank=True)
    image_layout = models.BooleanField(default=True)
    image_centered = models.BooleanField(default=True)
    image_font_size = models.PositiveIntegerField(default=150)
    image_posicion_edad_sexo = models.CharField(max_length=255, null=True, blank=True)
    image_posicion_nombre = models.CharField(max_length=255, null=True, blank=True)

    #recorte cuadrado elegido para instagram, en fracciones (0 a 1) de la imagen original
    crop_x = models.FloatField(null=True, blank=True)
    crop_y = models.FloatField(null=True, blank=True)
    crop_w = models.FloatField(null=True, blank=True)
    crop_h = models.FloatField(null=True, blank=True)

    def get_crop(self):
        """Devuelve el recorte como (x, y, w, h) en fracciones, o None si no hay."""

        crop = (self.crop_x, self.crop_y, self.crop_w, self.crop_h)
        if any(value is None for value in crop):
            return None

        if self.crop_w <= 0 or self.crop_h <= 0:
            return None

        return crop

    def set_crop(self, crop):
        """Guarda el recorte. crop es (x, y, w, h) en fracciones, o None para volver al automatico."""

        if crop is None:
            self.crop_x = self.crop_y = self.crop_w = self.crop_h = None
        else:
            self.crop_x, self.crop_y, self.crop_w, self.crop_h = crop

    def get_object_position(self):
        """El object-position que centra la foto en el recorte elegido para Instagram, o None.

        Las tarjetas y la ficha muestran las fotos en un cuadrado (object-fit: cover), y sin
        esto el cuadrado era siempre el del medio: en una foto apaisada con el gato en una
        punta se veía la pared. El recorte ya es la parte que el rescatista eligió.
        """
        from catus.services.ficha import posicion_del_recorte
        from catus.utils import clean_crop

        return posicion_del_recorte(clean_crop(self.get_crop()))


class EstadoFormulario(BaseEntity):

    choices = (
        ("N", "No asignado"),
        ("P", "En proceso de contacto con el candidato"),
        ("R", "Reservado"),
        ("A", "Adoptado"),
        ("D", "Descartado"),
        ("U", "Duplicado"),
        ("T", "Transitado"),
        #BuenAdoptante calificó a la persona con 1★ o 2★: el formulario no le llega al
        #rescatista, solo lo ve el equipo (ver services/buenadoptante.py)
        ("B", "Bloqueado por BuenAdoptante"),
    )

    fecha_ingreso = models.DateTimeField(null=True, blank=True)

    estado = models.CharField(max_length=1, choices=choices, default="N")

    #cada /formularios/<hash>/ busca por acá: sin índice recorría la tabla entera. No es
    #unique porque no está verificado que no haya repetidos en producción (migración 0042)
    hash = models.CharField(max_length=255, db_index=True)

    form_entry = models.ForeignKey(FormEntry, null=True, blank=True, on_delete=models.SET_NULL)
    gato = models.ForeignKey("animal", null=True, blank=True, on_delete=models.SET_NULL)

    persona_nombre = models.CharField(max_length=255, null=True, blank=True)

    tipo_choices = (
        ("A", "Pre Adopción - Gatos"),
        ("AP", "Pre Adopción - Perros"),
        ("T", "Tránsito - Gatos"),
        ("TP", "Tránsito - Perros"),
    )
    tipo = models.CharField(max_length=2, choices=tipo_choices, default="A")

    #"Postularme a otro animal con las mismas respuestas" (services/postulacion.py): el
    #formulario que la persona completó a mano y del que salió esta copia. Las copias
    #apuntan siempre al original, nunca a otra copia.
    copiado_de = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="copias")

    #cuándo se resolvió el aviso "ya tiene familia" a quien mandó este formulario
    #(services/aviso_candidatos.py): se mandó, o se salteó para siempre (mail inválido, era
    #el formulario de quien adoptó). Vacío es que todavía no le corresponde o no se pudo.
    aviso_cierre_el = models.DateTimeField(null=True, blank=True)
    _gato = None

    def get_fecha_ingreso(self):

        if not self.fecha_ingreso:
            return ""

        return localtime(self.fecha_ingreso).strftime("%d/%m/%Y %H:%M")

    def get_persona(self):
        from catus.services.adoption import AdoptionService

        if self.persona_nombre:
            return self.persona_nombre

        persona_nombre = AdoptionService().get_form_attr(self.form_entry, "Nombre y Apellido")
        if persona_nombre:
            self.persona_nombre = persona_nombre
            self.save()

        #se muestra directo en las tablas del admin: devolver None imprime "None"
        return persona_nombre or ""

    def get_estado_badge(self):

        if self.estado == "N":
            return "secondary"
        elif self.estado == "P":
            return "info"
        elif self.estado == "A":
            return "success"
        elif self.estado == "R":
            return "primary"
        elif self.estado == "D":
            return "danger"
        elif self.estado == "T":
            return "light"
        elif self.estado == "U":
            return "warning"
        elif self.estado == "B":
            return "dark"


class CatusUser(AbstractUser):

    objects = UserManager()

    USERNAME_FIELD = 'email'
    email = models.EmailField('email', unique=True)
    REQUIRED_FIELDS = []

    title = models.CharField(max_length=500, null=True, blank=True, default="")
    description = models.TextField(null=True, blank=True, default="")
    #/<handle>/ busca por acá. Índice y no unique: hay cuentas viejas que lo comparten
    #(views/usuario.py::get_user_por_handle)
    handle = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    instagram = models.CharField(max_length=255, null=True, blank=True)
    facebook = models.CharField(max_length=255, null=True, blank=True)
    twitter = models.CharField(max_length=255, null=True, blank=True)

    banner_img = models.ImageField(upload_to=ruta_de_imagen, null=True, blank=True, default="static/defaults/banner_bg.png")
    logo_img = models.ImageField(upload_to=ruta_de_imagen, null=True, blank=True, default="static/defaults/logo.png")

    automatic_approve = models.BooleanField(default=False)
    no_preguntar_adoptado = models.BooleanField(default=False)
    animales_comentario = models.TextField(null=True, blank=True)

    _original_banner = None
    _original_logo = None

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self._original_banner = self.banner_img
        self._original_logo = self.logo_img

    def save(self, *args, **kwargs):

        from catus.services.images import ImageService

        if self.banner_img != self._original_banner:
            ImageService().resize(self.banner_img, 1500)
        if self.logo_img != self._original_logo:
            ImageService().resize(self.logo_img, 500)

        super().save(*args, **kwargs)

    def get_instagram(self):

        if not self.instagram:
            return ""

        if self.instagram.startswith("@"):
            return self.instagram
        elif self.instagram.startswith("http"):
            return self.instagram
        else:
            return "@{}".format(self.instagram)

    def get_instagram_link(self):

        return self._get_network("instagram")

    def get_facebook_link(self):

        return self._get_network("facebook")

    def get_twitter_link(self):

        return self._get_network("twitter")

    def _normalize_network_value(self, value):

        return value.replace("@", "")

    def _get_network(self, network):

        value = getattr(self, network)
        if not value:
            return ""

        if value.startswith("http"):
            return value

        if network == "facebook":
            return "https://www.facebook.com/{}".format(self._normalize_network_value(self.facebook))
        elif network == "instagram":
            return "https://www.instagram.com/{}".format(self._normalize_network_value(self.instagram))
        elif network == "twitter":
            return "https://www.twitter.com/{}".format(self._normalize_network_value(self.twitter))
        elif network == "youtube":
            return "https://www.youtube.com/{}".format(self._normalize_network_value(self.youtube))
        elif network == "twitch":
            return "https://www.twitch.com/{}".format(self._normalize_network_value(self.twitch))
        elif network == "github":
            return "https://www.github.com/{}".format(self._normalize_network_value(self.github))
        elif network == "website":
            return "http://{}".format(self.website)

    def get_handle_url(self):

        if self.handle:
            return "/{}/".format(self.handle)

        return "/usuario/{}/animales/".format(self.id)


class Contrato(BaseEntity):

    def save(self, *args, **kwargs):

        if not self.contrato_fecha and self.adoptante is not None:
            self.contrato_fecha = timezone.now()

        return super(Contrato, self).save(*args, **kwargs)

    def get_tipo(self):

        return self.gato.tipo if self.gato is not None else "G"

    adoptante = models.ForeignKey("ContratoPersona", blank=True, null=True, on_delete=models.SET_NULL)
    gato = models.ForeignKey("Animal", blank=True, null=True, on_delete=models.SET_NULL)
    estado_formulario = models.ForeignKey("EstadoFormulario", blank=True, null=True, on_delete=models.SET_NULL)

    gato_nombre = models.CharField(max_length=255, null=True, blank=True)
    gato_sexo = models.CharField(max_length=1, default="D", choices=(("M", "Macho"), ("H", "Hembra"), ("A", "Macho y Hembra"), ("D", "Desconocido")))
    gato_color = models.CharField(max_length=255, null=True, blank=True)
    gato_fecha_nacimiento = models.DateField(null=True, blank=True)
    gato_edad = models.CharField(max_length=255, null=True, blank=True)

    gato_vacunacion_antirabica = models.BooleanField(default=False)
    gato_vacunacion_antirabica_fecha = models.DateField(null=True, blank=True)
    gato_vacunacion_antirabica_notas = models.TextField(null=True, blank=True)

    gato_vacunacion_triple_1_dosis = models.BooleanField(default=False)
    gato_vacunacion_triple_1_dosis_fecha = models.DateField(null=True, blank=True)
    gato_vacunacion_triple_1_dosis_notas = models.TextField(null=True, blank=True)

    gato_vacunacion_triple_2_dosis = models.BooleanField(default=False)
    gato_vacunacion_triple_2_dosis_fecha = models.DateField(null=True, blank=True)
    gato_vacunacion_triple_2_dosis_notas = models.TextField(null=True, blank=True)

    #PERROS
    perro_vacunacion_quintuple_1_dosis = models.BooleanField(default=False)
    perro_vacunacion_quintuple_1_dosis_fecha = models.DateField(null=True, blank=True)
    perro_vacunacion_quintuple_1_dosis_notas = models.TextField(null=True, blank=True)

    perro_vacunacion_quintuple_2_dosis = models.BooleanField(default=False)
    perro_vacunacion_quintuple_2_dosis_fecha = models.DateField(null=True, blank=True)
    perro_vacunacion_quintuple_2_dosis_notas = models.TextField(null=True, blank=True)

    perro_vacunacion_sextuple_1_dosis = models.BooleanField(default=False)
    perro_vacunacion_sextuple_1_dosis_fecha = models.DateField(null=True, blank=True)
    perro_vacunacion_sextuple_1_dosis_notas = models.TextField(null=True, blank=True)

    #ENDPERROS

    gato_castrado = models.BooleanField(default=False)
    gato_castrado_fecha = models.DateField(null=True, blank=True)
    gato_castracion_fecha_futura = models.DateField(null=True, blank=True)
    gato_castrado_notas = models.TextField(null=True, blank=True)

    gato_desparasitado = models.BooleanField(default=False)
    gato_desparasitado_fecha = models.DateField(null=True, blank=True)
    gato_desparasitado_2 = models.BooleanField(default=False)
    gato_desparasitado_fecha_2 = models.DateField(null=True, blank=True)
    gato_desparasitado_producto = models.CharField(max_length=255, null=True, blank=True)
    gato_desparasitado_notas = models.TextField(null=True, blank=True)

    gato_pipeta_antipulgas = models.BooleanField(default=False)
    gato_pipeta_antipulgas_fecha = models.DateField(null=True, blank=True)
    gato_pipeta_antipulgas_producto = models.CharField(max_length=255, null=True, blank=True)
    gato_pipeta_antipulgas_notas = models.TextField(null=True, blank=True)

    gato_alimento = models.CharField(max_length=255, null=True, blank=True)

    gato_cuidados_especiales = models.TextField(null=True, blank=True)

    contrato_fecha = models.DateField(null=True, blank=True)
    contrato_aceptado = models.BooleanField(default=False)

    miembro_adopcion_nombre = models.CharField(max_length=255, null=True, blank=True)
    #cada /contrato/<hash>/ busca por acá (migración 0042, ver EstadoFormulario.hash)
    hash = models.CharField(max_length=255, db_index=True)

    email_enviado = models.BooleanField(default=False)


class ContratoPersona(BaseEntity):

    persona_nombre = models.CharField(max_length=255, null=True, blank=True)
    persona_dni = models.CharField(max_length=255, null=True, blank=True)
    persona_fecha_nacimiento = models.DateField(null=True, blank=True)
    persona_ocupacion = models.CharField(max_length=255, null=True, blank=True)
    persona_email = models.CharField(max_length=255, null=True, blank=True)
    persona_celular = models.CharField(max_length=255, null=True, blank=True)
    persona_direccion = models.CharField(max_length=255, null=True, blank=True)
    persona_localidad = models.CharField(max_length=255, null=True, blank=True)
    persona_instagram = models.CharField(max_length=255, null=True, blank=True)
    persona_facebook = models.CharField(max_length=255, null=True, blank=True)


class FacebookAccount(BaseEntity):

    username = models.CharField(max_length=255, null=True, blank=True)
    bio = models.CharField(max_length=255, null=True, blank=True)
    website = models.CharField(max_length=255, null=True, blank=True)
    profile_picture = models.CharField(max_length=500, null=True, blank=True)
    full_name = models.CharField(max_length=255, null=True, blank=True)
    remote_id = models.CharField(max_length=255, null=True, blank=True)

    #el de la página (views/facebook.py): hoy mide ~210, y Facebook ya los alargó antes
    facebook_token = models.CharField(max_length=1000, null=True, blank=True)
    facebook_token_expire_at = models.DateTimeField(null=True, blank=True)
    business_account_id = models.CharField(max_length=255, null=True, blank=True)
    instagram_account_id = models.CharField(max_length=255, null=True, blank=True)


class ChatGTPResponse(BaseEntity):

    ig_url_for_chatgpt = models.CharField(max_length=255, null=True, blank=True)
    chatgpt_response = models.TextField(null=True, blank=True)

    #quién pidió leer el post. Cada pedido cuesta una llamada paga y el registro es
    #abierto, así que hay que poder contar cuántos hizo cada persona en el día.
    pedido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)


class RevisionIALlamada(BaseEntity):
    """Una llamada paga a la revisión automática de publicaciones. Existe sólo para
    contarlas y poder cortar el cupo diario de cada persona.

    Va en una tabla propia y no en ChatGTPResponse porque ese cupo es otro: lo cuenta
    /animal/pulldatafromig/ sobre sus propias filas, y meter acá las revisiones le
    comería el cupo a la lectura de posts (y al revés) sin que se note.

    El contador vivía en django.core.cache, pero el proyecto no configura CACHES: el
    backend real es LocMemCache, por proceso y en memoria. Con varios workers de
    gunicorn el tope real era MAX_POR_DIA por worker, y cada deploy lo ponía en cero.
    El registro es abierto: esto es lo único que separa a un refugio chico de una
    factura de OpenAI.
    """

    #quién gastó la llamada. La fecha es created_at, que ya pone BaseEntity.
    pedido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        #el alta del animal espera la revisión de forma sincrónica: el conteo del día
        #se hace por este índice y no barriendo las llamadas de toda la historia.
        #indexes y no index_together, que Django 5.1 sacó (0035 renombra el que creó 0033)
        indexes = [models.Index(fields=["pedido_por", "created_at"], name="catus_revia_pedido_fecha_idx")]


class ActividadBuenAdoptante(BaseEntity):
    """Lo que se le manda a BuenAdoptante (buenadoptante.org), el registro de adoptantes
    que comparten los rescates: una solicitud por cada formulario de pre-adopción y una
    adopción cuando se concreta. Ver catus/services/buenadoptante.py.

    Cada fila es un envío con su `external_id`, que BuenAdoptante usa para no registrar
    dos veces lo mismo: un reintento con el mismo id devuelve la respuesta original. Si
    BuenAdoptante no contesta, la fila queda pendiente ("P") y la manda el cron
    enviar_buenadoptante. Lo que devolvió (calificación, marcas, alertas, perfil) queda
    acá para mostrárselo al rescatista.
    """

    TIPOS = (
        ("adoption_request", "Solicitud de adopción"),
        ("adoption", "Adopción"),
    )

    ESTADOS = (
        ("P", "Pendiente"),
        ("OK", "Enviada"),
        ("E", "Rechazada"),
    )

    estado_formulario = models.ForeignKey("EstadoFormulario", null=True, blank=True, on_delete=models.SET_NULL)
    animal = models.ForeignKey("Animal", null=True, blank=True, on_delete=models.SET_NULL)

    tipo = models.CharField(max_length=20, choices=TIPOS)
    external_id = models.CharField(max_length=100, unique=True)
    estado = models.CharField(max_length=2, choices=ESTADOS, default="P")

    intentos = models.PositiveIntegerField(default=0)
    ultimo_intento = models.DateTimeField(null=True, blank=True)
    #el motivo del último fallo, para el equipo (sin datos de la persona)
    error = models.CharField(max_length=255, null=True, blank=True)

    #lo que contestó BuenAdoptante
    match = models.CharField(max_length=20, null=True, blank=True)
    #risk.worstRating.ratingLevel: la peor calificación de todos los perfiles que
    #coincidieron (0 sin calificar, 1 peligroso ... 5 excelente)
    nivel = models.PositiveSmallIntegerField(null=True, blank=True)
    marcas = models.TextField(null=True, blank=True)
    alertas = models.TextField(null=True, blank=True)
    perfil_url = models.CharField(max_length=255, null=True, blank=True)
    activity_id = models.CharField(max_length=64, null=True, blank=True)

    #el formulario se frenó por esta respuesta
    bloqueo = models.BooleanField(default=False)
    #a un formulario que ya había llegado, el reintento le encontró 1★ o 2★: se avisó
    avisado = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["estado", "ultimo_intento"], name="catus_ba_estado_intento_idx")]

    def get_marcas(self):
        try:
            return json.loads(self.marcas or "[]")
        except ValueError:
            return []

    def get_alertas(self):
        try:
            return json.loads(self.alertas or "[]")
        except ValueError:
            return []


class PasoFormulario(models.Model):
    """Cuántas veces por día se llegó a cada paso del formulario de pre-adopción.

    Es el embudo (abrir, aceptar los requisitos, empezar, querer enviar con faltantes,
    enviar) para saber dónde se queda la gente: con 38 preguntas obligatorias en el de
    gatos, no había ningún dato. Son contadores agregados, sin cookies ni nada de nadie
    (services/embudo.py).
    """

    PASOS = (
        ("abrio", "Abrió el formulario"),
        ("requisitos", "Aceptó los requisitos"),
        ("empezo", "Empezó a contestar"),
        ("faltantes", "Quiso enviar con respuestas sin contestar"),
        ("intento", "Lo envió desde el navegador"),
        ("enviado", "Llegó y se guardó"),
        ("frenado", "Lo frenó BuenAdoptante"),
        ("rechazado", "El servidor lo rechazó"),
    )

    fecha = models.DateField()
    especie = models.CharField(max_length=1, choices=(("G", "Gatos"), ("P", "Perros")))
    paso = models.CharField(max_length=12, choices=PASOS)
    n = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("fecha", "especie", "paso")
