from django.core.management.base import BaseCommand
from catus.models import *
from catus.services.facebook import FacebookApiService
from catus.services.base import BaseService
from catus.utils import clean_html
from django.db.models import Q


class Command(BaseCommand):

    def animales_a_comentar(self):
        """Los que ya se publicaron y todavía no tienen el comentario de adoptado.

        Solo los adoptados: el comentario dice "Ya fue adoptado" y acá también entraban
        los reservados, que todavía pueden no adoptarse. Y como después se guarda
        instagram_comment_id, el comentario equivocado ya no se volvía a corregir.
        Un reservado que después se adopte lo toma una corrida posterior.
        """

        return Animal.objects.filter(
            estado="A",
            instagram_publicado=True,
            instagram_post_id__isnull=False,
            instagram_comment_id__isnull=True,
        ).order_by("-id")

    def handle(self, *args, **options):

        account = FacebookAccount.objects.all().first()

        #update the status in IG

        for animal in self.animales_a_comentar():

            try:
                FacebookApiService.update_adoptado_comment(account, animal)
            except Exception as e:
                print ("Error updating animal %s: %s" % (animal.nombre, e))
