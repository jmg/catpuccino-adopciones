from datetime import datetime, timedelta
from socket import IP_DROP_MEMBERSHIP
from catus.models import *
from catus.services.facebook import FacebookApiService
from .base import BaseView


class LoginView(BaseView):

    def post(self, *args, **kwargs):

        token = self.request.POST.get("access_token")

        account_names, instagram_account_names, accounts_data = FacebookApiService(token=token).get_instagram_accounts()

        self.request.session["accounts_data"] = accounts_data
        for account_id, account in accounts_data.items():
            facebook_account = FacebookAccount.objects.all().first()
            if not facebook_account:
                facebook_account = FacebookAccount()

            facebook_account.username = account["username"]
            facebook_account.bio = account["username"]
            facebook_account.website = account["website"]
            facebook_account.profile_picture = account["profile_picture"]
            facebook_account.full_name = account["full_name"]
            facebook_account.remote_id = account_id
            facebook_account.business_account_id = account["remote_id"]

            access_token, expires_in = FacebookApiService.get_long_lived_token(token)
            facebook_token_expire_at = datetime.now() + timedelta(seconds=expires_in)

            facebook_account.facebook_token = access_token
            facebook_account.facebook_token_expire_at = facebook_token_expire_at
            facebook_account.save()

        return self.response("Connected with {}!".format(instagram_account_names[0][1]))