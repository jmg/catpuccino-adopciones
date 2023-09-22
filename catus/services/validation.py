import re
from socket import IP_DROP_MEMBERSHIP

from catus.models import Animal, CatusUser


class ValidationService():

    HANDLE_REGEX = "^[0-9a-zA-Z_]+$"

    def check_handle(self, handle, user):

        pattern = re.compile(self.HANDLE_REGEX)
        if not pattern.search(handle):
            raise Exception("chars")

        query_set = CatusUser.objects

        if user.is_authenticated:
            query_set = query_set.exclude(id=user.id)

        if query_set.filter(handle=handle).exists():
            raise Exception("handle")

    def clean_handle(self, handle):

        return re.sub(re.compile("[^0-9a-zA-Z_]"), "", handle)
