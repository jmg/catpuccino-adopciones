"""Que ningún animal quede sin veredicto de la revisión con IA.

La regla (pedida el 18/11/2026): la IA aprueba lo que está bien y lo que marca le llega por
mail a quien revisa (settings.AVISOS_DE_REVISION_A). La revisión del alta ya hacía las dos
cosas, pero tenía un tercer resultado, 'E' ("no se pudo revisar": OpenAI caída, sin crédito,
el tope del día, la revisión apagada), que no es un veredicto: sin historial el animal quedaba
esperando a una persona sin que nadie se enterara. El 1532 esperó nueve días así.

Tres caminos llegan acá:

- `reintentar()`, que corre cada hora desde el cron automatic_approve: vuelve a revisar lo que
  quedó en 'E'. OK aprueba lo que esperaba (como un alta, y se agenda para Instagram); R le
  avisa a quien revisa; otro 'E' suma un intento, y al llegar a MAX_INTENTOS (un día) deja de
  intentar y le avisa que no se pudo. También revisa los que el historial aprobó con 'E': siguen
  publicados, pero si la IA los marca llega el mail y no salen a Instagram.
- `despues_de_editar()`, desde EditView cuando el dueño cambia lo revisable de un animal ya
  cargado: si la revisión nueva da OK y el animal esperaba, se aprueba; si lo marca, llega el
  mail (una vez, al pasar a marcado).
- `avisar_al_cargar()`, que decide si el alta que no se aprobó sola manda el mail ya: sí si la
  IA lo marcó, no si no pudo revisar (el cron lo reintenta en menos de una hora, y si tampoco
  puede avisa él), salvo con la revisión apagada, que no reintenta nadie.

Lo que nunca aprueba la IA: lo que una persona ya decidió no publicar y su dueño devolvió a la
cola (Animal.espera_a_una_persona). Y lo que el equipo marcó "No publicar" no se toca.
"""
import logging

from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

#un intento por hora desde el cron: un día
MAX_INTENTOS = 24

#cuántos animales revisa una corrida, para que el cron termine en sus 10 minutos aunque OpenAI
#tarde los 8 s de timeout en cada uno. Los que quedan los toma la corrida siguiente.
POR_CORRIDA = 20

EN_ADOPCION = ("D", "R")


def a_reintentar():
    """Los animales en adopción con la revisión en 'E' que todavía tienen intentos.

    Afuera lo que ya decidió o va a decidir una persona: lo que aprobó una persona (en
    producción, los 11 de la cuenta 552 que se aprobaron a mano el 11/11 con la revisión sin
    cupo: revisarlos de nuevo sólo podía mandar un mail sobre algo que una persona ya miró), lo
    que espera a una persona y lo que el equipo marcó "No publicar" (no_publicar_el con el
    animal sin aprobar). Primero los que hace más que no se intentan.
    """
    from catus.models import Animal

    return Animal.objects.filter(
        revision_ia_estado=Animal.REVISION_ERROR,
        estado__in=EN_ADOPCION,
        espera_a_una_persona=False,
        aprobado_por_persona=False,
        revision_ia_intentos__lt=MAX_INTENTOS,
    ).exclude(
        aprobado=False, no_publicar_el__isnull=False,
    ).order_by(F("revision_ia_fecha").asc(nulls_first=True), "id")


def puede_aprobarla_la_ia(animal):
    """Si este animal está esperando una aprobación que puede dar la IA."""

    return (
        not animal.aprobado
        and animal.estado in EN_ADOPCION
        and not animal.espera_a_una_persona
        and animal.no_publicar_el is None
    )


def aprobar_por_ia(animal, avisar_al_rescatista=False):
    """La aprobación de la IA, igual que en el alta: sin aprobado_por_persona (no es
    historial), agendada para Instagram con la demora de siempre. fecha_ingreso pasa a ahora:
    es desde cuándo está publicado, y de ahí corre su mes (expirar_animales).

    Se relee el animal antes: la revisión pudo tardar hasta 8 s y en ese rato una persona pudo
    haberlo aprobado o marcado "No publicar". save(update_fields) y no update(): el post_save
    con `aprobado` es el que lo pone en el desplegable del formulario.

    `avisar_al_rescatista`: el cron aprueba cuando quien lo cargó ya no está mirando la
    pantalla, que le dijo "estamos revisando la publicación"; le llega el mismo mail que cuando
    lo aprueba el equipo.
    """
    from catus.services.instagram_auto import InstagramAutoService
    from catus.services.mail import MailService

    animal.refresh_from_db()
    if not puede_aprobarla_la_ia(animal):
        return False

    animal.aprobado = True
    animal.fecha_ingreso = timezone.now()
    animal.save(update_fields=["aprobado", "fecha_ingreso"])

    InstagramAutoService().agendar(animal)

    if avisar_al_rescatista:
        try:
            MailService().send_mail_aprobacion(animal)
        except Exception as error:
            logger.warning("No se pudo avisar de la aprobación de %s: %s", animal.id, type(error).__name__)

    return True


def avisar(animal, caso):
    """El mail a quien revisa. Un fallo del mail no deshace nada de lo que ya pasó."""
    from catus.services.mail import MailService

    try:
        MailService().send_new_animal_mail(animal, caso=caso)
        return True
    except Exception as error:
        logger.warning("No se pudo avisar de la revisión de %s: %s", animal.id, type(error).__name__)
        return False


def avisar_al_cargar(veredicto, moderacion):
    """Si el alta que no se aprobó sola manda ya el mail a quien revisa."""
    from catus.models import Animal

    if veredicto != Animal.REVISION_ERROR:
        return True

    #sin la revisión prendida el cron no reintenta nada: es el mundo de antes, en el que
    #todo lo que espera le llega a una persona en el momento
    return not moderacion.esta_activa()


def _poner_intentos(animal, valor):

    from catus.models import Animal

    Animal.objects.filter(id=animal.id).update(revision_ia_intentos=valor)
    animal.revision_ia_intentos = valor


def despues_de_editar(animal, antes, veredicto):
    """Lo que sigue a la re-revisión de una edición. Devuelve True si lo aprobó.

    `antes` es el estado de la revisión antes de editar. Lo que el dueño editó es contenido
    nuevo: los intentos vuelven a 0. Una marca avisa sólo al aparecer, para que alguien que
    edita diez veces una publicación marcada no mande diez mails.
    """
    from catus.models import Animal
    from catus.services.mail import MailService

    if animal.revision_ia_intentos:
        _poner_intentos(animal, 0)

    if veredicto == Animal.REVISION_OK and puede_aprobarla_la_ia(animal):
        #quien lo cargó está en la pantalla: ve el aviso del panel, no hace falta el mail
        return aprobar_por_ia(animal)

    if veredicto == Animal.REVISION_REVISAR and antes != Animal.REVISION_REVISAR and not animal.espera_a_una_persona:
        avisar(animal, MailService.AVISO_MARCADO)

    return False


def reintentar(moderacion=None):
    """Una pasada del cron. Devuelve los ids por resultado (sin nombres ni mails)."""
    from catus.models import Animal
    from catus.services.mail import MailService
    from catus.services.moderacion import ModeracionService

    moderacion = moderacion or ModeracionService()
    resumen = {"aprobados": [], "ok": [], "marcados": [], "siguen_sin_poder": [], "sin_revision": [],
               "esperan_cupo": []}

    if not moderacion.esta_activa():
        resumen["apagada"] = True
        return resumen

    for animal in list(a_reintentar()[:POR_CORRIDA]):

        try:
            #con el tope de todos alcanzado no tiene sentido seguir: los que quedan esperan a
            #mañana sin gastar intentos, que son para fallas de la revisión y no del cupo
            if moderacion.paso_el_limite_total():
                break

            #el cupo de la persona tampoco gasta intentos: vuelve a tener al día siguiente
            if moderacion.paso_el_limite(animal.cargado_por):
                resumen["esperan_cupo"].append(animal.id)
                continue

            veredicto = moderacion.revisar_y_guardar(animal)

            if veredicto == Animal.REVISION_OK:
                _poner_intentos(animal, 0)
                if puede_aprobarla_la_ia(animal) and aprobar_por_ia(animal, avisar_al_rescatista=True):
                    resumen["aprobados"].append(animal.id)
                else:
                    resumen["ok"].append(animal.id)

            elif veredicto == Animal.REVISION_REVISAR:
                _poner_intentos(animal, 0)
                avisar(animal, MailService.AVISO_MARCADO)
                resumen["marcados"].append(animal.id)

            else:
                Animal.objects.filter(id=animal.id).update(revision_ia_intentos=F("revision_ia_intentos") + 1)
                animal.refresh_from_db(fields=["revision_ia_intentos", "aprobado"])

                if animal.revision_ia_intentos >= MAX_INTENTOS:
                    #los que aprobó el historial ya tienen quién decidió: siguen publicados
                    if not animal.aprobado:
                        avisar(animal, MailService.AVISO_SIN_REVISION)
                    resumen["sin_revision"].append(animal.id)
                else:
                    resumen["siguen_sin_poder"].append(animal.id)

        except Exception as error:
            #un animal con un problema no corta la corrida de los demás
            logger.warning("No se pudo reintentar la revisión de %s: %s", animal.id, type(error).__name__)

    return resumen
