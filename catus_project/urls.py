"""catus URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path

from django_conventions import UrlsManager
import catus.views as app_root
import forms_builder.forms.urls
from django.conf.urls import include, url
from django.conf.urls.static import static
from django.conf import settings
from django.contrib.auth import views as auth_views
from catus.forms import UserLoginForm

urlpatterns = []

UrlsManager(urlpatterns, app_root)

urlpatterns += [
    path(settings.ADMIN_URL, admin.site.urls),
    url(r'^forms/', include(forms_builder.forms.urls)),

    path('accounts/login/', auth_views.LoginView.as_view(authentication_form=UserLoginForm), name='login'),
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(html_email_template_name='registration/password_reset_email.html')),
    path('accounts/', include('django.contrib.auth.urls')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.autodiscover()

admin.site.site_header = "Catpuccino Adopciones Admin"
admin.site.site_title = "Catpuccino Adopciones Admin"
admin.site.index_title = "Catpuccino Adopciones Admin"