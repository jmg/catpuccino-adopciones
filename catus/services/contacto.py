"""Los links para contactar a quien mandó un formulario: WhatsApp, llamada y mail.

El celular y el mail los escribe cualquiera en el formulario público, así que lo que escribió
la persona no va nunca tal cual adentro de un href: del celular quedan solo los dígitos y el
mail tiene que ser un mail.
"""
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def solo_digitos(texto):
    return re.sub(r"\D", "", str(texto or ""))


def link_de_llamada(celular):
    """tel: con los dígitos como los escribió la persona, o None si eso no es un teléfono."""

    digitos = solo_digitos(celular)
    if not 8 <= len(digitos) <= 15:
        return None

    return "tel:{}{}".format("+" if str(celular).strip().startswith("+") else "", digitos)


def link_de_whatsapp(celular):
    """https://wa.me/… o None.

    WhatsApp necesita el número completo, con el código del país, y la gente lo escribe
    de mil maneras: "11 5555-4444", "15 5555 4444", "011 15 5555-4444", "+54 9 11 5555 4444".
    Solo se arma el link cuando el número se puede llevar sin adivinar a los diez dígitos
    de un celular argentino (código de área más número); si no, mejor ningún link que uno
    que abre el chat de otra persona.
    """

    texto = str(celular or "").strip()
    digitos = solo_digitos(texto)

    #de otro país, escrito con su código: va como está
    if texto.startswith("+") and not digitos.startswith("54"):
        return "https://wa.me/{}".format(digitos) if 8 <= len(digitos) <= 15 else None

    if digitos.startswith("00"):
        digitos = digitos[2:]
    if digitos.startswith("54") and len(digitos) > 10:
        digitos = digitos[2:]
    if digitos.startswith("9") and len(digitos) == 11:
        digitos = digitos[1:]
    if digitos.startswith("0"):
        digitos = digitos[1:]

    #"11 15 5555-4444": el 15 después del código de área de Buenos Aires
    if len(digitos) == 12 and digitos.startswith("1115"):
        digitos = "11" + digitos[4:]
    #"15 5555-4444", sin código de área: es de Buenos Aires, donde está casi todo el sitio
    if len(digitos) == 10 and digitos.startswith("15"):
        digitos = "11" + digitos[2:]

    if len(digitos) != 10:
        return None

    return "https://wa.me/549{}".format(digitos)


def mail_valido(mail):
    mail = str(mail or "").strip()
    try:
        validate_email(mail)
    except ValidationError:
        return None
    return mail


def contacto(celular, mail):
    """Lo que la página del formulario necesita para los botones de contacto."""

    mail = mail_valido(mail)

    return {
        "whatsapp": link_de_whatsapp(celular),
        "llamada": link_de_llamada(celular),
        "mail": "mailto:{}".format(mail) if mail else None,
    }
