from django.conf import settings
from django.shortcuts import render, redirect
from catus.forms import SignupForm
from catus.models import CatusUser

from catus.services.validation import ValidationService
from django.conf import settings
from django.contrib.auth import login, authenticate

from catus.views.base import BaseView


class RegisterView(BaseView):

    url = r"^accounts/register/$"
    template_name = "registration/register.html"

    def post(self, *a, **k):

        if self.request.method == 'POST':

            form = SignupForm(self.request.POST)
            if form.is_valid():

                user = form.save(commit=False)
                user.username = form.cleaned_data['email']

                instagram = form.cleaned_data.get('instagram')
                if instagram:

                    handle = instagram
                    try:
                        ValidationService().check_handle(instagram, user)
                    except Exception as e:
                        if str(e) == "chars":
                            handle = ValidationService().clean_handle(instagram)
                        if str(e) == "handle":
                            handle = "{}_".format(instagram)

                    user.title = handle
                    user.handle = handle

                user.save()

                login(self.request, user, backend='django.contrib.auth.backends.ModelBackend')

                return self.redirect(settings.LOGIN_REDIRECT_URL)
        else:
            form = SignupForm()

        return self.render_to_response({'form': form, "settings": settings })

    get = post


class SettingsLoginView(BaseView):

    def get(self, *a, **k):

        if not self.request.user.is_superuser:
            return redirect('/accounts/login/')

        user = CatusUser.objects.get(id=self.request.GET.get("user_id"))

        user = authenticate(email=user.email, password=settings.ADMIN_PASSWORD)
        login(self.request, user, backend='catus.auth.SettingsBackend')

        return self.redirect(settings.LOGIN_REDIRECT_URL)