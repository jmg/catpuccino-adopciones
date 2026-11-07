from catus.models import *
from catus.services.facebook import FacebookApiService
from .base import BaseView, SuperuserRequiredMixin


class LoginView(SuperuserRequiredMixin, BaseView):
    """Vincula la cuenta de Instagram desde la que publica el sitio.

    Pisa el token y la cuenta, así que es solo del equipo: sin el chequeo cualquiera
    podía apuntar las publicaciones del sitio a otra cuenta.
    """

    def post(self, *args, **kwargs):

        token = self.request.POST.get("access_token")

        account_names, instagram_account_names, accounts_data = FacebookApiService(token=token).get_instagram_accounts()

        self.request.session["accounts_data"] = accounts_data

        #Solo sirven las páginas con un Instagram profesional vinculado. Antes se guardaba
        #la última página que devolvía Facebook, tuviera Instagram o no: con dos páginas el
        #sitio podía quedar sin cuenta para publicar, o publicando en la equivocada.
        con_instagram = [(page_id, data) for page_id, data in accounts_data.items() if data.get("remote_id")]

        if not con_instagram:
            return self.response("Ninguna de las páginas que elegiste tiene un Instagram profesional vinculado. Volvé a conectar y elegí la de Catpuccino.")

        facebook_account = FacebookAccount.objects.all().first() or FacebookAccount()

        #al volver a conectar se queda la misma cuenta, aunque Facebook devuelva otras
        page_id, account = next(
            ((page_id, data) for page_id, data in con_instagram if data["remote_id"] == facebook_account.business_account_id),
            con_instagram[0],
        )

        user_token, expires_in = FacebookApiService.get_long_lived_token(token)

        facebook_account.username = account["username"]
        facebook_account.bio = account["username"]
        facebook_account.website = account["website"]
        facebook_account.profile_picture = account["profile_picture"]
        facebook_account.full_name = account["full_name"]
        facebook_account.remote_id = page_id
        facebook_account.business_account_id = account["remote_id"]

        #Se guarda el token de la página y no el del usuario: el de usuario vence a los 60
        #días, y así se cortó la publicación en enero de 2026. El de la página no vence, y
        #refresh_token lo revisa todos los días y avisa si deja de andar.
        facebook_account.facebook_token = FacebookApiService.get_page_token(user_token, page_id)
        facebook_account.facebook_token_expire_at = None
        facebook_account.save()

        return self.response("Connected with {}!".format(account["full_name"]))
