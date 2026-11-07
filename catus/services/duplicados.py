"""¿Este animal ya lo cargó la misma persona?

Lo motivó un caso de producción (2026-11-02): una cuenta cargó al mismo perro dos veces
con 29 minutos de diferencia, con el mismo nombre, tipo, sexo, edad y texto, y las
mismas seis fotos. El primero estaba esperando que el equipo lo aprobara y la persona,
como no lo veía publicado, lo volvió a cargar. El doble clic en "Guardar Cambios" hace lo
mismo en un segundo. Cada repetido es una publicación más que el equipo tiene que
encontrar y borrar a mano, y una revisión con IA pagada dos veces.

La vista pregunta esto al dar de alta, antes de guardar nada (views/animal.py, EditView).
No es atómico: busca y después guarda, sin lock, así que frena a un segundo envío sólo si
llega después de que el primero se guardó. Dos POST pegados pasan los dos; contra el doble
clic protege la guarda del botón en animal/edit.html.

Corre en cada alta de cualquier cuenta, y el registro es abierto: todo lo que hace sobre lo
que manda el usuario tiene que costar poco y tener tope.
"""
import hashlib
import html
import logging
import os
import re
import unicodedata
from collections import namedtuple
from datetime import timedelta

from django.core.exceptions import SuspiciousFileOperation
from django.db.models import Count, Q
from django.db.models.functions import Substr
from django.utils import timezone
from PIL import Image

from catus.models import Animal, AnimalImage
from catus.services.images import ImageService

logger = logging.getLogger(__name__)


#motivo es "datos" (mismo nombre, tipo, sexo, edad y texto), "nombre y foto" (mismo nombre,
#tipo y sexo, y alguna foto igual) o "fotos" (mismo tipo y sexo, y exactamente las mismas
#fotos, al menos dos)
Duplicado = namedtuple("Duplicado", ["animal", "motivo"])

#una etiqueta de HTML, sin '<' adentro. Con r"<[^>]*>" cada '<' sin cerrar recorría todo el
#resto del texto buscando un '>': '<' * 100.000 tardaba 3,5 s y el doble, 14 s, con el GIL
#tomado (se traba el worker entero, con sus 4 threads). Así cada '<' mira sólo hasta el
#próximo '<' o '>', y el costo crece con el largo, no con su cuadrado.
ETIQUETA_HTML = re.compile(r"<[^<>]*>")

#una referencia numérica que no puede ser un carácter: los válidos llegan a 1114111 (7
#dígitos) o 0x10FFFF (6 hexadecimales). html.unescape le hace int() a lo que venga, y Python
#3.12 corta en 4300 dígitos con ValueError: un alta con '&#' y 4301 nueves daba un 500
REFERENCIA_IMPOSIBLE = re.compile(r"&#(?:[xX][0-9a-fA-F]{7,}|[0-9]{8,});?")


def normalizar(texto):
    """Lo que se compara de un texto: sin HTML, sin mayúsculas y con los espacios colapsados.

    El texto del animal sale de TinyMCE, así que el mismo texto puede volver con otros
    <p>, con &nbsp; o con &aacute; en vez de la letra. Las etiquetas se cambian por un
    espacio y no por nada: "fin.</p><p>Otro" tiene que dar lo mismo que "fin. Otro".

    Recibe lo que escribió cualquiera que se registre, así que tiene que ser lineal (ver
    ETIQUETA_HTML), no puede tirar excepciones (REFERENCIA_IMPOSIBLE) y no puede agrandar
    el texto: NFC y no NFKC, que "compatibiliza" caracteres y alguno crece 18 veces (U+FDFA),
    así que un texto ya recortado volvía a agrandarse. El largo lo acota quien la llama:
    DuplicadosService recorta el texto antes (MAX_CARACTERES_TEXTO).
    """

    sin_etiquetas = ETIQUETA_HTML.sub(" ", texto or "")
    sin_referencias = REFERENCIA_IMPOSIBLE.sub(" ", sin_etiquetas)

    try:
        sin_entidades = html.unescape(sin_referencias)
    except ValueError:
        sin_entidades = sin_referencias

    return " ".join(unicodedata.normalize("NFC", sin_entidades).split()).casefold()


class DuplicadosService():

    #el caso que lo motivó volvió a la media hora; con 90 días también se ve al que lo
    #vuelve a cargar porque pasaron días y no lo encuentra publicado
    DIAS = 90

    #un animal expirado o adoptado sí se puede volver a cargar: es otra publicación
    ESTADOS = ("D", "R")

    #comparar los datos es una consulta; las fotos hay que leerlas del disco, y una por
    #una: por eso miran menos animales
    MAX_ANIMALES = 200
    MAX_ANIMALES_POR_FOTOS = 20
    MAX_FOTOS_GUARDADAS = 120
    MAX_FOTOS_SUBIDAS = 12

    #del texto se compara el principio. Un aviso de verdad tiene un par de miles de
    #caracteres, pero `datos` no tiene tope (Django deja pasar 2,5 MB de campos) y se compara
    #contra el de hasta 200 animales. Se recorta igual de los dos lados, antes de normalizar:
    #el que llega acá, y el guardado ya desde la base (Substr), sin traer el texto entero
    MAX_CARACTERES_TEXTO = 20000

    #el texto se trae y se normaliza sólo de los que ya coinciden en nombre y edad, y de
    #esos, de los más nuevos
    MAX_COMPARACIONES_DE_TEXTO = 20

    #una foto guardada pasó por optimize() y pesa unos cientos de KB: más que esto es otra
    #cosa, y no vale la pena leerla entera en el POST del alta
    MAX_BYTES_FOTO_GUARDADA = 20 * 1024 * 1024

    #y entre todas: sólo con los dos topes de arriba eran 120 fotos de hasta 20 MB, 2,4 GB
    #leídos del disco en un POST
    MAX_BYTES_FOTOS_GUARDADAS = 60 * 1024 * 1024

    def buscar(self, usuario, datos, fotos_subidas=(), hay_fotos_de_instagram=False, max_width=1200):
        """El Duplicado con el animal que `usuario` ya tiene cargado y que es este mismo, o None.

        `datos` es el cleaned_data del AnimalForm. `fotos_subidas` son los archivos que trae
        el POST, que todavía no se guardaron: quedan otra vez al principio, porque después se
        guardan. `max_width` tiene que ser el mismo con el que la vista llama a optimize():
        es lo que define cómo quedó guardada cada foto.

        Es duplicado si coinciden nombre, tipo, sexo, edad y texto, o si las fotos dicen que
        es el mismo (ver por_fotos). No lo es un animal de otra cuenta, ni uno que ya expiró
        o se adoptó, ni uno que sólo comparte el nombre: Luna, Mía y Simba se repiten todo
        el tiempo.
        """

        if not getattr(usuario, "pk", None):
            return None

        candidatos = self.candidatos(usuario)

        animal = self.por_datos(candidatos, datos)
        if animal is not None:
            return Duplicado(animal, "datos")

        return self.por_fotos(candidatos, datos, list(fotos_subidas), hay_fotos_de_instagram, max_width)

    def candidatos(self, usuario):
        """Los animales de esta persona que todavía están publicados o por publicarse.

        Con o sin aprobar: el caso que motivó esto era justamente uno que estaba esperando
        la aprobación. Sin el texto: de ese se trae sólo el principio (ver por_datos).
        """

        desde = timezone.now() - timedelta(days=self.DIAS)

        return Animal.objects.filter(
            cargado_por=usuario, estado__in=self.ESTADOS, created_at__gte=desde,
        ).only(
            "id", "nombre", "tipo", "sexo", "edad", "estado", "aprobado", "created_at",
        ).order_by("-created_at", "-id")

    def por_datos(self, candidatos, datos):
        """El animal con el mismo nombre, tipo, sexo, edad y texto, o None.

        Sin texto no aplica: dos "Cachorro" macho sin edad ni texto, con otras fotos, son dos
        cachorros. Primero se compara lo barato (nombre y edad, de 255 caracteres como mucho)
        y el texto se trae de la base y se normaliza sólo de los que ya coinciden en eso.
        Del texto se comparan los primeros MAX_CARACTERES_TEXTO caracteres, de los dos lados:
        dos textos que recién se separan después de eso cuentan como el mismo, si además
        coincide todo lo demás.
        """

        texto = normalizar((datos.get("datos") or "")[:self.MAX_CARACTERES_TEXTO])
        if not texto:
            return None

        nombre, edad = normalizar(datos.get("nombre")), normalizar(datos.get("edad"))

        mismos = candidatos.filter(tipo=datos.get("tipo"), sexo=datos.get("sexo"))

        coinciden = [
            animal.id for animal in mismos[:self.MAX_ANIMALES]
            if normalizar(animal.nombre) == nombre and normalizar(animal.edad) == edad
        ][:self.MAX_COMPARACIONES_DE_TEXTO]

        if not coinciden:
            return None

        con_texto = mismos.filter(id__in=coinciden).annotate(
            principio_de_datos=Substr("datos", 1, self.MAX_CARACTERES_TEXTO),
        )

        for animal in con_texto:
            if normalizar(animal.principio_de_datos) == texto:
                return animal

        return None

    def por_fotos(self, candidatos, datos, fotos_subidas, hay_fotos_de_instagram, max_width):
        """El Duplicado con el animal que ya tiene estas fotos, si eso alcanza para decir que
        es el mismo, o None.

        Una foto repetida sola no alcanza: los hermanos de una camada se publican cada uno
        por su lado con la foto de todos juntos, hay cuentas que suben su flyer como única
        foto, y la publicación de uno solo reusa fotos de la de la camada. Las dos reglas
        piden el mismo tipo y sexo (una gata y una perra que comparten el flyer, o una pareja
        de macho y hembra con las mismas fotos de los dos, no son el mismo animal). Es el
        mismo si:

        - se llama igual (normalizado) y tiene al menos una de estas fotos: "nombre y foto";
        - o tiene exactamente las mismas fotos que esta alta, ni una más ni una menos, y son
          al menos dos: "fotos", el mismo animal con otro nombre. Que las fotos del alta
          estén todas en el otro no alcanza: un gatito que sale por su lado con dos fotos de
          la publicación de su camada se frenaba.

        Para la segunda hay que ver todas las fotos del alta. Las que vienen de un post de
        Instagram se bajan después de guardar, y de más de MAX_FOTOS_SUBIDAS se comparan
        sólo esas: en los dos casos queda sólo la primera regla. Las fotos guardadas se leen
        sólo de los animales que podrían coincidir: el del mismo nombre, o uno con tantas
        fotos como las distintas de esta alta. En el alta común no se lee ninguna.
        """

        if not fotos_subidas:
            return None

        animales = list(candidatos.filter(
            tipo=datos.get("tipo"), sexo=datos.get("sexo"),
        ).annotate(
            cantidad_de_fotos=Count("animalimage", filter=~Q(animalimage__image="")),
        )[:self.MAX_ANIMALES_POR_FOTOS])

        if not animales:
            return None

        nombre = normalizar(datos.get("nombre"))
        con_el_mismo_nombre = {animal.id for animal in animales if normalizar(animal.nombre) == nombre}

        comparadas = fotos_subidas[:self.MAX_FOTOS_SUBIDAS]

        #la misma foto subida dos veces es una sola
        subidas, ilegibles = self.huellas_crudas(comparadas)

        puede_ser_por_fotos = (
            len(comparadas) == len(fotos_subidas) and not hay_fotos_de_instagram
            and not ilegibles and len(subidas) >= 2
        )

        animales = [
            animal for animal in animales
            if animal.id in con_el_mismo_nombre
            or (puede_ser_por_fotos and animal.cantidad_de_fotos == len(subidas))
        ]
        if not animales:
            return None

        guardadas = self.huellas_guardadas(animales)
        if not guardadas:
            return None

        todas_las_guardadas = set().union(*guardadas.values())

        #lo que queda en el disco no es lo que se subió: optimize() reencoda siempre. Cada
        #foto se compara tal cual llegó (por si quedó guardada sin pasar por ahí) y además
        #con lo que le dejaría optimize(), que es lo que guardó el alta anterior. Rehacer
        #eso es lo caro, así que si ya coincidió tal cual, no se rehace
        huellas_subidas = []
        for cruda, archivo in subidas.items():

            huellas = {cruda}

            if cruda not in todas_las_guardadas:
                optimizada = self.huella_optimizada(archivo, max_width)
                if optimizada:
                    huellas.add(optimizada)

            huellas_subidas.append(huellas)

        for animal in animales:

            huellas = guardadas.get(animal.id)
            if not huellas:
                continue

            repetidas = sum(1 for huellas_de_una in huellas_subidas if huellas_de_una & huellas)
            if not repetidas:
                continue

            if animal.id in con_el_mismo_nombre:
                return Duplicado(animal, "nombre y foto")

            #el mismo conjunto: todas las del alta están en el otro, y el otro no tiene ni
            #una más (se leyeron todas las suyas y son tantas como las del alta)
            mismo_conjunto = (
                repetidas == len(huellas_subidas)
                and len(huellas) == animal.cantidad_de_fotos == len(huellas_subidas)
            )
            if puede_ser_por_fotos and mismo_conjunto:
                return Duplicado(animal, "fotos")

        return None

    def huellas_crudas(self, archivos):
        """({sha256 de la foto tal cual llegó: su archivo}, cuántas no se pudieron leer).

        La misma foto subida dos veces queda una sola vez. Cada archivo queda otra vez al
        principio.
        """

        huellas = {}
        ilegibles = 0

        for archivo in archivos:
            try:
                digest = hashlib.sha256()
                for pedazo in archivo.chunks():
                    digest.update(pedazo)

                huellas.setdefault(digest.hexdigest(), archivo)
            except (OSError, ValueError) as error:
                ilegibles += 1
                logger.warning("No se pudo leer una foto subida para buscar duplicados: %s", type(error).__name__)
            finally:
                archivo.seek(0)

        return huellas, ilegibles

    def huella_optimizada(self, archivo, max_width):
        """El sha256 de lo que optimize() guardaría de esta foto, o None si no se pudo.

        Depende de ImageService.bytes_optimizados(): si cambia optimize() o Pillow, las
        fotos que ya estaban guardadas dejan de coincidir hasta que esos animales pasan los
        DIAS. Es determinístico: en el caso de producción las seis fotos de los dos animales
        quedaron iguales byte a byte. El archivo queda otra vez al principio.
        """

        try:
            return hashlib.sha256(ImageService().bytes_optimizados(archivo, max_width)).hexdigest()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
            #el formulario ya validó que se puede abrir: si igual falla, se compara con lo
            #que haya y el alta sigue
            logger.warning("No se pudo leer una foto subida para buscar duplicados: %s", type(error).__name__)
            return None
        finally:
            archivo.seek(0)

    def huellas_guardadas(self, animales):
        """{id del animal: {sha256 de cada foto guardada}}, de las que están en el disco.

        Es lo que más se lee en el POST del alta, así que tiene tres topes: cuántas fotos,
        cuánto pesa cada una y cuánto entre todas. Van primero las de los animales más
        nuevos, y la que ya no entra en lo que queda del total se saltea.
        """

        huellas = {}
        quedan = self.MAX_BYTES_FOTOS_GUARDADAS

        imagenes = AnimalImage.objects.filter(
            animal_id__in=[animal.id for animal in animales],
        ).exclude(image="").only("id", "animal_id", "image").order_by("-animal_id", "id")[:self.MAX_FOTOS_GUARDADAS]

        for imagen in imagenes:

            ruta, tamano = self.ruta_y_tamano(imagen.image)
            if ruta is None or tamano > self.MAX_BYTES_FOTO_GUARDADA or tamano > quedan:
                continue

            quedan -= tamano

            huella = self.sha256_del_archivo(ruta)
            if huella:
                huellas.setdefault(imagen.animal_id, set()).add(huella)

        return huellas

    def ruta_y_tamano(self, archivo):
        """(ruta, bytes) de una foto guardada, o (None, 0) si no está en el disco."""

        try:
            ruta = archivo.path
            if not os.path.isfile(ruta):
                return None, 0

            return ruta, os.path.getsize(ruta)
        except (OSError, ValueError, NotImplementedError, SuspiciousFileOperation):
            #ValueError: el campo no tiene archivo; NotImplementedError: un storage sin
            #rutas; SuspiciousFileOperation: un nombre que apunta fuera de MEDIA_ROOT
            return None, 0

    def sha256_del_archivo(self, ruta):
        """El sha256 de un archivo del disco, leído por pedazos, o None si no se pudo."""

        try:
            digest = hashlib.sha256()
            with open(ruta, "rb") as abierto:
                for pedazo in iter(lambda: abierto.read(1024 * 1024), b""):
                    digest.update(pedazo)

            return digest.hexdigest()
        except OSError:
            return None
