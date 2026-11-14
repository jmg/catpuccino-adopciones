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

#lo que la gente escribe en Instagram o Facebook cuando no tiene, sin puntos ni guiones bajos,
#y los pedazos de link que no son una cuenta (instagram.com/p/…, /reel/…, facebook.com/share/…)
RELLENO_REDES = {
    "no", "nop", "nope", "ninguno", "ninguna", "notengo", "notiene", "noposeo", "noposee", "nouso", "nousa",
    "na", "none", "nada", "nadie", "sin", "sinredes", "noredes", "privado", "privada", "xxx", "xxxx", "xxxxx",
    "asd", "asdf", "asdasd", "test", "prueba", "instagram", "facebook", "ig", "fb",
    "p", "reel", "reels", "stories", "explore", "accounts", "tv", "share", "sharer", "people", "groups",
    "pages", "watch", "photo", "photophp", "profilephp", "storyphp", "permalinkphp", "homephp", "lphp",
}


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

        #solo lo que tiene forma de mail: uno cortado o de relleno (no@no.com) no es de nadie
        email = self._buscar(respuestas, "email")
        usuario = email.split("@")[0].lower() if "@" in email else ""
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", email) and len(usuario) >= 2 \
                and re.sub(r"[._]", "", usuario) not in RELLENO_REDES:
            persona["email"] = email[:254]

        celular = self._telefono(self._buscar(respuestas, "celular", "teléfono", "telefono"))
        if celular:
            persona["phone"] = celular

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

        Un dato que no es de una sola persona no se manda: con un match ambiguo se frena
        según la peor calificación de todos los que coinciden (decisión del 2026-11-13), así
        que "xx" en Instagram frenaría a quien sea si alguien mal calificado escribió lo mismo.
        No es una cuenta: un nombre con espacios ("Ana Pérez"), "no tengo" y parecidos, lo
        muy corto (Facebook pide 5 caracteres; en Instagram, menos de 3 es relleno), lo que no
        tiene letras, y los links que no son a un perfil (una publicación, "profile.php").
        """

        valor = (valor or "").strip()
        if not valor:
            return ""

        #facebook.com/profile.php?id=100012345: la cuenta es el número
        numero = re.search(re.escape(dominio) + r"/profile\.php\?(?:[^#\s]*&)?id=(\d{5,20})", valor)
        if numero:
            return numero.group(1)

        enlace = re.search(re.escape(dominio) + r"/([A-Za-z0-9._]+)", valor)
        if enlace:
            valor = enlace.group(1)

        valor = valor.lstrip("@").strip().strip("/")
        minimo = 5 if dominio == "facebook.com" else 3
        if not re.fullmatch(r"[A-Za-z0-9._]{%d,60}" % minimo, valor) or not re.search(r"[A-Za-z]", valor):
            return ""
        if re.sub(r"[._]", "", valor.lower()) in RELLENO_REDES:
            return ""
        return valor

    def _telefono(self, valor):
        """El celular tal como lo escribió (BuenAdoptante lo normaliza: probado con espacios,
        +54 9, 011 15, sin código de área, con texto y con dos números), o "" si no es uno:
        menos de 8 dígitos, todos iguales o 12345678. Por lo mismo que en _handle."""

        valor = (valor or "").strip()
        digitos = re.sub(r"\D", "", valor)
        if len(digitos) < 8:
            return ""
        ultimos = digitos[-8:]
        if len(set(ultimos)) == 1 or ultimos in ("12345678", "23456789", "87654321", "98765432"):
            return ""
        return valor[:200]

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

        #con nombre propio: el filtro anti-bots de BuenAdoptante (Cloudflare) contesta 403
        #"error code: 1010" a los clientes genéricos (lo hizo con el de Python), y un 403 acá
        #se reintenta sin fin mientras los formularios pasan sin revisar
        headers = {"Authorization": "Bearer {}".format(settings.BUENADOPTANTE_API_KEY), "Content-Type": "application/json",
                   "User-Agent": "CatpuccinoAdopciones/1.0 (+https://{})".format(settings.HOST)}
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

        #para el aviso de coincidencia (avisar_coincidencia), que sale en el mismo pedido:
        #no se guardan
        coincidio = perfil.get("matchedOn") or []
        actividad.coincidio_por = [str(c) for c in coincidio if isinstance(c, str)][:5] if isinstance(coincidio, list) else []
        motivo = datos.get("reason")
        actividad.motivo_ambiguo = motivo[:40] if isinstance(motivo, str) else ""

        #worstRating junta TODOS los perfiles que coincidieron por algún dato, también en un
        #match ambiguo: quien usa el celular de un familiar con 1★ queda frenado. Es a
        #propósito: el equipo lo decidió así el 2026-11-13, en vez de dejarlo pasar con aviso.
        actividad.bloqueo = actividad.tipo == "adoption_request" and self.bloquea(actividad.nivel)

    def bloquea(self, nivel):

        tope = settings.BUENADOPTANTE_BLOQUEAR_HASTA
        return bool(tope) and nivel is not None and 1 <= nivel <= tope

    #---- avisos

    def destinatarios_coincidencias(self, ademas=()):
        """A quién va el aviso de que BuenAdoptante ya conocía a la persona, sin repetidos."""

        destinatarios = []
        for direccion in list(ademas) + list(settings.BUENADOPTANTE_AVISAR_COINCIDENCIAS_A or []):
            if direccion and direccion not in destinatarios:
                destinatarios.append(direccion)
        return destinatarios

    def hubo_coincidencia(self, actividad):

        return (actividad is not None and actividad.tipo == "adoption_request" and actividad.estado == "OK"
                and actividad.match in ("found", "ambiguous"))

    def avisar_coincidencia(self, actividad):
        """Un mail por formulario cuyo adoptante BuenAdoptante ya conocía (pedido del equipo,
        para seguir de cerca cómo matchea). Si el formulario se frenó, este aviso no sale: el
        de bloqueo va a los mismos destinatarios. No levanta nada."""
        from catus.utils import send_html_email

        destinatarios = self.destinatarios_coincidencias()
        if not destinatarios or not self.hubo_coincidencia(actividad) or actividad.bloqueo:
            return False

        try:
            estado_form = actividad.estado_formulario
            animal = actividad.animal or (estado_form.gato if estado_form else None)
            persona = (estado_form.persona_nombre if estado_form else "") or ""
            if not persona and estado_form is not None:
                persona = self.persona(self.respuestas(estado_form.form_entry)).get("fullName", "")
            persona = persona or "Sin nombre"
            nombre_animal = (animal.nombre if animal else "") or "un animal"
            calificacion = CALIFICACIONES.get(actividad.nivel, "sin dato")

            subject = "BuenAdoptante ya conocía a {} ({})".format(" ".join(persona.split())[:80], calificacion)
            content = self.contenido_aviso(actividad, persona, nombre_animal, calificacion,
                                           "El formulario le llegó al rescatista como siempre.")
            send_html_email(subject, content, settings.SEND_MAIL, destinatarios)
            return True
        except Exception as e:
            logger.warning("No se pudo avisar de la coincidencia del envío %s: %s", actividad.id, type(e).__name__)
            return False

    def contenido_aviso(self, actividad, persona, nombre_animal, calificacion, que_paso):
        """El cuerpo del aviso de coincidencia (y del de bloqueo): quién, por qué dato, qué dice
        BuenAdoptante y los links. Todo lo que escribió la persona sale escapado."""
        import html

        ETIQUETAS_DATO = {"email": "el mail", "phone": "el celular", "social": "una red social", "documentId": "el documento"}
        por = ", ".join(ETIQUETAS_DATO.get(c, c) for c in getattr(actividad, "coincidio_por", []) or [])
        if actividad.match == "ambiguous":
            motivo = getattr(actividad, "motivo_ambiguo", "")
            como = ("Coincidencia ambigua: el dato es de alguien con otro nombre (por ejemplo, un celular familiar)."
                    if motivo == "name_mismatch" else "Coincidencia ambigua: varios perfiles encajan con el nombre.")
        else:
            como = "Coincidió por {}.".format(por) if por else "La encontró por sus datos de contacto."

        filas = [("Persona", html.escape(persona)), ("Animal", html.escape(nombre_animal)),
                 ("Coincidencia", html.escape(como)),
                 ("Calificación", "<b>{}</b>{}".format(html.escape(calificacion), " · {}★".format(actividad.nivel) if actividad.nivel else ""))]
        alertas = [descripcion_alerta(a) for a in actividad.get_alertas()]
        if alertas:
            filas.append(("Alertas", "<br>".join(html.escape(a) for a in alertas)))
        marcas = [descripcion_marca(m) for m in actividad.get_marcas()]
        if marcas:
            filas.append(("Marcas", "<br>".join(html.escape(m) for m in marcas)))
        filas.append(("Qué pasó", html.escape(que_paso)))

        estado_form = actividad.estado_formulario
        links = []
        if estado_form is not None:
            url = "https://{}/formularios/{}/".format(settings.HOST, estado_form.hash)
            links.append("<a href='{0}'>Ver el formulario</a>".format(html.escape(url)))
        if actividad.perfil_url:
            links.append("<a href='{0}'>Ver su perfil en BuenAdoptante</a>".format(html.escape(actividad.perfil_url)))

        cuerpo = "".join(
            "<tr><td style='padding:6px 12px 6px 0;color:#6b6f80;font-size:13px;vertical-align:top;width:32%;'>{}</td>"
            "<td style='padding:6px 0;vertical-align:top;'>{}</td></tr>".format(etiqueta, valor) for etiqueta, valor in filas)
        return (
            "<p style='margin:0 0 6px;font-size:13px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:#7020a0;'>BuenAdoptante</p>"
            "<h1 style='margin:0 0 16px;font-size:22px;line-height:1.3;color:#2d3748;'>La persona de un formulario ya figuraba en BuenAdoptante</h1>"
            "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' border='0' style='margin:0 0 16px;'>{}</table>"
            "<p style='margin:0;'>{}</p>"
        ).format(cuerpo, " · ".join(links))

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
