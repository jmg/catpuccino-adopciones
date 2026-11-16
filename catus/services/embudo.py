"""El embudo del formulario de pre-adopción: contadores por día, especie y paso.

Los pasos del navegador (abrió, aceptó los requisitos, empezó, quiso enviar con faltantes,
lo envió) los manda preadoption.html con sendBeacon a /pre-adopcion/paso/, una vez por
pestaña y paso; los del servidor (llegó, lo frenó BuenAdoptante, lo rechazó) los cuenta
PreAdoptionView. Contar nunca puede hacer fallar el formulario: los errores se loguean y
se sigue.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from catus.models import PasoFormulario

logger = logging.getLogger(__name__)

PASOS_DEL_NAVEGADOR = ("abrio", "requisitos", "empezo", "faltantes", "intento")
PASOS_DEL_SERVIDOR = ("enviado", "frenado", "rechazado")
ESPECIES = {"gato": "G", "perro": "P"}


def contar(especie, paso):
    """Suma uno al paso de hoy. `especie` es "G"/"P" o "gato"/"perro"."""
    especie = ESPECIES.get(especie, especie)
    if especie not in ("G", "P") or paso not in PASOS_DEL_NAVEGADOR + PASOS_DEL_SERVIDOR:
        return
    filtro = {"fecha": timezone.localdate(), "especie": especie, "paso": paso}
    try:
        if PasoFormulario.objects.filter(**filtro).update(n=F("n") + 1):
            return
        try:
            with transaction.atomic():
                PasoFormulario.objects.create(n=1, **filtro)
        except IntegrityError:
            #otro pedido creó la fila en el medio
            PasoFormulario.objects.filter(**filtro).update(n=F("n") + 1)
    except Exception as error:
        logger.warning("No se pudo contar el paso %s del formulario: %s", paso, type(error).__name__)


def resumen(dias=30):
    """Por especie, los totales de los últimos `dias` días en el orden del embudo, con el
    porcentaje de los que abrieron el formulario."""
    desde = timezone.localdate() - timedelta(days=dias - 1)
    totales = {
        (especie, paso): n for especie, paso, n in
        PasoFormulario.objects.filter(fecha__gte=desde).values_list("especie", "paso")
        .annotate(total=Sum("n")).values_list("especie", "paso", "total")
    }
    salida = []
    for especie, nombre in (("G", "Gatos"), ("P", "Perros")):
        abrieron = totales.get((especie, "abrio"), 0)
        pasos = []
        for paso, descripcion in PasoFormulario.PASOS:
            n = totales.get((especie, paso), 0)
            pasos.append({"paso": paso, "descripcion": descripcion, "n": n,
                          "porcentaje": round(100 * n / abrieron) if abrieron else None})
        salida.append({"especie": nombre, "pasos": pasos, "abrieron": abrieron})
    return salida
