from django.core.management.base import BaseCommand, CommandError
import instaloader
from pathlib2 import Path


class Command(BaseCommand):

    def handle(self, *args, **options):

        L = instaloader.Instaloader(save_metadata=False, quiet=True, compress_json=False)
        L.context._session.proxies = {
            'http':  'http://%s'%("us-wa.proxymesh.com:31280"),
            'https': 'http://%s'%("us-wa.proxymesh.com:31280"),
        }
        post = instaloader.Post.from_shortcode(L.context, "Cq6AYP9rCob")

        L.download_post(post, target=Path("/tmp/test"))