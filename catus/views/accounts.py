import re
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from catus.services.adoption import AdoptionService
from catus.services.validation import ValidationService
from catus.views.base import BaseView, SoloPostMixin

from catus.models import Animal, CatusUser, EstadoFormulario
from catus.forms import AnimalImageForm, CatusUserForm, RequiredImageInlineFormset
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q


class ProfileView(LoginRequiredMixin, BaseView):

    def render_to_response(self, context):
        #lista y no queryset: la usan la tabla y las preguntas de adopción, una sola consulta
        context["animals"] = list(self.get_animals())

        context["success"] = self.request.session.pop("animal_save_success", False) == True
        context["is_new_animal"] = self.request.session.pop("is_new_animal", False) == True
        context["is_new_animal_approved"] = self.request.session.pop("is_new_animal_approved", False) == True
        context["settings"] = settings
        context["form"] = CatusUserForm(instance=self.request.user)
        context["usuario_save_success"] = self.request.session.pop("usuario_save_success", False)
        context["usuario_save_error"] = self.request.session.pop("usuario_save_error", False)

        if self.request.user.is_superuser:
            estado_forms = EstadoFormulario.objects.all().order_by("-id")
        else:
            #los frenados por BuenAdoptante los revisa el equipo: al rescatista no le llegan
            estado_forms = EstadoFormulario.objects.filter(gato__cargado_por=self.request.user).exclude(estado="B").order_by("-id")

        #El equipo ve todos los formularios de la historia (miles) y la tabla pide el
        #nombre del gato en cada fila: sin el select_related eso era una consulta por
        #formulario, y el perfil del equipo tardaba 15 segundos en producción. El only
        #es porque la fila muestra cuatro campos: sin él, cada formulario traía además
        #el animal entero (datos, la respuesta de ChatGPT...), repetido por formulario.
        #Si la tabla suma un campo, va acá; si no, vuelve a ser una consulta por fila.
        estado_forms = estado_forms.select_related("gato").only("hash", "persona_nombre", "gato__nombre")

        context["estado_forms"] = estado_forms
        context["SSL_HOST"] = settings.SSL_HOST

        candidatos, adoptados, por_confirmar = self.preguntas_de_adopcion(context["animals"])
        context["adoptados_sin_adoptante"] = adoptados
        context["animales_por_confirmar"] = por_confirmar
        #lo que lee el JS del panel (json_script): sin las fechas como objeto
        context["candidatos_json"] = {
            str(animal_id): [{"id": c["id"], "persona": c["persona"], "fecha": c["fecha"]} for c in lista]
            for animal_id, lista in candidatos.items()
        }

        return BaseView.render_to_response(self, context)

    def get_animals(self):

        return Animal.objects.filter(cargado_por=self.request.user).order_by("-id")

    #formularios que no cuentan como candidatos a adoptante
    ESTADOS_NO_CANDIDATOS = ("B", "D", "U")
    #los adoptados de hasta hace cuánto se pregunta quién los adoptó
    DIAS_ADOPTADOS_SIN_ADOPTANTE = 60
    #a partir de cuántos días del primer formulario se pregunta si se adoptó
    DIAS_PARA_PREGUNTAR = 7

    def preguntas_de_adopcion(self, animales):
        """Lo que el panel pregunta sobre adopciones, armado con los animales que el panel
        ya trae (una sola consulta más, la de los formularios: el perfil del equipo tiene
        presupuesto de consultas, ver test_perfil).

        Devuelve (candidatos, adoptados_sin_adoptante, por_confirmar):
        - candidatos: {animal_id: [{id, persona, fecha, recibido}]}, los formularios de
          pre-adopción de cada animal, para elegir quién lo adoptó;
        - adoptados_sin_adoptante: marcados adoptados en los últimos dos meses sin decir
          quién, que habían recibido formularios;
        - por_confirmar: en adopción o reservados, reservados o con formularios de hace una
          semana o más.

        Casi nadie marca la adopción en el sitio, así que se pregunta al entrar. "Todavía
        no" posterga la pregunta (pregunta_adopcion_hasta) y el equipo puede apagarla para
        una cuenta (no_preguntar_adoptado).
        """

        ahora = timezone.now()
        hace_dos_meses = ahora - timedelta(days=self.DIAS_ADOPTADOS_SIN_ADOPTANTE)

        relevantes = [a for a in animales if a.estado in ("D", "R") or (
            a.estado == "A" and not a.estado_formulario_id and a.fecha_adopcion and a.fecha_adopcion >= hace_dos_meses)]
        if not relevantes:
            return {}, [], []

        formularios = (EstadoFormulario.objects
                       .filter(gato_id__in=[a.id for a in relevantes], tipo__in=["A", "AP"])
                       .exclude(estado__in=self.ESTADOS_NO_CANDIDATOS)
                       .order_by("-id")
                       .only("id", "gato_id", "persona_nombre", "fecha_ingreso", "created_at"))

        candidatos = {}
        for formulario in formularios:
            lista = candidatos.setdefault(formulario.gato_id, [])
            if len(lista) >= 30:
                continue
            fecha = formulario.fecha_ingreso or formulario.created_at
            lista.append({
                "id": formulario.id,
                "persona": (formulario.persona_nombre or "Sin nombre")[:80],
                "fecha": timezone.localtime(fecha).strftime("%d/%m/%Y") if fecha else "",
                "recibido": fecha,
            })

        if getattr(self.request.user, "no_preguntar_adoptado", False):
            return candidatos, [], []

        def se_puede_preguntar(animal):
            return animal.id in candidatos and (animal.pregunta_adopcion_hasta is None or animal.pregunta_adopcion_hasta < ahora)

        adoptados = [a for a in relevantes if a.estado == "A" and se_puede_preguntar(a)]
        adoptados.sort(key=lambda a: a.fecha_adopcion, reverse=True)

        limite = ahora - timedelta(days=self.DIAS_PARA_PREGUNTAR)
        por_confirmar = []
        for animal in relevantes:
            if animal.estado not in ("D", "R") or not animal.aprobado or not se_puede_preguntar(animal):
                continue
            fechas = [c["recibido"] for c in candidatos[animal.id] if c["recibido"]]
            primero = min(fechas) if fechas else None
            if animal.estado == "R" or (primero is not None and primero <= limite):
                por_confirmar.append((primero or ahora, animal))
        por_confirmar.sort(key=lambda par: par[0])

        return candidatos, adoptados[:8], [animal for _, animal in por_confirmar[:8]]

    def post(self, *a, **k):

        form = CatusUserForm(self.request.POST, self.request.FILES, instance=self.request.user)

        if form.is_valid():

            form.save()
            logo_img = "/{}".format(form.instance.logo_img.name)
            banner_img = "/{}".format(form.instance.banner_img.name)

            profile_link = "/{}/".format(form.instance.handle)

            return self.json_response({"status": "success", "logo_img": logo_img, "banner_img": banner_img, "profile_link": profile_link })
        else:
            return self.json_response({"status": "failure", "errors": form.errors })


class CheckHandleView(SoloPostMixin, BaseView):

    def post(self, *a, **k):

        handle = self.request.POST.get("handle")
        user = self.request.user

        try:
            ValidationService().check_handle(handle, user)
            return self.json_response({"status": "success"})
        except Exception as e:
            return self.json_response({"status": "failure", "error": str(e) })
