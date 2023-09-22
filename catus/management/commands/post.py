from django.core.management.base import BaseCommand
from catus.models import Animal, FacebookAccount
from catus.services.facebook import FacebookApiService


class Command(BaseCommand):

    def handle(self, *args, **options):

        animal = Animal.objects.get(id=1)

        #image_url = "{}{}".format(settings.SSL_HOST animal.animalimage_set.first().image_for_instagram.url)
        image_url = "https://adopciones.catpuccino.org/gallery/8dcb5e33-cf64-4564-b3d3-40a585a6ec9e.jpeg"
        #caption = self.request.POST.get("ig_text")
        caption = animal.description

        account = FacebookAccount.objects.all().first()

        url = "{}/media".format(
            account.remote_id,
        )

        data = {
            "image_url": image_url,
            "caption": caption,
            "locale": "en_us",
        }

        service = FacebookApiService(account=account)
        data = service.facebook.request(url, **data)
        print (data)

        print (data)

        url = "{}/media_publish".format(
            account.remote_id,
        )

        data = {
            "creation_id" : data["id"],
            "locale": "en_us",
        }

        print (service.facebook.request(url, **data))

        return self.response("Publicado.")