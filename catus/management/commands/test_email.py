from django.core.management.base import BaseCommand, CommandError
from catus.models import *
from catus.utils import send_html_email
from catus.services.base import BaseService


class Command(BaseCommand):

    def handle(self, *args, **options):

        animal = list(Animal.objects.filter(cargado_por__email="jmg.utn@gmail.com"))[-1]
        email_context = {
            "animal": animal,
            "tipo": "preadoption",
        }

        subject = "Catpuccino Adopciones - Formulario Recibido"
        content = BaseService().render("email/received.html", email_context)

        send_html_email(subject, content, settings.SEND_MAIL, "jmg.utn@gmail.com")