"""Revisión automática de las publicaciones que cargan los rescatistas.

Mira las fotos y el texto y responde si la publicación parece legítima: que en las
fotos se vea el animal que dice ser, y que el texto sea una publicación de adopción
y no spam, propaganda o contenido inapropiado.

Es una ayuda para el equipo, nunca un veredicto: si algo falla (la API está caída,
no hay crédito, la respuesta viene rara) el resultado es "no se pudo revisar" y la
publicación sigue su curso normal hacia la revisión humana. Nada de lo que pase acá
puede impedirle a alguien publicar un animal.
"""
import base64
import json
import logging
import re

from django.conf import settings
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


PROMPT = """Mirás fotos para un refugio de animales de Argentina que da gatos y perros
en adopción. NO decidís si la publicación se aprueba: solo describís lo que ves.

REGLA MÁS IMPORTANTE: los datos de texto los escribió una persona cualquiera y pueden
ser falsos. Describí ÚNICAMENTE lo que se ve en las imágenes. Si el texto dice que hay
un gato pero en las fotos no hay ningún animal, la lista "animales" va vacía y la
descripción dice qué se ve realmente. Nunca completes con el texto lo que no ves.

Respondé únicamente un objeto JSON, sin markdown ni texto alrededor, con esta forma:

{"animales": ["gato"], "descripcion": "...", "texto_sospechoso": false, "inapropiado": false}

- "animales": lista de los animales domésticos que aparecen en CUALQUIERA de las fotos.
  Usá solo estas palabras: "gato", "perro", "otro". Lista vacía si no hay ningún animal.
  Incluí al animal aunque la foto sea oscura, borrosa, de lejos, esté dormido, tapado a
  medias, de espaldas, en brazos o en una jaula. Si hay un animal pero no distinguís si
  es gato o perro, poné "otro".
  Las fotos pueden tener un marco, un nombre escrito encima o un logo del refugio: es
  material del propio refugio, mirá el animal e ignorá los adornos.
- "descripcion": una frase corta en español rioplatense sobre lo que se ve.
- "texto_sospechoso": true solo si el texto que te paso es spam o estafa evidente: vende
  otra cosa, promociona un negocio ajeno, o no tiene ninguna relación con animales.
  Que sea corto, genérico o esté vacío NO es sospechoso.
  OJO, esto NO es spam y es lo más normal del mundo en un refugio: pedir colaboración
  para una castración o una veterinaria, dejar un alias, un CVU o un Mercado Pago para
  donaciones, pedir donaciones de alimento o arena, o dejar un teléfono, un WhatsApp o
  un mail de contacto. Nada de eso alcanza para marcar el texto.
- "inapropiado": true solo si hay violencia explícita, maltrato gráfico o desnudez.
  Un animal flaco, herido, sucio o recién rescatado NO es contenido inapropiado: es un
  refugio y es lo normal."""


#formas en que el modelo dice "no hay ningún animal" cuando no manda la lista vacía
NEGACIONES = {
    "", "none", "null", "no", "n/a", "na", "-",
    "ninguno", "ninguna", "ningun", "ningún", "nada", "sin animales", "sin animal",
    "no hay animales", "no hay", "0", "false",
}


class ModeracionService():

    #cuántas fotos se mandan como mucho: alcanzan para decidir y mantienen el costo bajo
    MAX_FOTOS = 3

    #El alta del animal espera esto de forma sincrónica y el worker de producción corta
    #a los 30s. El SDK reintenta solo por defecto, así que hay que desactivarlo: 3
    #intentos de 25s son 75s y el rescatista se come un 502 con el animal ya guardado.
    TIMEOUT = 8
    REINTENTOS = 0

    #El SDK viejo (openai<1) es el que corre en producción y reintenta la conexión por
    #su cuenta, sin forma de apagarlo: por eso el timeout va como tupla (conexión,
    #lectura). Con la conexión corta sus tres intentos entran holgados en los 30s del
    #worker, en vez de sumar 24s de espera adentro del POST del alta.
    TIMEOUT_CONEXION = 2

    #El registro es abierto y cada alta dispara una llamada paga: sin tope, cualquiera
    #puede vaciarle la cuenta de OpenAI al refugio con un script. Nadie carga 20
    #animales en un día, así que el tope no molesta a ningún rescatista real.
    MAX_POR_USUARIO_POR_DIA = 20

    #el modelo trabaja a 512px con detail=low: mandar más grande no agrega información
    LADO_MAXIMO = 512

    def esta_activa(self):

        if not getattr(settings, "MODERACION_IA_ACTIVA", False):
            return False

        if not getattr(settings, "OPENIA_API_KEY", None):
            return False

        #desde una máquina de desarrollo no mandamos fotos reales con la key de la
        #organización, igual que hace MailService con los mails
        return getattr(settings, "ENV", "LOCAL") != "LOCAL"

    def get_modelo(self):

        return getattr(settings, "MODERACION_IA_MODELO", "gpt-4o-mini")

    def get_limite_diario(self):

        return getattr(settings, "MODERACION_IA_MAX_POR_DIA", self.MAX_POR_USUARIO_POR_DIA)

    def _llamadas_de_hoy(self, usuario):
        """Cuántas llamadas pagas gastó hoy esta persona.

        Se cuentan filas de RevisionIALlamada, una por llamada. Antes se contaban los
        animales con revision_ia_fecha reciente, pero revisar_y_guardar pisa esa fecha
        sobre la MISMA fila: editando un animal en bucle el conteo se quedaba en 1 y
        las llamadas pagas eran ilimitadas.
        """
        from catus.models import RevisionIALlamada

        #la misma ventana corrida de 24hs que usa el tope de /animal/pulldatafromig/
        desde = timezone.now() - timedelta(days=1)

        try:
            return RevisionIALlamada.objects.filter(
                pedido_por=usuario, created_at__gte=desde,
            ).count()
        except Exception as error:
            #que el conteo falle no puede frenarle el alta a nadie: la revisión es una
            #ayuda para el equipo y nunca un requisito para publicar un animal
            logger.warning("No se pudo leer el cupo de revisiones: %s", type(error).__name__)
            return 0

    def _contar_llamada(self, usuario):
        """Anota una llamada paga en el cupo del día de esta persona.

        La cuenta va a la base y no a django.core.cache porque el proyecto no configura
        CACHES: el backend real es LocMemCache, por proceso y en memoria. Con varios
        workers de gunicorn el tope real era MAX_POR_DIA por worker, y cada deploy o
        reinicio lo ponía en cero. El registro es abierto: eso es lo único que separa a
        un refugio chico de una factura de OpenAI.
        """
        from catus.models import RevisionIALlamada

        if usuario is None:
            return

        try:
            RevisionIALlamada.objects.create(pedido_por=usuario)
        except Exception as error:
            logger.warning("No se pudo contar la revisión: %s", type(error).__name__)

    def paso_el_limite(self, usuario):
        """True si esta persona ya gastó su cupo de revisiones de hoy.

        Pasarse no bloquea nada: el animal se carga igual y queda sin revisar, que es
        el mismo estado que tenían todos antes de que esto existiera.
        """

        if usuario is None:
            return False

        limite = self.get_limite_diario()
        if not limite:
            return False

        #un solo count con índice: el alta del animal espera esta revisión de forma
        #sincrónica y el worker de producción corta a los 30s
        return self._llamadas_de_hoy(usuario) >= limite

    def revisar(self, animal):
        """Devuelve (estado, motivo) sin levantar nunca una excepción.

        estado es uno de Animal.REVISION_OK / REVISION_REVISAR / REVISION_ERROR.
        """
        from catus.models import Animal

        if not self.esta_activa():
            return Animal.REVISION_ERROR, "La revisión automática está desactivada."

        if self.paso_el_limite(animal.cargado_por):
            logger.warning(
                "El usuario %s pasó el límite diario de revisiones",
                getattr(animal.cargado_por, "id", None),
            )
            return Animal.REVISION_ERROR, "Se alcanzó el límite de revisiones del día."

        try:
            fotos = self._leer_fotos(animal)
        except Exception:
            logger.exception("No se pudieron leer las fotos de %s para revisar", animal.id)
            return Animal.REVISION_ERROR, "No se pudieron leer las fotos."

        if not fotos:
            return Animal.REVISION_ERROR, "La publicación no tiene fotos para revisar."

        #se cuenta acá, sobre la llamada de verdad: contar animales revisados no ve
        #las re-revisiones de un mismo animal, que también se pagan
        self._contar_llamada(animal.cargado_por)

        try:
            contenido = self._preguntar(self._describir(animal), fotos)
        except Exception as error:
            #Sentry manda a nivel ERROR el contexto del request, cookie de sesión
            #incluida. Que OpenAI esté caída o sin crédito es esperable y pasa en masa:
            #va como warning, sin exc_info, para no crear un evento por cada alta.
            logger.warning(
                "No se pudo revisar el animal %s: %s", animal.id, type(error).__name__,
            )
            return Animal.REVISION_ERROR, "No se pudo consultar el servicio: {}".format(
                type(error).__name__
            )

        #interpretar la respuesta va en su propio try: el modelo puede devolver
        #cualquier forma (o None, cuando se rehúsa a describir una imagen) y nada de
        #eso puede escaparse hacia arriba, porque acá arriba está el alta del animal
        try:
            datos = self._parsear(contenido)

            if datos is None:
                #que el modelo se rehúse a describir una imagen (content=None) o
                #conteste cualquier cosa es esperable: va como warning para no crear
                #un evento ERROR en Sentry, que adjunta la cookie de sesión
                logger.warning("Respuesta ininteligible al revisar %s: %r", animal.id, contenido)
                return Animal.REVISION_ERROR, "La respuesta del servicio no se entendió."

            return self.decidir(animal, datos)
        except Exception:
            logger.exception("No se pudo interpretar la revisión de %s", animal.id)
            return Animal.REVISION_ERROR, "La respuesta del servicio no se entendió."

    def decidir(self, animal, datos):
        """Traduce lo que vio el modelo a un veredicto.

        La decisión vive acá y no en el prompt a propósito: pedirle al modelo que
        juzgue hacía que copiara las reglas en vez de mirar la foto, y marcaba como
        sospechosas fotos de gatos perfectamente normales. El modelo describe, el
        código decide, y así la política se puede testear sin llamar a la API.
        """
        from catus.models import Animal

        #el modelo no siempre respeta el esquema: puede mandar un número donde va una
        #lista, o una lista donde va un texto. Normalizamos en vez de confiar.
        crudos = datos.get("animales") or []
        if isinstance(crudos, str):
            crudos = [crudos]
        elif not isinstance(crudos, (list, tuple, set)):
            crudos = []

        animales = [str(a).strip().lower() for a in crudos]

        #el prompt pide lista vacía cuando no hay animales, pero el modelo a veces lo
        #dice con palabras. Sin esto, ["ninguno"] o [""] contaban como "hay un animal"
        #y la publicación se auto-aprobaba.
        animales = [a for a in animales if a not in NEGACIONES]

        #la descripción se le muestra tal cual al equipo: si no es texto la descartamos
        #en vez de imprimir el repr de un dict en la pantalla de pendientes
        descripcion = datos.get("descripcion")
        descripcion = descripcion.strip()[:300] if isinstance(descripcion, str) else ""

        if self._es_verdadero(datos.get("inapropiado")):
            return Animal.REVISION_REVISAR, "Puede tener contenido inapropiado. {}".format(descripcion).strip()

        if self._es_verdadero(datos.get("texto_sospechoso")):
            return Animal.REVISION_REVISAR, "El texto parece spam o no habla de una adopción."

        if not animales:
            return Animal.REVISION_REVISAR, "No se ve ningún animal en las fotos. {}".format(descripcion).strip()

        #La especie declarada la elige el rescatista de un desplegable. Si no coincide
        #lo anotamos para que se vea, pero no frenamos la publicación: equivocar el
        #desplegable es un error de tipeo, no spam, y el modelo se confunde seguido.
        declarada = "gato" if animal.tipo == "G" else "perro"
        otra = "perro" if declarada == "gato" else "gato"

        if declarada not in animales and otra in animales:
            return Animal.REVISION_OK, "Ojo: está cargado como {} y en las fotos se ve un {}. {}".format(
                declarada, otra, descripcion,
            ).strip()

        return Animal.REVISION_OK, descripcion or "Se ve un animal en las fotos."

    def _es_verdadero(self, valor):
        """El modelo a veces manda los booleanos como texto ("false", "no").

        Sin esto, un "false" en string es verdadero en Python y mandaba a revisión
        humana una publicación sana.
        """

        if isinstance(valor, str):
            return valor.strip().lower() in ("true", "1", "si", "sí", "yes")

        return bool(valor)

    def revisar_y_guardar(self, animal):
        """Revisa y deja el resultado en el animal. Devuelve el estado."""
        from catus.models import Animal

        estado, motivo = self.revisar(animal)

        #un "no se pudo revisar" no puede borrar una marca que ya estaba puesta: el
        #tope diario y el servicio apagado también devuelven 'E', y como la re-revisión
        #la dispara el propio rescatista editando, quien quedaba marcado con 'R' se
        #sacaba la marca solo. Un veredicto solo lo reemplaza otro veredicto.
        if estado == Animal.REVISION_ERROR and animal.revision_ia_estado == Animal.REVISION_REVISAR:
            estado = Animal.REVISION_REVISAR
            motivo = animal.revision_ia_motivo

        try:
            animal.revision_ia_estado = estado
            animal.revision_ia_motivo = motivo
            animal.revision_ia_fecha = timezone.now()
            animal.save()
        except Exception:
            #guardar el resultado es lo de menos: el animal ya está cargado y lo que
            #no puede pasar es que esto le devuelva un error a quien lo publicó
            logger.exception("No se pudo guardar la revisión de %s", animal.id)
            return Animal.REVISION_ERROR

        return estado

    def _describir(self, animal):

        tipo = "gato" if animal.tipo == "G" else "perro"

        #todos estos campos los escribe quien carga el animal: van sin HTML y recortados
        partes = [
            "DATOS SIN VERIFICAR que cargó la persona (pueden no coincidir con las fotos):",
            "Tipo declarado: {}".format(tipo),
            "Nombre: {}".format(self._sin_html(animal.nombre)[:80] or "(sin nombre)"),
        ]

        if animal.edad:
            partes.append("Edad: {}".format(self._sin_html(animal.edad)[:40]))
        if animal.zona:
            partes.append("Zona: {}".format(self._sin_html(animal.zona)[:60]))
        if animal.datos:
            partes.append("Descripción: {}".format(self._sin_html(animal.datos)[:600]))

        partes.append("")
        partes.append("Ahora mirá las imágenes y describí lo que hay en ellas.")

        return "\n".join(partes)

    def _sin_html(self, texto):

        return re.sub(r"<[^>]*>", " ", texto or "").replace("&nbsp;", " ").strip()

    def _leer_fotos(self, animal):
        """Devuelve las fotos como data URLs. Se leen del disco, no por URL pública:
        así también funciona en desarrollo y con animales todavía no publicados."""

        fotos = []

        for imagen in self._fotos_a_mirar(animal):

            if not imagen.image:
                continue

            try:
                with imagen.image.open("rb") as archivo:
                    crudo = archivo.read()
            except Exception:
                logger.exception("No se pudo abrir la foto %s", imagen.id)
                continue

            if not crudo:
                continue

            fotos.append("data:image/jpeg;base64,{}".format(
                base64.b64encode(self._achicar(crudo)).decode("ascii")
            ))

        return fotos

    def _fotos_a_mirar(self, animal):
        """Las fotos que se le mandan al modelo, a lo sumo MAX_FOTOS.

        get_images() ordena por posicion, que no se escribe en ningún lado y queda
        siempre en NULL, así que el orden real es el de carga. Agregarle una cuarta
        foto a un animal que ya tenía tres hacía que la re-revisión mirara otra vez
        las tres viejas, no viera la nueva y encima le refrescara el "OK". Cuando ya
        hubo un veredicto, primero van las fotos que ese veredicto no vio.
        """

        imagenes = list(animal.get_images())
        revisado = animal.revision_ia_fecha

        if revisado:
            nuevas = []
            viejas = []

            for imagen in imagenes:
                if imagen.created_at and imagen.created_at > revisado:
                    nuevas.append(imagen)
                else:
                    viejas.append(imagen)

            imagenes = nuevas + viejas

        return imagenes[: self.MAX_FOTOS]

    def _achicar(self, crudo):
        """Reduce la foto antes de mandarla.

        Se manda con detail=low, que del lado del modelo la lleva a 512px igual, así
        que subir el original de 3 MB solo gasta tiempo y ancho de banda. Si algo falla
        se manda el original: es mejor una revisión cara que ninguna.
        """
        from io import BytesIO
        from PIL import Image

        try:
            imagen = Image.open(BytesIO(crudo))
            imagen = imagen.convert("RGB")
            imagen.thumbnail((self.LADO_MAXIMO, self.LADO_MAXIMO))

            salida = BytesIO()
            imagen.save(salida, format="JPEG", quality=80)
            return salida.getvalue()
        except Exception as error:
            #una foto que Pillow no puede abrir es esperable y no rompe nada: warning,
            #porque los eventos ERROR de Sentry se llevan la cookie de sesión puesta
            logger.warning("No se pudo achicar una foto para revisar: %s", type(error).__name__)
            return crudo

    def _mensajes(self, descripcion, fotos):

        contenido = [{"type": "text", "text": descripcion}]

        for foto in fotos:
            #detail low: alcanza para reconocer un animal y cuesta una fracción
            contenido.append({"type": "image_url", "image_url": {"url": foto, "detail": "low"}})

        return [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": contenido},
        ]

    def _preguntar(self, descripcion, fotos):
        """Llama a la API. Soporta el SDK viejo (openai<1) y el nuevo (openai>=1)."""

        import openai

        mensajes = self._mensajes(descripcion, fotos)
        modelo = self.get_modelo()

        if hasattr(openai, "OpenAI"):

            cliente_kwargs = {
                "api_key": settings.OPENIA_API_KEY,
                "timeout": self.TIMEOUT,
                "max_retries": self.REINTENTOS,
            }
            organizacion = getattr(settings, "OPENIA_API_ORG_ID", None)
            if organizacion:
                cliente_kwargs["organization"] = organizacion

            cliente = openai.OpenAI(**cliente_kwargs)
            respuesta = cliente.chat.completions.create(
                model=modelo, messages=mensajes, max_tokens=300, temperature=0,
            )
            return respuesta.choices[0].message.content

        openai.api_key = settings.OPENIA_API_KEY
        if getattr(settings, "OPENIA_API_ORG_ID", None):
            openai.organization = settings.OPENIA_API_ORG_ID

        respuesta = openai.ChatCompletion.create(
            model=modelo, messages=mensajes, max_tokens=300, temperature=0,
            #tupla (conexión, lectura): acá no hay cómo apagar los reintentos del SDK
            request_timeout=(self.TIMEOUT_CONEXION, self.TIMEOUT),
        )
        return respuesta["choices"][0]["message"]["content"]

    def _parsear(self, contenido):
        """Saca el JSON de la respuesta. Devuelve None si no se entiende."""

        if not contenido:
            return None

        texto = contenido.strip()

        #a veces viene envuelto en ```json ... ```
        if texto.startswith("```"):
            texto = re.sub(r"^```[a-zA-Z]*\s*", "", texto)
            texto = re.sub(r"\s*```$", "", texto)

        try:
            datos = json.loads(texto)
        except ValueError:
            encontrado = re.search(r"\{.*\}", texto, re.S)
            if not encontrado:
                return None
            try:
                datos = json.loads(encontrado.group(0))
            except ValueError:
                return None

        if not isinstance(datos, dict) or "animales" not in datos:
            return None

        #"animales" es la única clave de la que depende la decisión. Si viene con una
        #forma que no entendemos, esto es "no se pudo revisar" y NO "sospechoso":
        #tratar nuestra propia falla de parseo como sospecha frenaría la publicación
        #de un animal legítimo.
        if not isinstance(datos["animales"], (list, tuple, str)):
            return None

        return datos
