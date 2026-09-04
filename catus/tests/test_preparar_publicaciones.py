"""Tests del cron que prepara los posteos agendados.

Este comando es el paso que antes se hacía a mano en /tools/makeimages/: arma la imagen
de Instagram de cada foto y recién ahí marca el animal como listo para que lo levante
`publish`. Corre sin nadie mirando, así que lo que acá se rompe se publica —o no se
publica— en la cuenta real de la organización sin que se entere nadie.
"""
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from PIL import Image

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from catus.management.commands.preparar_publicaciones import Command
from catus.models import Animal
from catus.services.facebook import FacebookApiService
from catus.services.images import ImageService
from catus.tests.factories import make_animal, make_animal_image, uploaded_photo


#el color de la barra del nombre en add_nombre_y_edad
COLOR_BARRA = (147, 186, 183)


#El posteo automático arranca apagado y este comando es sólo de ese pipeline: sin el flag
#corta de entrada. Los tests de acá abajo son los del pipeline andando, así que lo prenden;
#el que prueba que apagarlo frena todo lo vuelve a apagar.
@override_settings(ENV="TEST", INSTAGRAM_AUTO_ACTIVO=True)
class PrepararPublicacionesTestCase(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def correr(self):

        salida, errores = StringIO(), StringIO()
        call_command("preparar_publicaciones", stdout=salida, stderr=errores)
        return salida.getvalue() + errores.getvalue()

    def agendado(self, nombre="Willy", hace=timedelta(minutes=5), **kwargs):
        """Un animal aprobado cuya demora ya venció: el cron lo tiene que preparar."""

        kwargs.setdefault("instagram_programado_para", timezone.now() - hace)
        return make_animal(nombre=nombre, **kwargs)

    def con_foto(self, animal, size=(900, 1600), **kwargs):

        return make_animal_image(animal=animal, size=size, **kwargs)

    def correr_con_tope(self, tope):
        """Una corrida con el tope bajado, para no tener que crear diez animales."""

        anterior, Command.MAX_POR_CORRIDA = Command.MAX_POR_CORRIDA, tope
        try:
            return self.correr()
        finally:
            Command.MAX_POR_CORRIDA = anterior

    def ya_generada(self, imagen):
        """Una foto que ya pasó por acá (o por /tools/makeimages/) en una corrida anterior."""

        imagen.image_for_instagram.save("ya_estaba.jpg", uploaded_photo(), save=True)
        return imagen

    def romper(self, imagen):
        """La foto que en el disco no es una foto: se truncó al copiar la galería.

        Se rompe el contenido y no se borra el archivo: al borrarlo, el nombre vuelve a
        quedar libre y la foto que se cargue después se lo lleva, así que las dos filas
        terminaban apuntando al mismo archivo sano y el test no probaba nada.
        """

        with open(imagen.image.path, "wb") as archivo:
            archivo.write(b"esto no es una foto")

        return imagen


class GeneraLasImagenesTest(PrepararPublicacionesTestCase):

    def test_le_arma_la_imagen_a_la_foto_que_no_la_tiene(self):

        imagen = self.con_foto(self.agendado())

        self.correr()

        imagen.refresh_from_db()
        self.assertTrue(imagen.image_for_instagram)
        with Image.open(imagen.image_for_instagram.path) as posteo:
            self.assertEqual(posteo.size, (1400, 1400))

    def test_respeta_la_que_ya_estaba(self):
        """Rearmar la imagen guarda un archivo con otro nombre.

        Si el animal ya está publicado o en cola, esa URL ya se la pasamos a Instagram:
        regenerar de gusto la deja colgada, además de quemar CPU en cada corrida.
        """

        animal = self.agendado()
        vieja = self.ya_generada(self.con_foto(animal))
        nueva = self.con_foto(animal)

        nombre_anterior = vieja.image_for_instagram.name

        self.correr()

        vieja.refresh_from_db()
        nueva.refresh_from_db()

        self.assertEqual(vieja.image_for_instagram.name, nombre_anterior)
        self.assertTrue(nueva.image_for_instagram, "no le armó la imagen a la foto nueva")

    def test_marca_listo_cuando_quedo_al_menos_una_imagen(self):

        animal = self.agendado()
        self.con_foto(animal)

        self.correr()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_listo_para_publicar)
        self.assertIsNone(animal.instagram_error)

    def test_no_marca_listo_al_que_no_tiene_fotos(self):
        """Marcarlo listo sin una sola imagen lo manda a la cola de `publish` a fallar.

        Allá se anota "le faltan las imágenes" corrida tras corrida hasta que alguien
        mira; acá se ve de una que el problema es que nunca cargaron una foto.
        """

        animal = self.agendado()

        self.correr()

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar)
        self.assertIn("foto", animal.instagram_error)

    def test_usa_el_recorte_que_eligio_el_rescatista(self):

        imagen = self.con_foto(self.agendado())
        imagen.set_crop((0.0, 0.25, 1.0, 0.5625))
        imagen.save()

        self.correr()

        imagen.refresh_from_db()
        self.assertAlmostEqual(imagen.crop_y, 0.25)

    def test_le_sugiere_un_recorte_a_la_foto_que_no_lo_tiene(self):
        """Sin recorte el cuadrado sale del centro y le corta la cabeza a media galería.

        suggest_crop() lo propone mirando la foto; queda guardado para que la pantalla
        muestre el que se usó y la corrida siguiente no proponga otro.
        """

        imagen = self.con_foto(self.agendado(), size=(900, 1600))

        self.assertIsNone(imagen.get_crop())

        self.correr()

        imagen.refresh_from_db()
        self.assertIsNotNone(imagen.get_crop())


class QuienEntraTest(PrepararPublicacionesTestCase):
    """Preparar es el paso justo antes de publicar, así que pide los mismos permisos."""

    def tomados(self):

        return [animal.nombre for animal in Command().animales_a_preparar()]

    def test_no_toca_al_que_todavia_no_vencio(self):
        """La demora es la única ventana para cancelar el posteo: adelantarla la borra."""

        imagen = self.con_foto(self.agendado(hace=timedelta(minutes=-30)))

        self.correr()

        imagen.refresh_from_db()
        self.assertFalse(imagen.image_for_instagram)
        self.assertNotIn("Willy", self.tomados())

        imagen.animal.refresh_from_db()
        self.assertFalse(imagen.animal.instagram_listo_para_publicar)

    def test_no_toca_al_que_no_esta_agendado(self):
        """Sin agenda no hay posteo automático: es el animal que se carga y nadie aprueba."""

        self.con_foto(make_animal(nombre="Sin agenda", instagram_programado_para=None))

        self.assertEqual(self.tomados(), [])

    def test_no_prepara_lo_que_la_ia_marco_para_revisar(self):
        """aprobado=True no quiere decir que alguien haya mirado.

        automatic_approve le regala la auto-aprobación al rescatista con historial, así
        que del segundo animal en adelante nadie mira nada: lo que la revisión marcó con
        'R' no puede salir solo a la cuenta de la organización.
        """

        imagen = self.con_foto(self.agendado(revision_ia_estado=Animal.REVISION_REVISAR))

        self.correr()

        imagen.refresh_from_db()
        self.assertFalse(imagen.image_for_instagram)

        imagen.animal.refresh_from_db()
        self.assertFalse(imagen.animal.instagram_listo_para_publicar)

    def test_un_error_de_la_revision_no_frena_a_nadie(self):
        """'E' es un fallo nuestro, no una sospecha sobre la publicación ajena."""

        self.agendado(nombre="No se pudo revisar", revision_ia_estado=Animal.REVISION_ERROR)
        self.agendado(nombre="Sin revisar", revision_ia_estado=Animal.REVISION_PENDIENTE)

        self.assertEqual(sorted(self.tomados()), ["No se pudo revisar", "Sin revisar"])

    def test_tabla_de_quien_entra(self):
        """Entra el aprobado, en adopción o reservado, agendado y todavía sin publicar."""

        for aprobado in (True, False):
            for estado in ("D", "R", "A", "E"):
                for publicado in (True, False):

                    entra = aprobado and estado in ("D", "R") and not publicado

                    with self.subTest(aprobado=aprobado, estado=estado, publicado=publicado):

                        animal = self.agendado(
                            nombre="Willy",
                            aprobado=aprobado,
                            estado=estado,
                            instagram_publicado=publicado,
                        )

                        self.assertEqual(self.tomados(), ["Willy"] if entra else [])

                        animal.delete()


class FallasTest(PrepararPublicacionesTestCase):

    def test_un_fallo_en_uno_no_frena_a_los_que_siguen(self):

        roto = self.agendado(nombre="Roto", hace=timedelta(hours=1))
        self.romper(self.con_foto(roto))

        sano = self.agendado(nombre="Sano", hace=timedelta(minutes=1))
        imagen_sana = self.con_foto(sano)

        self.correr()

        imagen_sana.refresh_from_db()
        self.assertTrue(imagen_sana.image_for_instagram, "el que andaba se quedó esperando al roto")

        sano.refresh_from_db()
        self.assertTrue(sano.instagram_listo_para_publicar)

    def test_el_que_falla_queda_con_el_motivo_y_sin_marcar_listo(self):
        """El stdout de un cron no lo lee nadie: el motivo tiene que quedar en el animal."""

        animal = self.agendado(nombre="Roto")
        self.romper(self.con_foto(animal))

        self.correr()

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar)
        self.assertTrue(animal.instagram_error)

    def test_una_foto_rota_no_deja_a_medias_a_las_otras(self):
        """Las que se pueden armar se arman igual: el equipo decide con el posteo a la vista."""

        animal = self.agendado()
        rota = self.romper(self.con_foto(animal))
        sana = self.con_foto(animal)

        self.correr()

        sana.refresh_from_db()
        self.assertTrue(sana.image_for_instagram)

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar, "salio un carrusel al que le falta una foto")
        self.assertIn(str(rota.id), animal.instagram_error or "")

    def test_el_que_ya_fallo_no_se_come_el_cupo_de_los_que_andan(self):
        """El roto falla rápido, pero vuelve a intentarse en cada corrida.

        En orden de agenda es siempre el más viejo, así que un puñado de animales rotos se
        come el tope de la corrida todos los días y el que se aprobó hoy no sale nunca.
        """

        roto = self.agendado(nombre="Roto", hace=timedelta(days=2), instagram_error="ya falló antes")
        self.romper(self.con_foto(roto))

        sano = self.agendado(nombre="Sano", hace=timedelta(minutes=1))
        imagen = self.con_foto(sano)

        self.correr_con_tope(1)

        imagen.refresh_from_db()
        self.assertTrue(imagen.image_for_instagram, "el cupo se lo comió uno que ya venía fallando")


class IdempotenciaTest(PrepararPublicacionesTestCase):

    def test_correrlo_dos_veces_no_cambia_nada_la_segunda_vez(self):
        """El cron corre cada pocos minutos y el animal se queda en la cola hasta publicar.

        Rearmar las imágenes en cada corrida cambia el nombre del archivo —o sea, la URL
        que `publish` le pasa a Instagram— y quema CPU en cada vuelta.
        """

        animal = self.agendado()
        primera = self.con_foto(animal)
        segunda = self.con_foto(animal)

        self.correr()

        primera.refresh_from_db()
        segunda.refresh_from_db()
        nombres = (primera.image_for_instagram.name, segunda.image_for_instagram.name)

        self.correr()

        primera.refresh_from_db()
        segunda.refresh_from_db()

        self.assertEqual((primera.image_for_instagram.name, segunda.image_for_instagram.name), nombres)

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_listo_para_publicar)
        self.assertIsNone(animal.instagram_error)

    def test_el_que_ya_esta_listo_no_se_come_el_cupo_de_la_corrida(self):
        """El preparado se queda en la cola hasta que `publish` lo levante.

        Si contara para el tope por corrida, unos pocos animales esperando a publicarse
        dejarían sin preparar a todos los que se aprobaron después.
        """

        esperando = self.agendado(nombre="Esperando", hace=timedelta(hours=2))
        self.ya_generada(self.con_foto(esperando))
        esperando.instagram_listo_para_publicar = True
        esperando.save()

        recien = self.agendado(nombre="Recién", hace=timedelta(minutes=1))
        imagen = self.con_foto(recien)

        self.correr_con_tope(1)

        imagen.refresh_from_db()
        self.assertTrue(imagen.image_for_instagram, "el cupo se lo comió uno que ya estaba listo")

    def test_el_tope_por_corrida_corta(self):
        """Componer imágenes es caro: una corrida no puede quedarse horas adentro."""

        for i in range(3):
            self.con_foto(self.agendado(nombre="Animal {}".format(i), hace=timedelta(hours=3 - i)))

        self.correr_con_tope(2)

        listos = Animal.objects.filter(instagram_listo_para_publicar=True).count()
        self.assertEqual(listos, 2)


class NombreLargoTest(PrepararPublicacionesTestCase):
    """El tamaño de letra por default (150) no entra en el lienzo con cualquier nombre.

    add_nombre_y_edad dibuja la barra del nombre desde x=0 hasta 130 + el ancho del texto,
    sin mirar el lienzo: con "Bartolomeo Maximiliano de los Santos" el texto mide 2356 px
    sobre 1400 de lienzo, así que la barra tapaba el ancho entero y el nombre salía
    cortado. Mientras las imágenes se armaban a mano se veía en la previsualización y se
    bajaba el tamaño; el cron no mira.
    """

    NOMBRE_LARGO = "Bartolomeo Maximiliano de los Santos"

    def borde_derecho_de_la_barra(self, path):
        """Hasta qué x llega la barra del nombre en la imagen ya generada."""

        with Image.open(path) as posteo:
            pixeles = posteo.convert("RGB").load()

            borde = 0
            #alcanza con la franja donde se dibuja el nombre arriba (la barra va de y=100
            #a y=280): recorrer las 1400 filas es un minuto de test por nada
            for y in range(100, 285):
                for x in range(posteo.size[0]):
                    if all(abs(a - b) <= 25 for a, b in zip(pixeles[x, y], COLOR_BARRA)):
                        borde = max(borde, x)

            return borde

    def test_el_tamano_baja_hasta_que_el_nombre_entra(self):

        service = ImageService()

        self.assertEqual(service.tamano_de_letra_para_el_nombre("Willy"), 150)

        elegido = service.tamano_de_letra_para_el_nombre(self.NOMBRE_LARGO)

        self.assertLess(elegido, 150)
        self.assertIn(elegido, service.TAMANOS_NOMBRE)
        self.assertLessEqual(
            service.MARGEN_BARRA_NOMBRE + service.ancho_del_nombre(self.NOMBRE_LARGO, elegido),
            service.LADO_LIENZO_POSTEO,
        )

    def test_un_nombre_largo_no_se_sale_de_la_imagen(self):

        imagen = self.con_foto(self.agendado(nombre=self.NOMBRE_LARGO))

        self.correr()

        imagen.refresh_from_db()

        borde = self.borde_derecho_de_la_barra(imagen.image_for_instagram.path)

        self.assertGreater(borde, 0, "no se encontró la barra del nombre: el test no mide nada")
        self.assertLess(
            borde, ImageService.LADO_LIENZO_POSTEO - ImageService.MARGEN_BORDE_POSTEO,
            "la barra del nombre llega hasta el borde del posteo",
        )

    def test_respeta_un_tamano_elegido_a_mano(self):
        """El tamaño guardado es un techo: bajarlo cuando no entra no le pisa la decisión
        a nadie, pero subirlo sí."""

        imagen = self.con_foto(self.agendado(nombre="Mishi"), image_font_size=50)

        self.correr()

        imagen.refresh_from_db()
        self.assertEqual(imagen.image_font_size, 50)


class AgendaDeUnSoloUsoTest(PrepararPublicacionesTestCase):
    """La agenda se gasta apenas el cron termina con el animal.

    `instagram_programado_para` no se limpiaba nunca: una vez vencida, el animal volvía a
    la cola en todas las corridas hasta que se publicara. Como preparar sólo se abstenía
    cuando la marca YA estaba prendida, cualquier freno del equipo se revertía solo en la
    corrida siguiente.
    """

    def test_marcar_listo_le_gasta_la_agenda(self):

        animal = self.agendado()
        self.con_foto(animal)

        self.correr()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_listo_para_publicar)
        self.assertIsNone(animal.instagram_programado_para, "la agenda quedó vencida para siempre")

    def test_apagar_la_marca_a_mano_frena_el_posteo_de_verdad(self):
        """El bug de fondo: el gesto de freno duraba una corrida.

        Alguien del equipo entra a /tools/, destilda "listo para publicar" y se va
        tranquilo. Como la agenda seguía vencida, la corrida siguiente lo levantaba de
        nuevo, le volvía a prender la marca y el posteo salía igual.
        """

        animal = self.agendado()
        self.con_foto(animal)

        self.correr()

        #el gesto de freno: es lo que escribe /tools/saveform/ al destildar la marca
        Animal.objects.filter(id=animal.id).update(instagram_listo_para_publicar=False)

        self.correr()

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar, "el cron le volvió a prender la marca")

    def test_el_que_falla_tampoco_se_queda_agendado_para_siempre(self):
        """Reintentar la foto rota en cada corrida son segundos de CPU para volver a fallar.

        Queda con el motivo escrito -que es lo que se ve en /tools/colainstagram/- y vuelve
        a la cola sólo si alguien lo reagenda desde ahí.
        """

        animal = self.agendado(nombre="Roto")
        self.romper(self.con_foto(animal))

        self.correr()

        animal.refresh_from_db()
        self.assertTrue(animal.instagram_error)
        self.assertIsNone(animal.instagram_programado_para)
        self.assertEqual([], [a.nombre for a in Command().animales_a_preparar()])

    def test_un_error_apaga_la_marca_que_ya_estaba_prendida(self):
        """El carrusel incompleto: anotar el error no alcanzaba, el animal salía igual.

        El animal ya estaba listo de una corrida anterior y ahora una foto nueva no se
        puede componer. Con la marca prendida, `publish` lo publicaba igual: un carrusel al
        que le falta una foto que el rescatista sí cargó, sin que se entere nadie.
        """

        animal = self.agendado(nombre="Roto", instagram_listo_para_publicar=True)
        self.ya_generada(self.con_foto(animal))
        self.romper(self.con_foto(animal))

        self.correr()

        animal.refresh_from_db()
        self.assertFalse(animal.instagram_listo_para_publicar, "salía un carrusel al que le falta una foto")
        self.assertTrue(animal.instagram_error)

    def test_un_fallo_inesperado_deja_el_motivo_y_no_se_reintenta_solo(self):
        """El único camino que no dejaba rastro: se reintentaba en silencio para siempre.

        Y sin instagram_error escrito iba primero en la cola, así que se comía el cupo de
        los que sí se podían preparar, todos los días.
        """

        animal = self.agendado()
        self.con_foto(animal)

        def reventar(*args, **kwargs):
            raise Exception("se cortó la base a mitad de camino")

        with mock.patch.object(Command, "tiene_alguna_imagen", side_effect=reventar):
            self.correr()

        animal.refresh_from_db()
        self.assertIn("No se pudo preparar", animal.instagram_error or "")
        self.assertIsNone(animal.instagram_programado_para)


class FlagApagadoTest(PrepararPublicacionesTestCase):
    """Apagar INSTAGRAM_AUTO_ACTIVO tiene que frenar lo que ya está agendado."""

    @override_settings(INSTAGRAM_AUTO_ACTIVO=False)
    def test_con_el_flag_apagado_no_prepara_nada(self):
        """El comando no lo miraba: apagar el posteo automático no frenaba a los agendados,
        que se preparaban igual y quedaban esperando en la cola de `publish`."""

        imagen = self.con_foto(self.agendado())

        salida = self.correr()

        imagen.refresh_from_db()
        self.assertFalse(imagen.image_for_instagram, "armó las imágenes con el posteo automático apagado")

        imagen.animal.refresh_from_db()
        self.assertFalse(imagen.animal.instagram_listo_para_publicar)
        self.assertIn("apagado", salida)


class TopeDeFotosTest(PrepararPublicacionesTestCase):
    """Componer es la parte cara del comando: no se compone lo que no se publica."""

    def test_no_arma_las_fotos_que_instagram_no_va_a_publicar(self):
        """Instagram no acepta más de diez y `publish` corta ahí: la 11 se armaba al pedo.

        En un animal con veinte fotos son diez composiciones tiradas por corrida.
        """

        animal = self.agendado()
        fotos = [self.con_foto(animal, size=(300, 300), posicion=posicion) for posicion in range(1, 13)]

        self.correr()

        for foto in fotos[:FacebookApiService.MAX_IMAGENES_POR_POST]:
            foto.refresh_from_db()
            self.assertTrue(foto.image_for_instagram, "no armó una foto que sí se publica")

        for foto in fotos[FacebookApiService.MAX_IMAGENES_POR_POST:]:
            foto.refresh_from_db()
            self.assertFalse(foto.image_for_instagram, "armó una foto que Instagram nunca va a publicar")
