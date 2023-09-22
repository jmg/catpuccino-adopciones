from django.apps import AppConfig


class CatusConfig(AppConfig):
    name = 'catus'

    def ready(self):
        import catus.signals