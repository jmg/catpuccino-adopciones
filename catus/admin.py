from django.contrib import admin
from django.urls import reverse, re_path

from catus.models import Animal, AnimalImage, Contrato, ContratoPersona, EstadoFormulario, CatusUser, FacebookAccount, ChatGTPResponse
from forms_builder.forms.admin import FormAdmin
from forms_builder.forms.models import Form, FormEntry, Field
from django.contrib.auth.models import Group, User
from django.contrib.sites.models import Site

from django.utils.safestring import mark_safe


class AnimalImageAdmin(admin.StackedInline):

    model = AnimalImage


class AnimalAdmin(admin.ModelAdmin):

    list_display = ["nombre", "usuario", "sexo", "edad", "zona", "fecha_ingreso", "fecha_adopcion", "estado", "instagram_listo_para_publicar", "instagram_publicado", "aprobado", "ig_link", "utilidades"]
    list_editable = ("estado", "instagram_listo_para_publicar", "instagram_publicado", "aprobado")
    search_fields = ["nombre"]
    inlines = [AnimalImageAdmin]
    ordering = ("-fecha_ingreso",)

    def usuario(self, obj):

        return "{} ({})".format(obj.cargado_por.email if obj.cargado_por else "", obj.cargado_por.get_instagram() if obj.cargado_por else "")

    def ig_link(self, obj):

        if not obj.instagram_media_url:
            return ""

        return mark_safe("<a target='_blank' href='{}'>IG link</a>".format(obj.instagram_media_url))

    def utilidades(self, obj):

        links = "<a target='_blank' href='/tools/generarimagen/{}/'>Generar Imagen</a>".format(obj.id)
        if obj.cargado_por is not None:
            links += " | <a target='_blank' href='/user/settingslogin/?user_id={}'>Login as user</a>".format(obj.cargado_por.id)

        links += " | <a target='_blank' href='/tools/preguntaradopcion/?user_id={}'>Preguntar Adopción</a>".format(obj.cargado_por.id)
        return mark_safe(links)


class FormAdmin(FormAdmin):

    list_display = ("title", "utilidades")
    list_editable = ()

    def utilidades(self, obj):

        links = "<a href='/admin/forms/form/{}/entries/show/'>Ver todos los formularios</a> | <a href='/admin/forms/form/{}/entries/export/'>Exportar formularios a Excel</a>".format(obj.id, obj.id)
        return mark_safe(links)


class CatusUserAdmin(admin.ModelAdmin):

    list_display = ("email", "handle", "get_instagram", "automatic_approve", "no_preguntar_adoptado", "animal_count", "login")
    list_editable = ("automatic_approve", "no_preguntar_adoptado")

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

        return obj.gato.cargado_por.get_instagram() if obj.gato.cargado_por else ""


#admin.site.unregister(User)
admin.site.unregister(Group)
admin.site.unregister(Form)

admin.site.register(Animal, AnimalAdmin)
admin.site.register(Form, FormAdmin)
admin.site.register(FormEntry)
admin.site.register(Field)
admin.site.register(EstadoFormulario, EstadoFormularioAdmin)
admin.site.register(CatusUser, CatusUserAdmin)
admin.site.register(AnimalImage)
admin.site.register(FacebookAccount)

admin.site.register(Contrato)
admin.site.register(ContratoPersona)
admin.site.register(ChatGTPResponse, ChatGTPResponseAdmin)
