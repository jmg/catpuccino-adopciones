from django.core.management.base import BaseCommand
from catus.models import *
from catus.services.facebook import FacebookApiService
from catus.services.base import BaseService
from catus.utils import clean_html


class Command(BaseCommand):

    def handle(self, *args, **options):

        MAX_PUBLICATIONS = 10

        animals = Animal.objects.filter(
            instagram_listo_para_publicar=True,
            instagram_publicado=False,
        ).order_by("id")[:MAX_PUBLICATIONS]

        for animal in animals:

            print ("publicando ", animal.nombre)

            ig_text = BaseService().render("tools/generartexto.txt", {"animal": animal})
            ig_text = clean_html(ig_text)

            response = FacebookApiService.publish(animal, ig_text)
            print (response)

