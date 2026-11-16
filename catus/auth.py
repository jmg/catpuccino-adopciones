import hashlib
import unicodedata

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.hashers import check_password

from catus.forms import PasswordResetForm
from catus.models import CatusUser
from catus.services import throttle

class SettingsBackend:

    def authenticate(self, request, email=None, password=None):

        pwd_valid = password == settings.ADMIN_PASSWORD
        if pwd_valid:
            user = CatusUser.objects.get(email=email)
            return user

        return None

    def get_user(self, user_id):
        try:
            return CatusUser.objects.get(pk=user_id)
        except CatusUser.DoesNotExist:
            return None


#La página de "me olvidé la contraseña" le manda un mail a la dirección que se escriba, sin
#cuenta ni captcha: sin tope, alcanzaba un bucle para llenarle la casilla de mails de
#reseteo a cualquier rescatista. Con memcached caído no se cuenta nada y la página sigue
#andando (catus/services/throttle.py).
RESET_MAX_POR_HORA = 10           # por conexión
RESET_MAX_POR_DIA_POR_MAIL = 3    # por dirección, venga de donde venga
RESET_DEMASIADOS_DESDE_LA_CONEXION = "Pediste demasiados cambios de contraseña desde tu conexión. Esperá una hora y probá de nuevo."
RESET_DEMASIADOS_A_ESE_MAIL = ("Ya mandamos varios mails para cambiar la contraseña a esa dirección. Usá el link del último "
                               "(revisá también la carpeta de spam) o probá de nuevo mañana.")


def casilla(email):
    """La dirección como la compara PasswordResetForm (NFKC y sin mayúsculas), hasheada:
    lo que queda en memcached no es el mail de nadie."""

    normal = unicodedata.normalize("NFKC", (email or "").strip()).casefold()
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()


class PasswordResetView(auth_views.PasswordResetView):
    """La de Django con el formulario propio (catus.forms.PasswordResetForm) y un tope.

    Se cuenta toda dirección pedida, tenga cuenta o no: si solo se contaran las que existen,
    el mensaje del tope diría cuáles tienen cuenta. Está acá y no en catus/views/ porque
    allá django-conventions la registraría en otra URL; la conecta catus_project/urls.py.
    """

    form_class = PasswordResetForm
    # The text part used to be the HTML template too, tags and all.
    email_template_name = "registration/password_reset_email.txt"
    html_email_template_name = "registration/password_reset_email.html"

    def form_valid(self, form):

        bloqueo = self.limite(form.cleaned_data["email"])
        if bloqueo:
            form.add_error(None, bloqueo)
            return self.form_invalid(form)

        return super().form_valid(form)

    def limite(self, email):
        """Por qué este pedido no se manda, o None."""

        conexion = throttle.client_ip(self.request)
        if conexion and throttle.hit("password-reset", conexion, 60 * 60) > RESET_MAX_POR_HORA:
            return RESET_DEMASIADOS_DESDE_LA_CONEXION

        if throttle.hit("password-reset-mail", casilla(email), 24 * 60 * 60) > RESET_MAX_POR_DIA_POR_MAIL:
            return RESET_DEMASIADOS_A_ESE_MAIL

        return None
