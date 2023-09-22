from catus.utils import send_html_email, rreplace
from catus.services.base import BaseService
from catus.models import Animal
from django.conf import settings
from datetime import datetime, timedelta


class MailService(BaseService):

    def send_new_animal_mail(self, animal):

        if settings.ENV == "LOCAL":
            return

        subject = "Catpuccino Adopciones - Nuevo Ingreso"
        content = self.render("email/new_animal.html", {"animal": animal, "settings": settings})

        send_html_email(subject, content, settings.SEND_MAIL, ["catpuccino.ok@gmail.com"])

    def send_mail_aprobacion(self, animal):

        if settings.ENV == "LOCAL":
            return

        subject = "Catpuccino Adopciones - {} ya está publicado!".format(animal.nombre.capitalize())
        content = self.render("email/new_animal_aprobacion.html", {"animal": animal, "settings": settings })

        send_html_email(subject, content, settings.SEND_MAIL, animal.cargado_por.email)

    def send_mail_pregunta(self, user, content):

        days_ago = datetime.now() - timedelta(days=30)

        animals = Animal.objects.filter(cargado_por=user, estado="D", aprobado=True, created_at__lte=days_ago)
        animals_names = ", ".join([animal.nombre for animal in animals])
        animals_names = rreplace(animals_names, ", ", " y ", 1)

        subject = "Catpuccino Adopciones - ¿Sigue{} {} en adopción?".format("n" if len(animals) > 1 else "", animals_names)

        animals.update(mail_preguntar_adopcion_enviado=True)

        send_html_email(subject, content, settings.SEND_MAIL, user.email)
