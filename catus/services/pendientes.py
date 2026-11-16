"""La cola del equipo: los animales que esperan que una persona los apruebe, y "No publicar".

En noviembre de 2026 había 58 animales sin aprobar, 54 de antes de que existiera la revisión
con IA y 41 con más de 180 días esperando, y nadie los miraba: /tools/animalespendientes/
listaba además todo lo ya publicado o expirado (publicar en Instagram y expirar apagan
instagram_listo_para_publicar), así que lo que esperaba aprobación quedaba enterrado entre
cientos de tarjetas. Y no había forma de decir que no: lo que el equipo no quería publicar
se quedaba "En revisión" para siempre, en la cola del equipo y en el panel del rescatista.
"""
import logging
from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import Coalesce
from django.utils import timezone

from catus.models import Animal
from catus.services.instagram_auto import InstagramAutoService
from catus.services.mail import MailService

logger = logging.getLogger(__name__)

#Lo que espera aprobación está en adopción o reservado. Los adoptados no esperan nada, y
#los expirados tampoco: "No publicar" los deja en "E", así que este filtro es también lo
#que los saca de la cola. No se filtra además por no_publicar_el a propósito: si alguien
#vuelve a poner en adopción uno de esos sin pasar por la edición ("Republicar" del panel),
#la fecha queda puesta y, filtrando por ella, el animal esperaría sin que nadie lo viera.
ESTADOS_PENDIENTES = ("D", "R")

#Lo que el equipo elige al apretar "No publicar". "Otro" es escribirlo a mano.
OTRO = "Otro"
MOTIVOS_NO_PUBLICAR = (
    "No es un animal en adopción",
    "Fotos o datos insuficientes",
    "Repetido",
    OTRO,
)

#El motivo de lo que archiva el comando archivar_pendientes.
MOTIVO_SIN_REVISION = "Pasó mucho tiempo sin revisión. Si sigue en adopción, editalo y lo volvemos a mirar."

#el texto libre lo lee el rescatista en el mail y en el panel: alcanza para explicarse
MAX_DETALLE = 1000

#Dónde queda, de un request al siguiente, el aviso de lo que se acaba de hacer: aprobar
#(AprobarView) y "No publicar" redirigen a la cola después del POST, y la cola lo muestra.
AVISO_EN_SESION = "pendientes_aviso"
URL_COLA = "/tools/animalespendientes/"


class PendientesService():

    def esperando(self):
        """Los que esperan que una persona los apruebe, del que más espera al más nuevo.

        Esperan desde fecha_ingreso, que es lo que se reinicia cuando el dueño edita uno
        que no se publicó y lo devuelve a la cola (EditView). Los animales viejos pueden no
        tenerla: ahí cuenta el alta.
        """

        return Animal.objects.filter(
            aprobado=False, estado__in=ESTADOS_PENDIENTES,
        ).annotate(
            esperando_desde=Coalesce("fecha_ingreso", "created_at"),
        ).order_by("esperando_desde", "id")

    def esperando_hace_mas_de(self, dias, ahora=None):
        """Los que llevan más de `dias` días esperando. Es lo que archiva el comando."""

        ahora = ahora or timezone.now()

        return self.esperando().filter(esperando_desde__lte=ahora - timedelta(days=dias))

    def aprobados_por_persona(self, usuarios_ids):
        """{id de la cuenta: cuántos animales le aprobó una persona}, en una consulta.

        Es el historial con el que el equipo decide si confía en una cuenta: el mismo que
        cuenta el cron automatic_approve. Los que aprobó la IA sola no cuentan, por lo mismo
        que allá: un alta inocua que la IA deja pasar no dice nada de quién la cargó.
        """

        ids = {usuario_id for usuario_id in usuarios_ids if usuario_id is not None}
        if not ids:
            return {}

        filas = Animal.objects.filter(
            cargado_por_id__in=ids, aprobado=True, aprobado_por_persona=True,
        ).values("cargado_por_id").annotate(cuantos=Count("id"))

        return {fila["cargado_por_id"]: fila["cuantos"] for fila in filas}

    def armar_motivo(self, opcion, detalle):
        """El motivo que se guarda y lee el rescatista, o None si el equipo no dio ninguno.

        La opción sólo vale si es una de la lista: el form es del equipo, pero lo que llega
        en el POST lo puede escribir cualquiera. "Otro" sin texto no explica nada, así que
        no es un motivo.
        """

        opcion = (opcion or "").strip()
        if opcion not in MOTIVOS_NO_PUBLICAR or opcion == OTRO:
            opcion = ""

        detalle = " ".join((detalle or "").split())[:MAX_DETALLE]

        if opcion and detalle:
            return "{}: {}".format(opcion, detalle)

        return opcion or detalle or None

    def no_publicar(self, animal, motivo=None):
        """Lo saca de la cola (y del sitio, si estaba publicado): queda "No se publicó".

        Sin expiro_el, para que el panel no le pregunte al rescatista si sigue en adopción:
        esa tarjeta es para lo que expiró solo, y republicar con un clic es justo lo que no
        tiene que pasar acá. El camino de vuelta es editarlo (EditView), que lo devuelve a
        la cola y le avisa al equipo.

        Desaprueba también lo que estaba publicado (lo que la revisión con IA marcó después
        de una edición) y le limpia aprobado_por_persona, como el tilde del admin: retirar
        la aprobación es retirar la mirada, y si quedara puesta le seguiría contando como
        historial a la cuenta. Y cancela el posteo de Instagram por lo mismo que el tilde:
        un animal que no está en el sitio no se postea.

        save(update_fields) y no update(): el post_save sincroniza el desplegable del
        formulario público, y uno que estaba publicado tiene que salir de ahí.
        """

        ahora = timezone.now()

        animal.estado = "E"
        animal.aprobado = False
        animal.aprobado_por_persona = False
        animal.expiro_el = None
        animal.no_publicar_el = ahora
        animal.no_publicar_motivo = motivo or None
        animal.updated_at = ahora

        animal.save(update_fields=[
            "estado", "aprobado", "aprobado_por_persona", "expiro_el",
            "no_publicar_el", "no_publicar_motivo", "updated_at",
        ])

        InstagramAutoService().cancelar(animal)

    def archivar(self, dias, ahora=None):
        """Marca como no publicados a los que esperan hace más de `dias` días. Devuelve
        la lista de los que marcó.

        Un UPDATE y no un save() por animal, como expirar_animales. Acá además no hace
        falta sincronizar el desplegable del formulario público: sólo están los aprobados,
        y estos no lo están. El filtro se repite en el UPDATE por si alguien aprobó uno
        entre la consulta y esto, y los que se marcaron se reconocen por la fecha exacta,
        así a nadie le llega el mail de uno que se aprobó en el medio.
        """

        ahora = ahora or timezone.now()
        ids = list(self.esperando_hace_mas_de(dias, ahora).values_list("id", flat=True))

        if not ids:
            return []

        Animal.objects.filter(
            id__in=ids, aprobado=False, estado__in=ESTADOS_PENDIENTES,
        ).update(
            estado="E", expiro_el=None, no_publicar_el=ahora, no_publicar_motivo=MOTIVO_SIN_REVISION,
            updated_at=ahora, instagram_programado_para=None, instagram_listo_para_publicar=False,
        )

        return list(Animal.objects.filter(id__in=ids, no_publicar_el=ahora).select_related("cargado_por"))

    def avisar(self, animales, motivo, sacado_del_sitio=False):
        """Le avisa a cada rescatista con un mail por cuenta. Devuelve (avisados, sin_aviso).

        Uno por cuenta y no uno por animal: archivar_pendientes marca de a muchos, y una
        cuenta con cinco animales esperando recibía cinco mails iguales. Un mail que falla
        no puede frenar a los demás ni deshacer lo que ya se marcó.
        """

        por_cuenta = {}
        for animal in animales:
            if animal.cargado_por is None or not animal.cargado_por.email:
                continue
            por_cuenta.setdefault(animal.cargado_por_id, (animal.cargado_por, []))[1].append(animal)

        avisados = 0
        sin_aviso = 0

        for usuario, suyos in por_cuenta.values():
            try:
                MailService().send_mail_no_publicado(usuario, suyos, motivo, sacado_del_sitio=sacado_del_sitio)
                avisados += 1
            except Exception as error:
                #warning y no exception: es el proveedor de mails, algo ajeno y esperable
                sin_aviso += 1
                logger.warning("No se pudo avisar a la cuenta %s que no se publicó: %s", usuario.id, type(error).__name__)

        return avisados, sin_aviso
