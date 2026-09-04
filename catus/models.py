from django.db import models
from forms_builder.forms.models import FormEntry
from django.contrib.auth.models import AbstractUser
from catus.managers import UserManager
from django.utils.timezone import localtime
from django.utils import timezone
import random
from django.db.models import F

import os
import requests
from django.conf import settings


class BaseEntity(models.Model):

    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    def __init__(self, *args, **kwargs):

        now = timezone.now()
        kwargs.update(created_at=kwargs.get("created_at",now), updated_at=kwargs.get("updated_at",now))
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
    instagram_intentos = models.PositiveIntegerField(default=0)
    instagram_ultimo_intento = models.DateTimeField(null=True, blank=True)
    instagram_error = models.TextField(null=True, blank=True)

    mail_preguntar_adopcion_enviado = models.BooleanField(default=False)

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
        max_length=2, choices=REVISION_IA_CHOICES, default=REVISION_PENDIENTE,
    )
    revision_ia_motivo = models.TextField(null=True, blank=True)
    revision_ia_fecha = models.DateTimeField(null=True, blank=True)

    def necesita_revision_humana(self):

        return self.revision_ia_estado == self.REVISION_REVISAR

    def get_revision_ia_badge(self):

        return {
            self.REVISION_OK: "success",
            self.REVISION_REVISAR: "danger",
            self.REVISION_ERROR: "secondary",
        }.get(self.revision_ia_estado, "light")

    def save(self, *args, **kwargs):
        from catus.services.cache import CacheService

        if not self.fecha_ingreso:
            self.fecha_ingreso = timezone.now()

        result = super(Animal, self).save(*args, **kwargs)
        #CacheService().set("animals-for-adoption", self.get_all_for_adoption(destacado=True, sort="-fecha_ingreso"))
        return result

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

    def get_images(self):

        #el desempate por id importa: posicion no se escribe en ningún lado, así que sin
        #él quedan todas en NULL y el orden lo elige la base. En el carrusel de Instagram
        #eso significa que la foto de portada puede cambiar entre una corrida y la otra.
        return self.animalimage_set.order_by(F("posicion").asc(nulls_last=True), "id")

    def __str__(self):

        return self.nombre


class AnimalImage(BaseEntity):

    animal = models.ForeignKey("Animal", null=True, blank=True, on_delete=models.SET_NULL)
    image = models.ImageField(upload_to='gallery')
    posicion = models.PositiveIntegerField(null=True, blank=True)

    image_for_instagram = models.ImageField(upload_to='gallery', null=True, blank=True)
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


class EstadoFormulario(BaseEntity):

    choices = (
        ("N", "No asignado"),
        ("P", "En proceso de contacto con el candidato"),
        ("R", "Reservado"),
        ("A", "Adoptado"),
        ("D", "Descartado"),
        ("U", "Duplicado"),
        ("T", "Transitado"),
    )

    fecha_ingreso = models.DateTimeField(null=True, blank=True)

    estado = models.CharField(max_length=1, choices=choices, default="N")

    hash = models.CharField(max_length=255)

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


class CatusUser(AbstractUser):

    objects = UserManager()

    USERNAME_FIELD = 'email'
    email = models.EmailField('email', unique=True)
    REQUIRED_FIELDS = []

    title = models.CharField(max_length=500, null=True, blank=True, default="")
    description = models.TextField(null=True, blank=True, default="")
    handle = models.CharField(max_length=255, null=True, blank=True)

    instagram = models.CharField(max_length=255, null=True, blank=True)
    facebook = models.CharField(max_length=255, null=True, blank=True)
    twitter = models.CharField(max_length=255, null=True, blank=True)

    banner_img = models.ImageField(upload_to='gallery', null=True, blank=True, default="static/defaults/banner_bg.png")
    logo_img = models.ImageField(upload_to='gallery', null=True, blank=True, default="static/defaults/logo.png")

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
    hash = models.CharField(max_length=255)

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

    facebook_token = models.CharField(max_length=255, null=True, blank=True)
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
        #se hace por este índice y no barriendo las llamadas de toda la historia
        index_together = [("pedido_por", "created_at")]
