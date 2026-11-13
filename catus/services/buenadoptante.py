"""BuenAdoptante (buenadoptante.org): el registro de adoptantes que comparten los rescates.

Qué se manda:
- cada formulario de pre-adopción, como `adoption_request`, con todas sus respuestas. Se
  manda en el momento, antes de que el formulario le llegue al rescatista: la respuesta
  dice la peor calificación de la persona y, con 1★ o 2★ (BUENADOPTANTE_BLOQUEAR_HASTA),
  el formulario se frena.
- cada adopción concretada, como `adoption`, cuando el rescatista dice quién adoptó.

Dos reglas sostienen la integración:
- **BuenAdoptante no puede frenar un formulario por estar caído.** Cualquier falla (sin
  red, lento, 5xx, cupo agotado) deja el envío pendiente y el formulario pasa como antes;
  el cron enviar_buenadoptante lo reintenta. Solo frena una respuesta que dice 1★ o 2★.
- **Nunca se registra dos veces lo mismo.** Cada envío lleva un `externalId` propio
  (catpuccino-solicitud-<hash del formulario>): un reintento devuelve la respuesta
  original. Por eso el envío se anota (ActividadBuenAdoptante) antes de mandarlo.

Las respuestas del formulario las escribe cualquiera: se mandan como datos y se recortan
a los topes de la API. Los fallos se loguean como warning y sin datos de la persona:
Jentry adjunta el request a los eventos ERROR.
"""
import json
import logging
import re
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

#etiqueta en español de cada calificación de BuenAdoptante, por ratingLevel
CALIFICACIONES = {
    0: "Sin calificar",
    1: "Peligroso",
    2: "Malo",
    3: "Regular",
    4: "Bueno",
    5: "Excelente",
}

#qué quiere decir cada alerta; un tipo nuevo se muestra con su nombre
ALERTAS = {
    "too_many_requests": "Pidió adoptar en muchos rescates distintos en poco tiempo",
    "too_many_adoptions": "Adoptó muchos animales en poco tiempo",
    "housemate_low_rating": "Convive con alguien mal calificado",
    "housemate_alerts": "Convive con alguien que tiene alertas",
}

MARCAS = {
    "duplicate": "Marcado como duplicado de otro perfil",
    "possible_duplicate": "Puede ser la misma persona que otro perfil",
}

#un formulario de pre-adopción por persona y animal: son las del sitio
TIPOS_PREADOPCION = ("A", "AP")

#topes de la API (ver /api/v1/docs)
MAX_FORM_CONTENT_BYTES = 45 * 1024
MAX_RESPUESTA = 2000

#cuántas veces reintenta el cron antes de dejar un envío por imposible
MAX_INTENTOS = 12


def descripcion_alerta(alerta):

    tipo = alerta.get("type") if isinstance(alerta, dict) else str(alerta)
    return ALERTAS.get(tipo, tipo)


def descripcion_marca(marca):

    return MARCAS.get(marca, marca)


class FallaTemporal(Exception):
    """BuenAdoptante no contestó o no pudo: se reintenta más tarde."""


class Rechazo(Exception):
    """BuenAdoptante rechazó el pedido (datos inválidos): reintentarlo no cambia nada."""


class BuenAdoptanteService:

    #conectar, leer: el envío del formulario espera esta respuesta, así que es corto. Si
    #no contesta a tiempo, el formulario pasa y el cron lo manda después.
    TIMEOUT = (3, 5)

    def activo(self):

        return bool(settings.BUENADOPTANTE_ACTIVO and settings.BUENADOPTANTE_API_KEY and settings.BUENADOPTANTE_API_URL)

    #---- datos del formulario

    def respuestas(self, form_entry):
        """{etiqueta: valor} de un FormEntry, en el orden del formulario."""
        from forms_builder.forms.models import Field

        if form_entry is None:
            return {}

        entradas = list(form_entry.fields.all())
        etiquetas = dict(Field.objects.filter(id__in=[e.field_id for e in entradas]).values_list("id", "label"))
        tipos = dict(Field.objects.filter(id__in=[e.field_id for e in entradas]).values_list("id", "field_type"))

        resultado = {}
        for entrada in entradas:
            etiqueta = etiquetas.get(entrada.field_id)
            if not etiqueta:
                continue
            valor = entrada.value or ""
            #los archivos se guardan como ruta: se manda el link, que es lo que le sirve
            if tipos.get(entrada.field_id) == 9 and valor:
                valor = "https://{}/{}".format(settings.HOST, valor)
            resultado[etiqueta.strip()] = valor[:MAX_RESPUESTA]
        return resultado

    def _buscar(self, respuestas, *claves):

        for etiqueta, valor in respuestas.items():
            normal = etiqueta.lower()
            if any(clave in normal for clave in claves) and valor and valor.strip():
                return valor.strip()
        return ""

    def persona(self, respuestas):
        """La persona del formulario, con los campos que pide /api/v1/search."""

        persona = {}

        nombre = self._buscar(respuestas, "nombre y apellido")
        if nombre:
            persona["fullName"] = nombre[:200]

        email = self._buscar(respuestas, "email")
        if email:
            persona["email"] = email[:254]

        celular = self._buscar(respuestas, "celular", "teléfono", "telefono")
        if celular:
            persona["phone"] = celular[:200]

        partes = [self._buscar(respuestas, "direccion", "dirección"), self._buscar(respuestas, "localidad"), self._buscar(respuestas, "partido")]
        direccion = ", ".join(p for p in partes if p)
        if direccion:
            persona["address"] = direccion[:300]

        redes = []
        instagram = self._handle(self._buscar(respuestas, "instagram"), "instagram.com")
        if instagram:
            redes.append({"platform": "instagram", "handle": instagram})
        facebook = self._handle(self._buscar(respuestas, "facebook"), "facebook.com")
        if facebook:
            redes.append({"platform": "facebook", "handle": facebook})
        if redes:
            persona["socials"] = redes

        return persona

    def _handle(self, valor, dominio):
        """El usuario de una red, o "" si lo que escribió no es uno.

        Un nombre con espacios ("Ana Pérez") no identifica a nadie en BuenAdoptante, y
        "no tengo" tampoco: se manda solo lo que parece una cuenta.
        """

        valor = (valor or "").strip()
        if not valor:
            return ""

        enlace = re.search(re.escape(dominio) + r"/([A-Za-z0-9._]+)", valor)
        if enlace:
            valor = enlace.group(1)

        valor = valor.lstrip("@").strip().strip("/")
        if not re.fullmatch(r"[A-Za-z0-9._]{2,60}", valor):
            return ""
        if valor.lower() in ("no", "nop", "ninguno", "ninguna", "notengo", "na", "n.a", "none"):
            return ""
        return valor

    def contenido(self, respuestas):
        """Las respuestas para formContent, dentro del tope de la API."""

        contenido = dict(respuestas)
        while contenido and len(json.dumps(contenido, ensure_ascii=False).encode()) > MAX_FORM_CONTENT_BYTES:
            #se recortan primero las respuestas más largas
            etiqueta = max(contenido, key=lambda k: len(contenido[k]))
            contenido[etiqueta] = contenido[etiqueta][: max(0, len(contenido[etiqueta]) // 2)]
        return contenido

    def especie(self, estado_form, animal):

        if animal is not None:
            return "dog" if animal.tipo == "P" else "cat"
        return "dog" if estado_form.tipo in ("AP", "TP") else "cat"

    #---- envíos

    def registrar_solicitud(self, estado_form):
        """Registra el formulario de pre-adopción y devuelve la ActividadBuenAdoptante, o
        None si la integración está apagada o el formulario no es de pre-adopción.

        No levanta nada: si BuenAdoptante falla, la actividad queda pendiente.
        """
        from catus.models import ActividadBuenAdoptante

        if not self.activo() or estado_form is None or estado_form.tipo not in TIPOS_PREADOPCION:
            return None

        try:
            actividad, _ = ActividadBuenAdoptante.objects.get_or_create(
                external_id="catpuccino-solicitud-{}".format(estado_form.hash),
                defaults={"tipo": "adoption_request", "estado_formulario": estado_form, "animal": estado_form.gato},
            )
        except Exception as e:
            logger.warning("No se pudo anotar el envío a BuenAdoptante del formulario %s: %s", estado_form.id, type(e).__name__)
            return None

        self.enviar(actividad)
        return actividad

    def registrar_adopcion(self, estado_form, animal):
        """Anota la adopción concretada para que la mande el cron. No llama a la API: el
        rescatista no tiene por qué esperarla.
        """
        from catus.models import ActividadBuenAdoptante

        if not self.activo() or estado_form is None or animal is None or estado_form.tipo not in TIPOS_PREADOPCION:
            return None

        try:
            #formulario y animal: con un mismo formulario se puede adoptar más de uno
            actividad, _ = ActividadBuenAdoptante.objects.get_or_create(
                external_id="catpuccino-adopcion-{}-{}".format(estado_form.hash, animal.id),
                defaults={"tipo": "adoption", "estado_formulario": estado_form, "animal": animal},
            )
            return actividad
        except Exception as e:
            logger.warning("No se pudo anotar la adopción del formulario %s para BuenAdoptante: %s", estado_form.id, type(e).__name__)
            return None

    def cuerpo(self, actividad):
        """El JSON de /api/v1/search para esta actividad."""

        estado_form = actividad.estado_formulario
        if estado_form is None:
            raise Rechazo("el formulario ya no existe")

        animal = actividad.animal or estado_form.gato
        respuestas = self.respuestas(estado_form.form_entry)
        persona = self.persona(respuestas)
        if not persona.get("fullName") or not any(k in persona for k in ("email", "phone", "socials")):
            raise Rechazo("el formulario no tiene nombre más email, celular o una red")

        actividad_api = {
            "activityType": actividad.tipo,
            "externalId": actividad.external_id,
            "species": self.especie(estado_form, animal),
        }
        if animal is not None and animal.nombre:
            actividad_api["animalName"] = animal.nombre[:100]

        if actividad.tipo == "adoption_request":
            fecha = estado_form.fecha_ingreso or estado_form.created_at
            actividad_api["formContent"] = self.contenido(respuestas)
        else:
            fecha = (animal.fecha_adopcion if animal is not None else None) or actividad.created_at
            if animal is not None:
                if animal.edad:
                    actividad_api["age"] = animal.edad[:40]
                if animal.sexo in ("M", "H"):
                    actividad_api["sex"] = "male" if animal.sexo == "M" else "female"
        if fecha:
            actividad_api["date"] = timezone.localtime(fecha).date().isoformat()

        return {"mode": "exact", "person": persona, "activity": actividad_api}

    def _llamar(self, cuerpo):

        headers = {"Authorization": "Bearer {}".format(settings.BUENADOPTANTE_API_KEY), "Content-Type": "application/json"}
        if settings.BUENADOPTANTE_DRY_RUN:
            headers["X-Dry-Run"] = "1"

        try:
            respuesta = requests.post("{}/api/v1/search".format(settings.BUENADOPTANTE_API_URL), json=cuerpo,
                                      headers=headers, timeout=self.TIMEOUT)
        except requests.RequestException as e:
            raise FallaTemporal(type(e).__name__)

        try:
            datos = respuesta.json()
        except ValueError:
            datos = {}

        if respuesta.status_code == 200:
            return datos

        codigo = (datos.get("error") or {}).get("code") if isinstance(datos.get("error"), dict) else datos.get("error")

        #el mismo externalId ya está guardado con otro contenido (por ejemplo, la persona
        #corrigió algo y se reintentó): lo guardado es lo que vale
        if respuesta.status_code == 409:
            return dict(datos, _ya_guardado=True)

        #clave mal, de otro ambiente o revocada, cupo del día, BuenAdoptante caído: puede
        #arreglarse solo o al cambiar la config, así que se reintenta
        if respuesta.status_code in (401, 403, 429) or respuesta.status_code >= 500:
            raise FallaTemporal("HTTP {} {}".format(respuesta.status_code, codigo or "").strip())

        raise Rechazo("HTTP {} {}".format(respuesta.status_code, codigo or "").strip())

    def enviar(self, actividad):
        """Manda una actividad y guarda lo que contestó. Devuelve True si quedó enviada.

        No levanta nada. Decide el bloqueo del formulario, pero no lo aplica: eso lo hace
        quien lo llamó (el envío del formulario, o el cron, que en vez de frenarlo avisa).
        """

        actividad.intentos += 1
        actividad.ultimo_intento = timezone.now()

        try:
            datos = self._llamar(self.cuerpo(actividad))
        except FallaTemporal as e:
            actividad.error = str(e)[:255]
            actividad.estado = "E" if actividad.intentos >= MAX_INTENTOS else "P"
            logger.warning("BuenAdoptante no contestó el envío %s (intento %s): %s", actividad.id, actividad.intentos, e)
            self._guardar(actividad)
            return False
        except Rechazo as e:
            actividad.error = str(e)[:255]
            actividad.estado = "E"
            logger.warning("BuenAdoptante rechazó el envío %s: %s", actividad.id, e)
            self._guardar(actividad)
            return False
        except Exception as e:
            actividad.error = type(e).__name__
            actividad.estado = "E" if actividad.intentos >= MAX_INTENTOS else "P"
            logger.warning("No se pudo armar o mandar el envío %s a BuenAdoptante: %s", actividad.id, type(e).__name__)
            self._guardar(actividad)
            return False

        self.leer_respuesta(actividad, datos)
        actividad.estado = "OK"
        actividad.error = None
        self._guardar(actividad)
        return True

    def leer_respuesta(self, actividad, datos):

        riesgo = datos.get("risk") or {}
        peor = riesgo.get("worstRating") or {}
        nivel = peor.get("ratingLevel")
        perfil = datos.get("profile") or {}
        guardado = datos.get("saved") or {}

        actividad.match = (datos.get("match") or "")[:20] or None
        actividad.nivel = nivel if isinstance(nivel, int) and 0 <= nivel <= 5 else None
        actividad.marcas = json.dumps([m for m in (riesgo.get("flags") or []) if isinstance(m, str)][:20])
        actividad.alertas = json.dumps([a for a in (riesgo.get("alerts") or []) if isinstance(a, dict)][:20])
        url = perfil.get("url") or guardado.get("profileUrl") or ""
        if url.startswith("https://"):
            actividad.perfil_url = url[:255]
        activity_id = guardado.get("activityId") or datos.get("activityId")
        if activity_id:
            actividad.activity_id = str(activity_id)[:64]

        actividad.bloqueo = actividad.tipo == "adoption_request" and self.bloquea(actividad.nivel)

    def bloquea(self, nivel):

        tope = settings.BUENADOPTANTE_BLOQUEAR_HASTA
        return bool(tope) and nivel is not None and 1 <= nivel <= tope

    def _guardar(self, actividad):

        try:
            actividad.save()
        except Exception as e:
            logger.warning("No se pudo guardar el envío a BuenAdoptante %s: %s", actividad.id, type(e).__name__)

    #---- el cron

    def pendientes(self, limite):
        """Los envíos pendientes cuyo reintento ya toca, del más viejo al más nuevo.

        Entre intentos se espera cada vez más (15 min, 30, 45...): con BuenAdoptante caído
        o el cupo del día agotado, insistir cada vez no sirve.
        """
        from catus.models import ActividadBuenAdoptante

        ahora = timezone.now()
        listos = []
        for actividad in ActividadBuenAdoptante.objects.filter(estado="P").select_related("estado_formulario", "animal").order_by("id"):
            espera = timedelta(minutes=15 * actividad.intentos)
            if actividad.ultimo_intento is None or actividad.ultimo_intento + espera <= ahora:
                listos.append(actividad)
            if len(listos) >= limite:
                break
        return listos
