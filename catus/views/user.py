from django.conf import settings
from django.shortcuts import render, redirect
from catus.forms import SignupForm
from catus.models import CatusUser

from catus.services import throttle
from catus.services.validation import ValidationService
from django.conf import settings
from django.contrib.auth import login, authenticate

from catus.views.base import BaseView

#El registro es abierto, y cada cuenta trae su propio cupo de revisiones con IA y de
#lecturas de Instagram: abrir cuentas en cantidad es la forma de saltarse los topes por
#persona. Nadie abre más de un par de cuentas por día desde la misma conexión. Los
#intentos por hora frenan además a quien prueba mails de a uno para ver cuáles ya tienen
#cuenta. Con memcached caído no se cuenta nada y el registro sigue andando.
REGISTRO_MAX_INTENTOS_POR_HORA = 20
REGISTRO_MAX_CUENTAS_POR_DIA = 5
REGISTRO_DEMASIADOS_INTENTOS = "Hubo demasiados intentos de registro desde tu conexión. Esperá una hora y probá de nuevo."
REGISTRO_DEMASIADAS_CUENTAS = "Hoy ya se crearon varias cuentas desde tu conexión. Probá de nuevo mañana."


class RegisterView(BaseView):

    url = r"^accounts/register/$"
    template_name = "registration/register.html"

    def limite(self, conexion):
        """Por qué este registro no se procesa, o None."""

        if not conexion:
            return None

        if throttle.hit("register", conexion, 60 * 60) > REGISTRO_MAX_INTENTOS_POR_HORA:
            return REGISTRO_DEMASIADOS_INTENTOS

        if throttle.count("register-account", conexion) >= REGISTRO_MAX_CUENTAS_POR_DIA:
            return REGISTRO_DEMASIADAS_CUENTAS

        return None

    def post(self, *a, **k):

        if self.request.method == 'POST':

            form = SignupForm(self.request.POST)
            conexion = throttle.client_ip(self.request)
            bloqueo = self.limite(conexion)

            if bloqueo:
                form.add_error(None, bloqueo)

            elif form.is_valid():

                user = form.save(commit=False)
                user.username = form.cleaned_data['email']

                instagram = form.cleaned_data.get('instagram')
                if instagram:

                    handle = ValidationService().build_handle(instagram, user)
                    if handle:
                        user.title = handle
                        user.handle = handle

                user.save()

                if conexion:
                    throttle.hit("register-account", conexion, 24 * 60 * 60)

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