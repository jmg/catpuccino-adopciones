from django.conf import settings
from django.contrib.auth.hashers import check_password

from catus.models import CatusUser

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