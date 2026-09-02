"""Publica en Instagram los animales que el equipo marcó como listos. Corre por cron."""
from django.core.management.base import BaseCommand

from catus.models import Animal
from catus.services.base import BaseService
from catus.services.facebook import FacebookApiService
from catus.utils import clean_html


class Command(BaseCommand):

    help = "Publica en Instagram los animales marcados como listos."

    MAX_PUBLICATIONS = 999

    def animales_a_publicar(self):
        """Mismo criterio que /tools/animaleslistosparapublicar/.

        Sin mirar aprobado ni estado, el cron publicaba animales que nunca se
        aprobaron, o que ya se habían adoptado entre que se marcaron y corrió.
        """

        return Animal.objects.filter(
            instagram_listo_para_publicar=True,
            instagram_publicado=False,
            aprobado=True,
            estado__in=["D", "R"],
        ).order_by("id")[:self.MAX_PUBLICATIONS]

    def handle(self, *args, **options):

        for animal in self.animales_a_publicar():

            self.stdout.write("publicando {}".format(animal.nombre))

            ig_text = BaseService().render("tools/generartexto.txt", {"animal": animal})
            ig_text = clean_html(ig_text)

            #un fallo con un animal no puede dejar sin publicar a los que siguen
            try:
                self.stdout.write(str(FacebookApiService.publish(animal, ig_text)))
            except Exception as error:
                self.stderr.write("No se pudo publicar {}: {}".format(animal.nombre, error))
