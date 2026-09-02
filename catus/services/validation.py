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

        return re.sub(re.compile("[^0-9a-zA-Z_]"), "", handle or "")

    def esta_libre(self, handle, user):

        query_set = CatusUser.objects

        if user is not None and user.pk:
            query_set = query_set.exclude(pk=user.pk)

        return not query_set.filter(handle=handle).exists()

    def build_handle(self, propuesta, user):
        """Devuelve un handle válido y libre a partir de lo que puso la persona.

        Antes se limpiaban los caracteres inválidos O se agregaba un "_" si estaba
        tomado, pero nunca las dos cosas, y no se volvía a chequear: dos personas
        podían terminar con el mismo handle y /<handle>/ devolvía 500 para las dos.
        """

        base = self.clean_handle(propuesta)
        if not base:
            return None

        handle = base
        sufijo = 1

        while not self.esta_libre(handle, user):
            sufijo += 1
            handle = "{}_{}".format(base, sufijo)

        return handle
