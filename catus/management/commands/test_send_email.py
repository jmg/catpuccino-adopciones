from django.core.management.base import BaseCommand
from catus.services.mail import MailService
from catus.models import Animal


class Command(BaseCommand):

    def handle(self, *args, **options):

        animal = Animal.objects.get(id=1)
        MailService().send_mail_aprobacion(animal)