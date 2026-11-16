from django.apps import AppConfig


class CatusConfig(AppConfig):
    name = 'catus'

    def ready(self):
        import catus.signals

        #El límite propio de Pillow, para todo lo que abre fotos (las ya guardadas, la de
        #Instagram, los duplicados): por encima del doble, Image.open() tira
        #DecompressionBombError en vez de decodificar. Las fotos que llegan de afuera se
        #controlan antes y más fino (services/images.py, MAX_PIXELES).
        from PIL import Image
        from catus.services.images import MAX_PIXELES
        Image.MAX_IMAGE_PIXELS = MAX_PIXELES
