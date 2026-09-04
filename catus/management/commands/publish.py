"""Publica en Instagram los animales que están listos. Corre por cron.

No es sólo el pipeline automático: acá también sale lo que el equipo marca a mano desde
/tools/makeimages/, que es como se publicó siempre. Por eso apagar INSTAGRAM_AUTO_ACTIVO
no apaga este comando -eso dejaría al equipo sin poder publicar-, sino sólo lo que está en
la cola porque una agenda automática venció.
"""
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from catus.models import Animal, AnimalImage
from catus.services.base import BaseService
from catus.services.facebook import FacebookApiService
from catus.services.instagram_auto import InstagramAutoService
from catus.utils import clean_html

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Publica en Instagram los animales marcados como listos."

    #Instagram acepta 25 publicaciones cada 24 h por cuenta (el límite del Content
    #Publishing API de Graph). El tope de acá era 999, que es lo mismo que no tener
    #ninguno: mientras el equipo marcaba de a uno no molestaba, pero con el posteo
    #automático la cola pasa a ser todo lo que se aprueba en el día. Se deja margen para
    #lo que el equipo publique a mano desde /tools/ el mismo día.
    MAX_POR_DIA = 20

    #Y un tope por corrida, para no quedarse una hora adentro de una sola: cada foto de un
    #carrusel puede tardar hasta un minuto en procesarse del lado de Instagram.
    MAX_POR_CORRIDA = 5

    #Después de estos intentos el animal deja de intentarse y queda con instagram_error
    #puesto, para que se vea en /tools/. Reintentar para siempre sólo esconde el problema.
    MAX_INTENTOS = 5

    #Espera entre intento e intento, duplicando: 30 min, 1 h, 2 h, 4 h.
    #La primera espera no es sólo backoff: mientras no pase, el animal cuenta como "lo
    #está publicando otra corrida", así que tiene que ser más larga que una publicación
    #entera o la corrida siguiente lo reclama mientras la primera todavía sube fotos, que
    #es justo el post duplicado que se quiere evitar. Un carrusel son once
    #wait_for_media_ready (diez fotos y el contenedor) y cada uno espera hasta 30 x 2 s
    #antes de rendirse: cerca de veinte minutos en el peor caso.
    ESPERA_BASE = timedelta(minutes=30)
    ESPERA_MAXIMA = timedelta(hours=12)

    #El código del error es lo único estable que manda Graph: el mensaje lo escribe
    #Facebook, lo traduce a la locale de la app y lo reescribe cuando quiere, así que
    #buscar "limit reached" adentro del texto dejaba de reconocer el corte con sólo cambiar
    #una palabra. 4 es el tope de la app, 17 el del usuario, 32 el de la página, 613 el rate
    #limit de la API y 9 el tope de publicaciones del Content Publishing API (25 posteos
    #cada 24 h), que es el que se toca primero.
    CODIGOS_DE_LIMITE = (4, 9, 17, 32, 613)

    #Los que no son del animal sino de la conexión con la cuenta: 190 es el token (vencido,
    #revocado o invalidado), 102 la sesión caída, 10 y 200 permisos que faltan. Con
    #cualquiera de estos falla todo lo que se intente publicar.
    CODIGOS_GLOBALES = (10, 102, 190, 200)

    #Y el fallo global que ni siquiera llega a Graph: FacebookApiService.publish devuelve
    #este texto cuando no hay ninguna FacebookAccount cargada. No pasa por show_error, así
    #que no trae código y no queda más que reconocerlo por el texto.
    SIN_CUENTA = "cuenta de Instagram vinculada"

    #El prefijo que arma FacebookApiService.show_error con el JSON de error de Graph:
    #"Error de Instagram 4: ..." o, con subcódigo, "Error de Instagram 190/463: ...".
    #publish() devuelve el error como texto y no como el dict que ya leyó
    #leer_error_de_graph, así que el código se saca de acá: es formato nuestro, no de
    #Facebook, y por eso se puede confiar en él.
    CODIGO_DE_GRAPH = re.compile(r"Error de Instagram (\d+)")

    FALTAN_IMAGENES = (
        "No tiene ninguna foto con la imagen de Instagram generada: se generan en /tools/makeimages/."
    )

    def animales_a_publicar(self):
        """La cola: quién tiene permiso de salir a la cuenta de la organización.

        Mismo criterio que /tools/animaleslistosparapublicar/. Sin mirar aprobado ni
        estado, el cron publicaba animales que nunca se aprobaron, o que ya se habían
        adoptado entre que se marcaron y corrió.

        Lo que la revisión automática marcó para mirar a mano no sale. 'E' (no se pudo
        revisar) y 'P' (sin revisar) no son sospecha y no pueden frenar a nadie: un fallo
        nuestro no se reporta como sospecha de la publicación ajena.
        """

        return Animal.objects.filter(
            instagram_listo_para_publicar=True,
            instagram_publicado=False,
            aprobado=True,
            estado__in=["D", "R"],
        ).exclude(
            revision_ia_estado=Animal.REVISION_REVISAR,
        ).order_by("id")

    def animales_de_esta_corrida(self):
        """De la cola, los que esta corrida puede intentar ahora, hasta donde da el cupo.

        Sale de la cola por lo que le falta al animal (las imágenes, la hora agendada) y
        por lo que ya gastamos (los intentos que lleva, el cupo del día).
        """

        ahora = timezone.now()

        candidatos = self.con_imagen_de_instagram(self.animales_a_publicar()).filter(
            self.gate_de_la_agenda(ahora),
            instagram_intentos__lt=self.MAX_INTENTOS,
        )

        cupo = min(self.MAX_POR_CORRIDA, self.cupo_del_dia())

        return [animal for animal in candidatos if self.le_toca(animal, ahora)][:cupo]

    def gate_de_la_agenda(self, ahora):
        """Qué dice la agenda automática sobre publicar ahora.

        Con el posteo automático prendido, la agenda es una demora: el animal sale recién
        cuando le toca la hora, y esa demora es la única ventana que tiene una persona para
        frenarlo, así que el cron no puede adelantarse.

        Con el flag apagado el pipeline automático no existe, pero este comando sigue
        publicando lo que el equipo marca a mano, que es como se publicó siempre: apagarlo
        no puede dejar al equipo sin poder publicar. Lo que no sale es lo que está en la
        cola sólo porque una agenda automática venció. Ninguno de los dos crones miraba el
        flag, así que apagarlo no frenaba nada de lo que ya estaba agendado.
        """

        sin_agenda = Q(instagram_programado_para__isnull=True)

        if not InstagramAutoService().esta_activo():
            return sin_agenda

        return sin_agenda | Q(instagram_programado_para__lte=ahora)

    def imagenes_generadas(self):
        """Subconsulta: las fotos del animal que ya tienen la imagen de Instagram armada."""

        return AnimalImage.objects.filter(animal=OuterRef("pk")).exclude(
            image_for_instagram="",
        ).exclude(
            image_for_instagram=None,
        ).values("id")

    def con_imagen_de_instagram(self, animales):

        return animales.annotate(
            tiene_imagen=Exists(self.imagenes_generadas()),
        ).filter(tiene_imagen=True)

    def sin_imagen_de_instagram(self, animales):

        return animales.annotate(
            tiene_imagen=Exists(self.imagenes_generadas()),
        ).filter(tiene_imagen=False)

    def cupo_del_dia(self):
        """Lo que queda del límite de Instagram en las últimas 24 h.

        Se cuenta por instagram_ultimo_intento, que lo escribe el reclamo justo antes de
        subir, o sea que se cuentan los posteos DE ESTE COMANDO. El botón de /tools/publish/
        publica sin pasar por acá y no deja ninguna fecha, así que sus posteos no ocupan
        lugar: entre los dos caminos el tope real de la cuenta se puede pasar igual. Por eso
        MAX_POR_DIA deja margen (20 de 25) en vez de apurar el límite. Contarlos de verdad
        pide una fecha de publicación en el modelo, que hoy no existe: instagram_publicado
        es un booleano y updated_at no se escribe cuando se guarda con update_fields.

        Los que se publicaron antes de que existiera el campo no cuentan, pero tampoco caen
        dentro de las 24 h una vez que esto lleva un día andando.
        """

        publicados = Animal.objects.filter(
            instagram_publicado=True,
            instagram_ultimo_intento__gte=timezone.now() - timedelta(hours=24),
        ).count()

        return max(self.MAX_POR_DIA - publicados, 0)

    def espera_por_intentos(self, intentos):
        """Cuánto hay que esperar después de N intentos.

        Duplicando desde ESPERA_BASE y con techo en ESPERA_MAXIMA: 30 min, 1 h, 2 h, 4 h,
        8 h y de ahí 12 h. El docstring decía "15 min, 30 min, 1 h, 2 h", que eran los
        números de cuando ESPERA_BASE era de 15 minutos: la primera espera se subió a 30
        para que sea más larga que una publicación entera (mientras no pase, el animal
        cuenta como "lo está publicando otra corrida") y el docstring quedó viejo.
        """

        if intentos < 1:
            return timedelta(0)

        return min(self.ESPERA_BASE * (2 ** (intentos - 1)), self.ESPERA_MAXIMA)

    def le_toca(self, animal, ahora):
        """Si ya pasó la espera que le corresponde por los intentos que lleva encima."""

        if not animal.instagram_ultimo_intento:
            return True

        return ahora - animal.instagram_ultimo_intento >= self.espera_por_intentos(animal.instagram_intentos)

    def es_una_muestra(self):
        """En LOCAL publish() no llega a Instagram, así que la corrida es sólo una muestra.

        Anotar el intento acá le quemaría el contador y el backoff a un animal que nunca
        se intentó publicar, y lo dejaría fuera de la cola del cron de verdad.
        """

        return settings.ENV == "LOCAL"

    def reclamar(self, animal):
        """UPDATE atómico: la corrida sigue con el animal sólo si se lo quedó ella.

        publish() marca instagram_publicado recién al final, después de esperar a que
        Instagram procese cada foto —minutos con un carrusel—. Con el cron corriendo cada
        pocos minutos, la corrida siguiente veía el mismo animal sin publicar y quedaban
        dos posts iguales en la cuenta de la organización.

        Se escribe con update() y no con save() a propósito: el post_save de Animal
        reescribe el desplegable de forms_builder, y esto corre en cada intento.
        """

        if self.es_una_muestra():
            return True

        reclamados = Animal.objects.filter(
            id=animal.id,
            instagram_publicado=False,
            #si otra corrida lo reclamó primero, ya no es el valor que leímos al armar la cola
            instagram_ultimo_intento=animal.instagram_ultimo_intento,
        ).update(
            instagram_ultimo_intento=timezone.now(),
            instagram_intentos=F("instagram_intentos") + 1,
        )

        return reclamados == 1

    def anotar_error(self, animal, motivo):
        """El motivo queda en el animal: el stdout de un cron no lo mira nadie.

        `animal` viene refrescado, así que instagram_intentos ya cuenta el de esta corrida.
        """

        if self.es_una_muestra():
            return

        if animal.instagram_intentos >= self.MAX_INTENTOS:
            motivo = "Se dejó de intentar después de {} intentos. Último error: {}".format(
                animal.instagram_intentos, motivo,
            )

        Animal.objects.filter(id=animal.id).update(instagram_error=motivo)
        logger.warning("No se pudo publicar %s en Instagram: %s", animal.nombre, motivo)

    def olvidar_el_error(self, animal):
        """Salió bien: el motivo de las fallas anteriores ya no le sirve a nadie."""

        if animal.instagram_error:
            Animal.objects.filter(id=animal.id).update(instagram_error=None)

    def codigo_de_graph(self, motivo):
        """El code del error de Graph que quedó escrito en el motivo, o None."""

        encontrado = self.CODIGO_DE_GRAPH.search(motivo or "")

        return int(encontrado.group(1)) if encontrado else None

    def es_error_de_limite(self, motivo):
        """Instagram cortó por límite: corta para la cuenta, no para este animal."""

        return self.codigo_de_graph(motivo) in self.CODIGOS_DE_LIMITE

    def es_error_global(self, motivo):
        """El fallo no es de este animal sino de la cuenta: con esto falla cualquiera."""

        if self.SIN_CUENTA in (motivo or ""):
            return True

        return self.codigo_de_graph(motivo) in self.CODIGOS_GLOBALES

    def devolver_el_intento(self, animal, ultimo_intento):
        """Le devuelve al animal el intento que le contó el reclamo de esta corrida.

        Un fallo global -el token vencido, la cuenta desvinculada- le hacía perder un
        intento a cada animal de la corrida: en dos corridas los cinco intentos de toda la
        cola se gastaban sin que nadie hubiera publicado nada mal, y después no había forma
        de rehabilitarlos desde la app (instagram_intentos sólo se toca desde el admin).

        Se devuelve también instagram_ultimo_intento, que es lo que mira el backoff: sin
        eso el animal queda esperando por un intento que no hizo. De paso deja de contar
        como "lo está publicando otra corrida", que acá no es un riesgo porque no se llegó
        a subir nada.
        """

        if self.es_una_muestra():
            return

        #el filtro por >0 es el que evita que el UPDATE deje negativo un PositiveInteger
        devueltos = Animal.objects.filter(id=animal.id, instagram_intentos__gt=0).update(
            instagram_intentos=F("instagram_intentos") - 1,
            instagram_ultimo_intento=ultimo_intento,
        )

        if devueltos:
            animal.instagram_intentos -= 1
            animal.instagram_ultimo_intento = ultimo_intento

    def marcar_los_que_no_tienen_imagenes(self):
        """El que está listo pero sin imagen generada no entra, y tiene que verse por qué.

        publish() devolvía el motivo como texto, el comando lo escribía por stdout, no se
        guardaba nada y el animal quedaba en la cola quemando una corrida atrás de otra.
        """

        ids = []

        for animal in self.sin_imagen_de_instagram(self.animales_a_publicar()):
            self.stdout.write("{}: {}".format(animal.nombre, self.FALTAN_IMAGENES))
            ids.append(animal.id)

        if ids:
            Animal.objects.filter(id__in=ids).update(instagram_error=self.FALTAN_IMAGENES)

        #y al que ya las tiene se le saca el aviso: si no, el mensaje le queda pegado
        #hasta que publique, diciendo que le falta algo que ya está
        Animal.objects.filter(instagram_error=self.FALTAN_IMAGENES).exclude(
            id__in=ids,
        ).update(instagram_error=None)

    def publicar(self, animal):
        """Devuelve el texto del resultado.

        publish() no levanta la mayoría de los errores: los devuelve como texto. Quien
        dice si el post salió es instagram_publicado, que lo escribe publish() apenas
        Instagram contesta.
        """

        ig_text = BaseService().render("tools/generartexto.txt", {"animal": animal})
        ig_text = clean_html(ig_text)

        #un fallo con un animal no puede dejar sin publicar a los que siguen
        try:
            resultado = str(FacebookApiService.publish(animal, ig_text))
        except Exception as error:
            resultado = "No se pudo publicar {}: {}".format(animal.nombre, error)
            self.stderr.write(resultado)
            return resultado

        self.stdout.write(resultado)
        return resultado

    def handle(self, *args, **options):

        self.marcar_los_que_no_tienen_imagenes()

        publicados = 0

        for animal in self.animales_de_esta_corrida():

            #lo que había antes del reclamo, para poder devolvérselo si el fallo no es suyo
            ultimo_intento = animal.instagram_ultimo_intento

            if not self.reclamar(animal):
                #otra corrida se lo llevó entre que armamos la cola y llegamos hasta acá
                self.stdout.write("{}: lo está publicando otra corrida".format(animal.nombre))
                continue

            self.stdout.write("publicando {}".format(animal.nombre))

            resultado = self.publicar(animal)

            animal.refresh_from_db()

            if animal.instagram_publicado:
                self.olvidar_el_error(animal)
                publicados += 1
                continue

            #el fallo es de la cuenta y no del animal: van a fallar todos igual, así que se
            #corta la corrida como con el límite y además se le devuelve el intento. Se
            #devuelve antes de anotar el error para que el motivo no diga "se dejó de
            #intentar" por intentos que el animal nunca gastó.
            if self.es_error_global(resultado):
                self.devolver_el_intento(animal, ultimo_intento)
                self.anotar_error(animal, resultado)
                self.stderr.write(
                    "El problema es de la cuenta y no del animal: se corta la corrida.",
                )
                break

            self.anotar_error(animal, resultado)

            #seguir con los que quedan es quemar cuota al pedo y sumarles un intento
            #fallado a cada uno: cuando Instagram corta por límite, corta para la cuenta
            if self.es_error_de_limite(resultado):
                self.stderr.write("Instagram cortó por límite de publicaciones: se corta la corrida.")
                break

        self.stdout.write("Publicados: {}".format(publicados))
