from django.core.management.base import BaseCommand, CommandError
from catus.models import *
from catus.services.gpt import GPTService


class Command(BaseCommand):

    def handle(self, *args, **options):

        x = """{
  "nombre": "Sarabi",
  "tipo": "gato",
  "sexo": "hembra",
  "edad": "3 años",
  "descripcion": "Sarabi es una gatita muy especial y se vería muy estresada con tantas mudanzas, las cuales tiene que afrontar su actual familia. Actualmente tiene aprox 3 años, está desparasitada, castrada y sin pulgas. Es VIF y VILEF negativo!",
}"""
        data = (GPTService().parse_response(x))
        data.pop("response")
        print (data)