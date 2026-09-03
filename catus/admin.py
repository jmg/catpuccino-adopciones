import logging

from django.contrib import admin
from django.urls import reverse, re_path

from catus.models import Animal, AnimalImage, Contrato, ContratoPersona, EstadoFormulario, CatusUser, FacebookAccount, ChatGTPResponse
from forms_builder.forms.admin import FormAdmin
from forms_builder.forms.models import Form, FormEntry, FieldEntry
from django.contrib.auth.models import Group, User
from django.contrib.sites.models import Site

from django.utils.safestring import mark_safe
from catus.services.mail import MailService

logger = logging.getLogger(__name__)


class AnimalImageAdmin(admin.StackedInline):

    model = AnimalImage


class AnimalAdmin(admin.ModelAdmin):

    list_display = ["nombre", "usuario", "sexo", "edad", "zona", "fecha_ingreso", "fecha_adopcion", "estado", "instagram_listo_para_publicar", "instagram_publicado", "aprobado", "ig_link", "utilidades"]
    list_editable = ("estado", "instagram_listo_para_publicar", "instagram_publicado", "aprobado")
    search_fields = ["nombre"]
    inlines = [AnimalImageAdmin]
    ordering = ("-fecha_ingreso",)
    actions = ['aprobar_animales']

    def usuario(self, obj):

        return "{} ({})".format(obj.cargado_por.email if obj.cargado_por else "", obj.cargado_por.get_instagram() if obj.cargado_por else "")

    def ig_link(self, obj):

        if not obj.instagram_media_url:
            return ""

        return mark_safe("<a target='_blank' href='{}'>IG link</a>".format(obj.instagram_media_url))

    def utilidades(self, obj):

        links = "<a target='_blank' href='/tools/generarimagen/{}/'>Generar Imagen</a>".format(obj.id)

        #al dar de baja a un rescatista sus animales quedan con cargado_por en NULL
        #(SET_NULL). Este link estaba fuera del if y tumbaba el listado entero.
        if obj.cargado_por is not None:
            links += " | <a target='_blank' href='/user/settingslogin/?user_id={}'>Login as user</a>".format(obj.cargado_por.id)
            links += " | <a target='_blank' href='/tools/preguntaradopcion/?user_id={}'>Preguntar Adopción</a>".format(obj.cargado_por.id)

        # Agregar enlace para aprobar animal si no está aprobado
        if not obj.aprobado:
            links += " | <a target='_blank' href='/animal/aprobar/?id={}' style='color: green; font-weight: bold;'>Aprobar Animal</a>".format(obj.id)

        return mark_safe(links)

    def aprobar_animales(self, request, queryset):
        """
        Acción personalizada para aprobar animales seleccionados
        """
        animales_aprobados = 0
        sin_aviso = 0
        mail_service = MailService()

        for animal in queryset:
            if animal.aprobado:
                continue

            animal.aprobado = True
            animal.save()
            animales_aprobados += 1

            #un problema mandando un mail no puede dejar la tanda a medio aprobar
            try:
                mail_service.send_mail_aprobacion(animal)
            except Exception:
                sin_aviso += 1
                logger.exception("No se pudo avisar de la aprobación de %s", animal.nombre)

        if animales_aprobados == 1:
            message = "1 animal fue aprobado."
        else:
            message = "{} animales fueron aprobados.".format(animales_aprobados)

        if sin_aviso:
            message += " {} quedaron sin aviso por mail (mirá el log).".format(sin_aviso)

        self.message_user(request, message)

    aprobar_animales.short_description = "Aprobar animales seleccionados"


class FormAdmin(FormAdmin):

    list_display = ("title", "utilidades")
    list_editable = ()

    def utilidades(self, obj):

        links = "<a href='/admin/forms/form/{}/entries/show/'>Ver todos los formularios</a> | <a href='/admin/forms/form/{}/entries/export/'>Exportar formularios a Excel</a>".format(obj.id, obj.id)
        return mark_safe(links)


class CatusUserAdmin(admin.ModelAdmin):

    list_display = ("email", "handle", "get_instagram", "automatic_approve", "no_preguntar_adoptado", "animal_count", "login")
    list_editable = ("automatic_approve", "no_preguntar_adoptado")

    #este es el modelo de login, y al ser un ModelAdmin común el campo password salía
    #editable como texto: lo que se escribiera ahí se guardaba tal cual, sin hashear,
    #y esa persona después no podía entrar. Se cambia con "Cambiar contraseña" del
    #propio perfil o con manage.py changepassword.
    readonly_fields = ("password", "last_login", "date_joined")

    def animal_count(self, obj):

        return Animal.objects.filter(cargado_por=obj).count()

    def get_instagram(self, obj):

        return obj.get_instagram()

    def login(self, obj):

        return mark_safe("<a target='_blank' href='/user/settingslogin/?user_id={}'>Login</a>".format(obj.id))


class ChatGTPResponseAdmin(admin.ModelAdmin):

    list_display = ("created_at", "ig_url_for_chatgpt", "chatgpt_response")
    list_editable = ()


class EstadoFormularioAdmin(admin.ModelAdmin):

    list_display = ("fecha_ingreso", "estado", "persona_nombre", "gato", "animal_cargado_por", "tipo")
    search_fields = ["persona_nombre", "gato__nombre"]

    def animal_cargado_por(self, obj):

        #al borrar un animal, los formularios de sus candidatos quedan con gato en
        #NULL (SET_NULL) y este listado dejaba de abrirse
        if obj.gato is None or obj.gato.cargado_por is None:
            return ""

        return obj.gato.cargado_por.get_instagram()


class FieldEntryAdmin(admin.ModelAdmin):

    list_display = ("entry", "field_id", "value")


#admin.site.unregister(User)
admin.site.unregister(Group)
admin.site.unregister(Form)

admin.site.register(Animal, AnimalAdmin)
admin.site.register(Form, FormAdmin)
admin.site.register(FormEntry)
admin.site.register(FieldEntry, FieldEntryAdmin)
admin.site.register(EstadoFormulario, EstadoFormularioAdmin)
admin.site.register(CatusUser, CatusUserAdmin)
admin.site.register(AnimalImage)
admin.site.register(FacebookAccount)

admin.site.register(Contrato)
admin.site.register(ContratoPersona)
admin.site.register(ChatGTPResponse, ChatGTPResponseAdmin)
