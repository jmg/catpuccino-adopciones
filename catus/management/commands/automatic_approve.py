from django.core.management.base import BaseCommand
from catus.models import CatusUser, Animal

class Command(BaseCommand):

    def handle(self, *args, **options):

        users = CatusUser.objects.filter(automatic_approve=False)

        for user in users:

            count = Animal.objects.filter(cargado_por=user, aprobado=True).count()

            print ("{} tiene {} aprobados".format(user.get_instagram(), count))

            if count > 0 and not user.automatic_approve:
                user.automatic_approve = True
                user.save()
