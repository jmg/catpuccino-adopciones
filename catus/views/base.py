import json
from django.views.generic import TemplateView
from django.shortcuts import redirect
from catus.models import Animal
from django.http import HttpResponse
from catus.services.utils.render import render
from catus.services.base import BaseService


class BaseView(TemplateView):

    def render_to_response(self, context):

        return TemplateView.render_to_response(self, context)

    def json_response(self, data):

        return HttpResponse(json.dumps(data))

    def render(self, template, data):

        return render(template, data)

    def response(self, text):

        return HttpResponse(text)

    def redirect(self, url):

        return redirect(url)

    def render(self, template, context):

        return BaseService().render(template, context)

    def get_current_user(self):

        return self.request.user



class LoginRequiredView(BaseView):

    login_exempt = False