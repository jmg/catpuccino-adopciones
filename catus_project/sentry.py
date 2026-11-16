"""Lo que se le saca a cada evento antes de mandarlo a Jentry (compatible con Sentry).

Los formularios del sitio son datos personales: el de pre-adopción (nombre, dirección,
celular, fotos de la casa) y el contrato (DNI). Con send_default_pii=True el SDK mandaba en
cada error el cuerpo del POST, las cookies (la de sesión incluida) y el usuario con su mail.
settings.py ya no le pide nada de eso al SDK; esto es lo que queda, por si algo lo trae
igual: para arreglar un error alcanzan el stack trace, la ruta y el método.

No importa nada de Django: lo usa settings.py antes de que haya apps.
"""
import re

#los headers que abren la sesión de alguien o dicen desde dónde se conecta
HEADERS_SENSIBLES = frozenset({
    "cookie", "authorization", "proxy-authorization", "x-csrftoken", "x-forwarded-for", "x-real-ip",
})

#lo que no se guarda nunca del pedido: el cuerpo, las cookies, la query string (los links
#de los mails llevan datos) y el entorno (la IP)
PARTES_DEL_PEDIDO = ("data", "cookies", "query_string", "env")

#Los links que son el permiso: el contrato lo abre quien tenga el link, sin cuenta, y lo
#mismo /postularme/. El de /formularios/ pide cuenta, pero va por mail. En el evento queda
#la ruta, sin el hash.
LINKS_CON_PERMISO = re.compile(r"(/(?:contrato|postularme|formularios)/)[^/?#]+")

MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _sin_mails(valor):

    if isinstance(valor, str):
        return MAIL.sub("[mail]", valor)
    return valor


def _sin_mails_en(datos, *claves):

    for clave in claves:
        if clave in datos:
            datos[clave] = _sin_mails(datos[clave])


def _limpiar_datos_http(datos):
    """Los pedidos que hace el sitio (Graph, OpenAI, SendGrid) quedan como breadcrumbs y
    spans con la URL y su query string, y a Graph el token va en la query string."""

    if not isinstance(datos, dict):
        return
    datos.pop("http.query", None)
    datos.pop("http.fragment", None)
    if isinstance(datos.get("url"), str):
        datos["url"] = datos["url"].split("?", 1)[0].split("#", 1)[0]


def sin_datos_personales(event, hint=None):
    """before_send y before_send_transaction de sentry_sdk.init (settings.py)."""

    request = event.get("request")
    if isinstance(request, dict):
        for parte in PARTES_DEL_PEDIDO:
            request.pop(parte, None)

        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {k: v for k, v in headers.items() if str(k).lower() not in HEADERS_SENSIBLES}

        if isinstance(request.get("url"), str):
            request["url"] = LINKS_CON_PERMISO.sub(r"\1[link]", request["url"].split("?", 1)[0])

    #de quién es el error se sabe por el id; el mail, el usuario y la IP sobran
    user = event.get("user")
    if isinstance(user, dict):
        if user.get("id") is not None:
            event["user"] = {"id": user["id"]}
        else:
            event.pop("user", None)

    #los logs del sitio a veces nombran el mail de quien completó un formulario
    _sin_mails_en(event, "message")

    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        _sin_mails_en(logentry, "message", "formatted")
        if isinstance(logentry.get("params"), (list, tuple)):
            logentry["params"] = [_sin_mails(param) for param in logentry["params"]]

    for excepcion in (event.get("exception") or {}).get("values") or []:
        if isinstance(excepcion, dict):
            _sin_mails_en(excepcion, "value")

    migas = event.get("breadcrumbs")
    if isinstance(migas, dict):
        migas = migas.get("values")
    for miga in migas or []:
        if isinstance(miga, dict):
            _sin_mails_en(miga, "message")
            _limpiar_datos_http(miga.get("data"))

    for span in event.get("spans") or []:
        if isinstance(span, dict):
            _limpiar_datos_http(span.get("data"))

    return event
