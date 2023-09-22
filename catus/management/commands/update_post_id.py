from django.core.management.base import BaseCommand
from catus.models import *
from catus.services.facebook import FacebookApiService
from catus.services.base import BaseService
from catus.utils import clean_html
from django.db.models import Q


class Command(BaseCommand):

    def handle(self, *args, **options):

        account = FacebookAccount.objects.all().first()

        #get get post id for animals without post id

        animals = Animal.objects.filter(
            instagram_publicado=True,
            instagram_post_id__isnull=True,
        ).order_by("id")

        posts = FacebookApiService.get_all_posts(account, limit=50)

        for animal in animals:
            FacebookApiService.get_post_for(posts, animal)