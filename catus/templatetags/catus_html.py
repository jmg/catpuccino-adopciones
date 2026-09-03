"""Filtros de template propios."""
from django import template
from django.utils.safestring import mark_safe

from catus.services.html_seguro import sanitizar_html

register = template.Library()


@register.filter(name="html_seguro")
def html_seguro(valor):
    """Muestra texto enriquecido escrito por un usuario sin dejar pasar scripts.

    Reemplaza a |safe en la descripción del animal y en la del perfil: son campos
    con formato (negritas, listas, links) pero los escribe cualquiera que se
    registre, y se ven en páginas públicas.
    """

    return mark_safe(sanitizar_html(valor))
