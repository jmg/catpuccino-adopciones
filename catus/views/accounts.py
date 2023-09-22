import re
from django.conf import settings
from catus.services.adoption import AdoptionService
from catus.services.validation import ValidationService
from catus.views.base import BaseView

from catus.models import Animal, CatusUser, EstadoFormulario
from catus.forms import AnimalImageForm, CatusUserForm, RequiredImageInlineFormset
from django.contrib.auth.mixins import LoginRequiredMixin


class ProfileView(LoginRequiredMixin, BaseView):

    def render_to_response(self, context):
        context["animals"] = self.get_animals()

        context["success"] = self.request.session.pop("animal_save_success", False) == True
        context["is_new_animal"] = self.request.session.pop("is_new_animal", False) == True
        context["is_new_animal_approved"] = self.request.session.pop("is_new_animal_approved", False) == True
        context["settings"] = settings
        context["form"] = CatusUserForm(instance=self.request.user)
        context["usuario_save_success"] = self.request.session.pop("usuario_save_success", False)
        context["usuario_save_error"] = self.request.session.pop("usuario_save_error", False)

        if self.request.user.is_superuser:
            estado_forms = EstadoFormulario.objects.all().order_by("-id")
        else:
            estado_forms = EstadoFormulario.objects.filter(gato__cargado_por=self.request.user).order_by("-id")

        context["estado_forms"] = estado_forms
        context["SSL_HOST"] = settings.SSL_HOST

        return BaseView.render_to_response(self, context)

    def get_animals(self):

        return Animal.objects.filter(cargado_por=self.request.user).order_by("-id")

    def post(self, *a, **k):

        form = CatusUserForm(self.request.POST, self.request.FILES, instance=self.request.user)

        if form.is_valid():

            form.save()
            logo_img = "/{}".format(form.instance.logo_img.name)
            banner_img = "/{}".format(form.instance.banner_img.name)

            profile_link = "/{}/".format(form.instance.handle)

            return self.json_response({"status": "success", "logo_img": logo_img, "banner_img": banner_img, "profile_link": profile_link })
        else:
            return self.json_response({"status": "failure", "errors": form.errors })


class CheckHandleView(BaseView):

    def post(self, *a, **k):

        handle = self.request.POST.get("handle")
        user = self.request.user

        try:
            ValidationService().check_handle(handle, user)
            return self.json_response({"status": "success"})
        except Exception as e:
            return self.json_response({"status": "failure", "error": str(e) })
