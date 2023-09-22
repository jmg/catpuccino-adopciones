from django.core.management.base import BaseCommand
from django.views.generic import TemplateView
from catus.models import Animal
from catus.services.images import save_image
from django.core.files import File
from django.core.files.base import ContentFile

from PIL import Image


class Command(BaseCommand):

    def handle(self, *args, **options):

        animals = Animal.get_all_for_adoption()

        for animal in animals:

            images = Animal.get_images()

            for image in images:

                img = Image.open(image.imagen)

                optimized_img = save_image(img)

                content_file = ContentFile(optimized_img.read())
                file = File(content_file)

                new_name = image.imagen.name.replace(".png", ".jpg")

                image.imagen.save(new_name, file, save=True)