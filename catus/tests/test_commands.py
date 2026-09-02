"""Tests de los comandos de management, que corren por cron sin nadie mirando."""
import shutil
import tempfile
from io import StringIO

from PIL import Image

from django.core.management import call_command
from django.test import TestCase, override_settings

from catus.tests.factories import make_animal, make_animal_image


class OptimizeImagesTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def run_command(self, *args):

        salida = StringIO()
        call_command("optimize_images", *args, stdout=salida, stderr=StringIO())
        return salida.getvalue()

    def test_achica_las_fotos_de_los_animales_en_adopcion(self):

        animal = make_animal(estado="D", aprobado=True)
        imagen = make_animal_image(animal=animal, size=(3000, 2000))

        self.run_command()

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertLessEqual(max(foto.size), 1200)

    def test_respeta_el_ancho_que_se_le_pide(self):

        animal = make_animal(estado="D", aprobado=True)
        imagen = make_animal_image(animal=animal, size=(3000, 2000))

        self.run_command("--max-width", "600")

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertLessEqual(max(foto.size), 600)

    def test_por_defecto_no_toca_los_adoptados(self):

        adoptado = make_animal(estado="A", aprobado=True)
        imagen = make_animal_image(animal=adoptado, size=(3000, 2000))

        self.run_command()

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertEqual(foto.size, (3000, 2000))

    def test_con_todos_tambien_los_adoptados(self):

        adoptado = make_animal(estado="A", aprobado=True)
        imagen = make_animal_image(animal=adoptado, size=(3000, 2000))

        self.run_command("--todos")

        imagen.refresh_from_db()
        with Image.open(imagen.image.path) as foto:
            self.assertLessEqual(max(foto.size), 1200)

    def test_sin_animales_no_rompe(self):

        salida = self.run_command()

        self.assertIn("0", salida)

    def test_informa_cuantas_proceso(self):

        animal = make_animal(estado="D", aprobado=True)
        make_animal_image(animal=animal, size=(2000, 1500))

        salida = self.run_command()

        self.assertIn("Fotos optimizadas: 1", salida)
