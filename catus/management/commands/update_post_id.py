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

        #también los que quedaron sin permalink: publish() ahora guarda el post_id apenas
        #publica y lo que puede faltar es instagram_media_url, así que filtrando sólo por
        #post_id nulo el animal al que le falta el link no entraba nunca acá
        animals = Animal.objects.filter(
            instagram_publicado=True,
        ).filter(
            Q(instagram_post_id__isnull=True) |
            Q(instagram_media_url__isnull=True) |
            Q(instagram_media_url=""),
        ).order_by("id")

        posts = FacebookApiService.get_all_posts(account, limit=50)

        for animal in animals:
            FacebookApiService.get_post_for(posts, animal)