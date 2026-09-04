"""Prepara los posteos agendados: arma las imágenes y los deja listos. Corre por cron.

Va antes que `publish`. Hasta acá el paso intermedio era a mano —entrar a
/tools/makeimages/, mirar cada foto y apretar "Marcar como listo"—, así que un animal
aprobado se quedaba esperando a que alguien del equipo pasara por la pantalla. Este
comando hace ese paso con lo que ya eligió el rescatista al cargar las fotos.

Lo que NO hace es decidir quién se publica: eso lo decide `instagram_programado_para`, que
se escribe al aprobar y deja la ventana para cancelar. Acá sólo se prepara lo que ya está
vencido, y lo que la revisión automática marcó para mirar a mano no se prepara nunca.

La agenda es de un solo uso: se gasta apenas el cron termina con el animal. Antes no se
limpiaba nunca, así que quedaba vencida para siempre y el animal se volvía a levantar en
cada corrida: cualquier freno del equipo -destildar "listo para publicar"- duraba hasta la
corrida siguiente, que se la volvía a prender. De acá en adelante el animal avanza por la
marca, que es la que una persona puede apagar.
"""
import logging

from django.core.management.base import BaseCommand
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from catus.models import Animal
from catus.services.facebook import FacebookApiService
from catus.services.images import ImageService
from catus.services.instagram_auto import InstagramAutoService

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Genera las imágenes de Instagram de los animales agendados y los deja listos para publicar."

    #Componer una imagen son varios segundos de CPU por foto (abrirla, recortarla, pegar el
    #logo, escribir el nombre) y un animal puede tener diez. Con el tope la corrida termina
    #siempre; sin él, un día de muchas altas la deja horas adentro y el cron se solapa
    #consigo mismo. `publish` saca cinco animales por corrida, así que preparar diez alcanza
    #para no dejarlo sin cola.
    MAX_POR_CORRIDA = 10

    SIN_FOTOS = "No tiene ninguna foto cargada: no hay con qué armar el posteo de Instagram."

    #instagram_error es TextField null: acá se escribe None, pero un animal viejo puede
    #tenerlo en "", así que las dos formas cuentan como "sin problemas"
    SIN_ERROR = Q(instagram_error__isnull=True) | Q(instagram_error="")

    def animales_a_preparar(self):
        """La cola: los que ya cumplieron la demora y todavía no están listos.

        Mismos permisos que el cron `publish`, porque preparar es el paso justo antes de
        publicar: sin mirar aprobado y estado, se armarían imágenes de animales que nunca
        se aprobaron o que ya se adoptaron.

        Lo que la revisión automática marcó con 'R' no se prepara: aprobado=True no
        garantiza que un humano haya mirado (automatic_approve regala la aprobación), así
        que la ventana de cancelación y este filtro son el único gate que queda. 'E' (no se
        pudo revisar) y 'P' (sin revisar) no son sospecha y no frenan a nadie.

        Van primero los que nunca fallaron. El que falló ya no vuelve solo -la agenda se
        gasta-, pero sí cuando alguien lo reagenda desde /tools/ con "Publicar ya", y ahí
        entra como el más viejo de la cola: en orden de agenda, un puñado de animales rotos
        reagendados se come el tope de la corrida y deja sin preparar a los que se
        aprobaron hoy. Se preparan igual, con lo que sobre del tope.
        """

        return Animal.objects.filter(
            instagram_programado_para__lte=timezone.now(),
            instagram_publicado=False,
            aprobado=True,
            estado__in=["D", "R"],
        ).exclude(
            revision_ia_estado=Animal.REVISION_REVISAR,
        ).annotate(
            _ya_fallo=Case(
                When(self.SIN_ERROR, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        ).order_by("_ya_fallo", "instagram_programado_para", "id")

    def fotos_del_posteo(self, animal):
        """Las fotos que van a salir, en el orden en que salen.

        Instagram no publica más de MAX_IMAGENES_POR_POST y `publish` corta en ese mismo
        tope, así que armar la foto 11 de un animal con 20 es tirar el trabajo caro del
        comando: esas nunca se suben. El orden es el del posteo -get_images() ordena por
        (posicion, id)-, así que las que se arman son exactamente las que se publican.
        """

        return list(animal.get_images())[:FacebookApiService.MAX_IMAGENES_POR_POST]

    def generar_imagenes(self, animal):
        """Arma la imagen de Instagram de cada foto que todavía no la tenga.

        Devuelve (cuántas se generaron, motivos de las que fallaron). Una foto rota no
        puede dejar sin armar a las otras: el posteo sale con las que sí se pudieron.
        """

        service = ImageService()
        generadas = 0
        motivos = []

        for imagen in self.fotos_del_posteo(animal):

            #una AnimalImage sin archivo no se puede componer y tampoco es un error del
            #animal: se la saltea, igual que en optimize_images
            if not imagen.image:
                continue

            try:
                if service.generar_imagen_para_instagram(imagen):
                    generadas += 1
            except Exception as error:
                motivos.append("No se pudo armar la imagen de la foto {}: {}".format(imagen.id, error))
                logger.warning(
                    "No se pudo armar la imagen %s de %s: %s", imagen.id, animal.nombre, error,
                )

        return generadas, motivos

    def tiene_alguna_imagen(self, animal):
        """Con una sola alcanza para publicar: el resto del carrusel es opcional."""

        return any(imagen.image_for_instagram for imagen in animal.get_images())

    def consumir_agenda(self, animal):
        """Gasta la agenda: de acá en adelante el animal avanza por la marca.

        `instagram_programado_para` no se limpiaba nunca, así que una vez vencido lo
        quedaba para siempre y este cron levantaba al animal en todas las corridas. Cuando
        alguien destildaba "listo para publicar" para frenar el posteo, la corrida
        siguiente se la volvía a prender: el freno se revertía solo y el post salía igual.

        Se escribe con update() y no con save() a propósito, como el resto del pipeline:
        el post_save de Animal reescribe el desplegable de forms_builder.
        """

        if animal.instagram_programado_para is None:
            return

        Animal.objects.filter(id=animal.id).update(instagram_programado_para=None)
        animal.instagram_programado_para = None

    def marcar_listo(self, animal):
        """Lo deja en la cola de `publish` y le gasta la agenda.

        Se escribe con update() y no con save() a propósito: el post_save de Animal
        reescribe el desplegable de forms_builder, y esto corre en cada corrida.

        De paso se borra el error de la corrida anterior, que ya no describe nada. Sólo
        cuando la marca cambia: si el animal ya estaba listo, el error que tenga puesto es
        de `publish` intentando publicarlo y no es nuestro para borrar.
        """

        if not animal.instagram_listo_para_publicar:
            Animal.objects.filter(id=animal.id).update(
                instagram_listo_para_publicar=True,
                instagram_error=None,
            )
            animal.instagram_listo_para_publicar = True

        self.consumir_agenda(animal)

    def anotar_error(self, animal, motivo):
        """El motivo queda en el animal: el stdout de un cron no lo lee nadie.

        Sin esto el animal se quedaba agendado para siempre, sin salir y sin decir por qué.

        Apaga la marca, que es lo que promete el comentario de `preparar`: si el animal ya
        estaba listo de una corrida anterior y ahora una foto no se puede componer, dejarla
        prendida es publicar en la cuenta de la organización un carrusel al que le falta una
        foto que el rescatista sí cargó, sin que se entere nadie.

        Y gasta la agenda igual que cuando sale bien. Lo que falla acá falla por algo del
        animal -una foto rota, ninguna foto- y no se arregla solo: reintentarlo en cada
        corrida son varios segundos de CPU por foto para volver a fallar, y el que ya falló
        se come el cupo de los que se aprobaron hoy. Tampoco queda en un limbo mudo: queda
        con el motivo escrito, que es lo que /tools/colainstagram/ muestra en "con
        problemas", y de ahí vuelve por donde entró -"Publicar ya" lo agenda de nuevo-.
        """

        Animal.objects.filter(id=animal.id).update(
            instagram_error=motivo,
            instagram_listo_para_publicar=False,
        )
        animal.instagram_listo_para_publicar = False

        self.consumir_agenda(animal)

        self.stderr.write("{}: {}".format(animal.nombre, motivo))

    def preparar(self, animal):
        """Devuelve True si esta corrida hizo algo con este animal."""

        generadas, motivos = self.generar_imagenes(animal)

        #ya estaba preparado de una corrida anterior: no hay nada que armar ni que escribir.
        #Devolver False acá es lo que evita que los que esperan a `publish` se coman el cupo
        #de la corrida y dejen sin preparar a los que recién se aprobaron.
        if not generadas and not motivos and animal.instagram_listo_para_publicar:
            self.consumir_agenda(animal)
            return False

        #algo falló: el animal no sale hasta que alguien mire. Marcar listo con una foto
        #rota es publicar en la cuenta de la organización un carrusel al que le falta algo
        #que el rescatista sí cargó.
        if motivos:
            self.anotar_error(animal, " ".join(motivos))
            return True

        if not self.tiene_alguna_imagen(animal):
            self.anotar_error(animal, self.SIN_FOTOS)
            return True

        self.marcar_listo(animal)
        self.stdout.write("{}: listo para publicar ({} imágenes nuevas)".format(animal.nombre, generadas))

        return True

    def handle(self, *args, **options):

        #este comando es sólo el pipeline automático: lo único que trae animales acá es la
        #agenda que escribe la aprobación. Con el flag apagado no había que preparar nada y
        #se preparaba igual, así que apagarlo no frenaba lo que ya estaba agendado: las
        #imágenes se armaban y el animal quedaba marcado en la cola de `publish`.
        if not InstagramAutoService().esta_activo():
            self.stdout.write("El posteo automático está apagado: no se prepara nada.")
            logger.info("preparar_publicaciones: el posteo automático está apagado, no se prepara nada.")
            return

        preparados = 0

        for animal in self.animales_a_preparar():

            if preparados >= self.MAX_POR_CORRIDA:
                self.stdout.write("Se llegó al tope de la corrida: el resto queda para la próxima.")
                break

            try:
                hizo_algo = self.preparar(animal)
            except Exception as error:
                #un animal que falla no puede frenar a los que siguen: son todos posteos
                #distintos y el que anda no tiene por qué esperar al que no
                hizo_algo = True
                logger.warning("No se pudo preparar %s: %s", animal.nombre, error)

                #y el motivo se anota como cualquier otra falla: sin esto el fallo
                #inesperado era el único que no dejaba rastro en el animal ni gastaba la
                #agenda, o sea que se reintentaba en cada corrida, para siempre y en
                #silencio, comiéndose el cupo de los que sí se podían preparar
                self.anotar_error(animal, "No se pudo preparar el posteo: {}".format(error))

            if hizo_algo:
                preparados += 1

        self.stdout.write("Animales preparados: {}".format(preparados))
