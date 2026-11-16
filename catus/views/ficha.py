from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404

from catus.models import Animal
from catus.services import ficha
from .base import BaseView


class FichaView(BaseView):
    """La página pública de un animal: /adoptar/<id>-<nombre>/.

    Antes no existía: el nombre y el botón de la tarjeta llevaban al formulario, y un link
    compartido por WhatsApp mostraba la portada (og:url fijo en "/", sin foto). Esta es la
    URL que se comparte, la que listan el sitemap y los buscadores.

    El nombre de la URL es decorativo: se busca por id, y si el nombre no coincide (lo
    cambiaron, o alguien lo escribió a mano) se redirige con un 301 a la URL de ahora. Solo
    se ven los aprobados; uno que ya no está en adopción (reservado, adoptado, expirado) lo
    dice y muestra otros de la misma especie, sin el botón del formulario.
    """

    url = r"^adoptar/(?P<animal_id>\d{1,9})(?:-(?P<slug>[^/]*))?/?$"
    template_name = "ficha/animal.html"

    #cuántos otros se muestran cuando este ya no está en adopción
    OTROS = 6

    def get(self, request, *args, **kwargs):

        animal = get_object_or_404(
            Animal.objects.select_related("cargado_por"), id=kwargs["animal_id"], aprobado=True,
        )

        canonica = animal.get_ficha_url()
        if request.path != canonica:
            query = request.META.get("QUERY_STRING", "")
            return HttpResponsePermanentRedirect(canonica + ("?" + query if query else ""))

        context = self.get_context_data(**kwargs)
        context.update(self.datos_de_la_ficha(animal))
        return self.render_to_response(context)

    def datos_de_la_ficha(self, animal):

        fotos = list(animal.get_images())
        url_canonica = settings.SSL_HOST + animal.get_ficha_url()
        imagen = ficha.imagen_para_compartir(fotos)
        en_adopcion = animal.estado == "D"

        datos = {
            "animal": animal,
            "fotos": fotos,
            "en_adopcion": en_adopcion,
            "especie": ficha.especie(animal),
            "especie_en_plural": ficha.especie_en_plural(animal),
            "plural": ficha.es_plural(animal),
            "terminacion": ficha.terminacion(animal),
            "titulo": ficha.titulo_de_la_ficha(animal),
            "descripcion_meta": ficha.descripcion_de_la_ficha(animal),
            "url_canonica": url_canonica,
            "imagen_para_compartir": settings.SSL_HOST + imagen if imagen else None,
            "url_formulario": animal.get_adoption_url(),
            "link_whatsapp": ficha.link_de_whatsapp("Mirá a {}, {} en adopción: {}".format(
                animal.nombre, ficha.especie(animal), url_canonica,
            )),
        }

        rescatista = animal.cargado_por
        if rescatista is not None:
            datos["rescatista"] = rescatista
            datos["nombre_rescatista"] = ficha.nombre_del_rescatista(rescatista)
            datos["url_rescatista"] = ficha.url_del_perfil(rescatista)

        if not en_adopcion:
            datos["otros"] = list(
                Animal.get_all_for_adoption(tipo=animal.tipo, sort="-fecha_ingreso").exclude(id=animal.id)[:self.OTROS]
            )

        return datos
