from django.core.management.base import BaseCommand
from catus.models import *
from catus.services.facebook import FacebookApiService
from catus.services.base import BaseService
from catus.utils import clean_html
from django.db.models import Q


class Command(BaseCommand):

    def handle(self, *args, **options):

        account = FacebookAccount.objects.all().first()

        #update the status in IG

        animals = Animal.objects.filter(
            Q(estado="A") | Q(estado="R"),
            instagram_publicado=True,
            instagram_post_id__isnull=False,
            instagram_comment_id__isnull=True,
        ).order_by("-id")

        for animal in animals:

            try:
                FacebookApiService.update_adoptado_comment(account, animal)
            except Exception as e:
                print ("Error updating animal %s: %s" % (animal.nombre, e))
