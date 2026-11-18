from django.utils.html import escape

from catus.utils import send_html_email, rreplace
from catus.services.base import BaseService
from catus.models import Animal
from django.conf import settings
from datetime import datetime, timedelta


class MailService(BaseService):

    #por qué llega el aviso, además del alta que la revisión no aprobó (services/revision_pendiente.py)
    AVISO_MARCADO = "marcado"            #la IA lo marcó después: al reintentar o tras una edición
    AVISO_SIN_REVISION = "sin_revision"  #un día de reintentos y la revisión nunca pudo correr

    def send_new_animal_mail(self, animal, motivo_anterior=None, vuelve=False, caso=None):
        """A quien revisa (settings.AVISOS_DE_REVISION_A): un animal necesita que lo mire una persona.

        Sólo para los que lo necesitan: el alta que la revisión aprobó sola ya está en el sitio, y
        el mail decía "espera la aprobación del equipo" de algo que no esperaba nada. Lleva lo
        que dijo la revisión con IA, que es lo primero que hay que mirar, y un botón a la cola
        y no a una acción: antes era un link que aprobaba con un GET, así que lo aprobaba
        cualquier cosa que lo abriera (un antivirus que revisa los links, una vista previa).

        `vuelve` es el que el equipo había marcado "No publicar" y su dueño editó: vuelve a la
        cola, y el mail dice por qué no se había publicado. `caso` es AVISO_MARCADO (la IA lo
        marcó más tarde, y puede estar publicado) o AVISO_SIN_REVISION (no se pudo revisar).
        """

        if settings.ENV == "LOCAL":
            return

        if vuelve:
            subject = "Catpuccino Adopciones - Vuelve a revisión: {}".format(animal.nombre)
        elif caso == self.AVISO_MARCADO:
            subject = "Catpuccino Adopciones - La revisión marcó a {}".format(animal.nombre)
        elif caso == self.AVISO_SIN_REVISION:
            subject = "Catpuccino Adopciones - No se pudo revisar a {}".format(animal.nombre)
        else:
            subject = "Catpuccino Adopciones - Nuevo Ingreso"

        content = self.render("email/new_animal.html", {
            "animal": animal, "settings": settings,
            "vuelve": vuelve, "motivo_anterior": motivo_anterior, "caso": caso,
            "link_pendientes": "{}/tools/animalespendientes/#animal-{}".format(settings.SSL_HOST, animal.id),
        })

        send_html_email(subject, content, settings.SEND_MAIL, list(settings.AVISOS_DE_REVISION_A))

    def send_mail_no_publicado(self, usuario, animales, motivo=None, sacado_del_sitio=False):
        """Al rescatista: el equipo decidió no publicar estos animales suyos.

        Le dice cuáles, por qué si el equipo lo escribió, y cómo seguir: si sigue en
        adopción, que lo edite, que eso lo devuelve a la cola. Uno solo por cuenta aunque
        sean varios (archivar_pendientes los marca de a muchos).
        """

        if settings.ENV == "LOCAL":
            return

        if usuario is None or not usuario.email:
            return

        animales = list(animales)
        if not animales:
            return

        if len(animales) == 1:
            if sacado_del_sitio:
                subject = "Catpuccino Adopciones - {} ya no está publicado".format(animales[0].nombre)
            else:
                subject = "Catpuccino Adopciones - {} no se publicó".format(animales[0].nombre)
        else:
            subject = "Catpuccino Adopciones - {} animales no se publicaron".format(len(animales))

        content = self.render("email/no_publicado.html", {
            "animales": [
                {"nombre": animal.nombre, "link_editar": "{}/animales/{}/".format(settings.SSL_HOST, animal.id)}
                for animal in animales
            ],
            "motivo": motivo,
            "sacado_del_sitio": sacado_del_sitio,
            "link_panel": settings.SSL_HOST + settings.LOGIN_REDIRECT_URL,
            "settings": settings,
        })

        send_html_email(subject, content, settings.SEND_MAIL, usuario.email)

    def send_aviso_instagram(self, problemas, link):
        """Le avisa al equipo que hay que volver a conectar Instagram (refresh_token)."""

        if settings.ENV == "LOCAL":
            return

        subject = "Catpuccino Adopciones - Hay que volver a conectar Instagram"
        items = "".join("<li>{}</li>".format(escape(problema)) for problema in problemas)
        content = (
            "<p>El sitio no va a poder publicar ni comentar en Instagram hasta que alguien "
            "del equipo vuelva a conectar la cuenta:</p><ul>{}</ul>"
            "<p>Para arreglarlo: entrá con un usuario del equipo a "
            "<a href=\"{link}\">{link}</a>, apretá <b>Iniciar sesión con Facebook</b> y "
            "elegí solo la página de Catpuccino.</p>"
        ).format(items, link=escape(link))

        send_html_email(subject, content, settings.SEND_MAIL, ["catpuccino.ok@gmail.com"])

    def send_mail_aprobacion(self, animal):

        if settings.ENV == "LOCAL":
            return

        #hay animales sin rescatista (los cargados antes de que existieran las cuentas,
        #y los de quien fue dado de baja): no hay a quién avisarle, pero eso no puede
        #hacer fallar la aprobación
        if animal.cargado_por is None or not animal.cargado_por.email:
            return

        subject = "Catpuccino Adopciones - {} ya está publicado!".format(animal.nombre.capitalize())
        #el link del formulario puede ser uno propio del animal (custom_link), ya completo
        link_formulario = animal.get_adoption_url()
        if not link_formulario.startswith(("http://", "https://")):
            link_formulario = settings.SSL_HOST + link_formulario
        content = self.render("email/new_animal_aprobacion.html", {
            "animal": animal, "settings": settings, "link_formulario": link_formulario,
            "link_perfil": settings.SSL_HOST + animal.cargado_por.get_handle_url(),
        })

        send_html_email(subject, content, settings.SEND_MAIL, animal.cargado_por.email)

    def send_mail_pregunta(self, user, content):

        days_ago = datetime.now() - timedelta(days=30)

        animals = Animal.objects.filter(cargado_por=user, estado="D", aprobado=True, created_at__lte=days_ago)
        animals_names = ", ".join([animal.nombre for animal in animals])
        animals_names = rreplace(animals_names, ", ", " y ", 1)

        subject = "Catpuccino Adopciones - ¿Sigue{} {} en adopción?".format("n" if len(animals) > 1 else "", animals_names)

        animals.update(mail_preguntar_adopcion_enviado=True)

        #la respuesta ("sí, se adoptó") es para el equipo: sin esto le volvía al rescatista
        send_html_email(subject, content, settings.SEND_MAIL, user.email, reply_to=["catpuccino.ok@gmail.com"])
