from django.core.management.base import BaseCommand
from catus.services.facebook import FacebookApiService
from catus.models import FacebookAccount


class Command(BaseCommand):

    def handle(self, *args, **options):

        account = FacebookAccount.objects.get(id=1)
        FacebookApiService.send_message(account, "prueba")