from django.core.management.base import BaseCommand
from django.views.generic import TemplateView
from catus.models import Animal, EstadoFormulario
from catus.services.adoption import AdoptionService


class Command(BaseCommand):

    def handle(self, *args, **options):

        for animal in Animal.objects.all():

            estado_form = EstadoFormulario.objects.filter(gato_id=animal.id, estado="A")
            if not estado_form:
                estado_form = EstadoFormulario.objects.filter(gato_id=animal.id, estado="R")

            if estado_form:
                estado_form = estado_form[0]

                animal.estado_formulario = estado_form

                try:
                    adoptante = AdoptionService().get_adoptante(estado_form)
                except:
                    adoptante = None

                animal.adoptante = adoptante
                animal.save()