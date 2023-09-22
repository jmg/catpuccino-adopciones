"""
Django settings for catus project.

Generated by 'django-admin startproject' using Django 3.0.4.

For more information on this file, see
https://docs.djangoproject.com/en/3.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.0/ref/settings/
"""

import os
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass

ENV = os.environ.get("ENV", "LOCAL")
DEBUG = ENV == "LOCAL"

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from . import config
app_config = config.read_config(ENV, root_path=os.path.join(BASE_DIR, "catus"), file_name="catpuccino_adopciones")

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = app_config.get("DJANGO_SECRET_KEY")

if ENV != "LOCAL":
    ALLOWED_HOSTS = ["adopciones.catpuccino.org"]
else:
    ALLOWED_HOSTS = ["localhost"]

if ENV != "LOCAL":
    sentry_sdk.init(
        dsn=app_config.get("SENTRY_DSN"),
        integrations=[DjangoIntegration()]
    )

    try:
        import raven
        RAVEN_CONFIG = {
            'dsn': app_config.get("SENTRY_DSN"),
            'release': raven.fetch_git_sha(os.path.dirname(os.pardir)),
        }
    except:
        pass

if ENV != "LOCAL":
    HOST = "adopciones.catpuccino.org"
    SSL_HOST = "https://{}".format(HOST)
else:
    HOST = "localhost:8000"
    SSL_HOST = "http://{}".format(HOST)

# Application definition

INSTALLED_APPS = [
    'raven.contrib.django.raven_compat',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'forms_builder.forms',
    'bootstrap4',
    'crispy_forms',
    'django.contrib.sites',

    "catus",
]
SITE_ID = 1
CRISPY_TEMPLATE_PACK = 'bootstrap4'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'catus_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'catus', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'catus.auth.SettingsBackend'
)

ADMIN_PASSWORD = app_config.get("ADMIN_PASSWORD")

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "catus", "static"),
]

MEDIA_ROOT = os.path.join(BASE_DIR, "gallery")
MEDIA_URL = '/'

DATE_INPUT_FORMATS = ('%d/%m/%Y', )

WSGI_APPLICATION = 'catus_project.wsgi.application'


# Database
# https://docs.djangoproject.com/en/3.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': app_config.get("DB_ENGINE"),
        'NAME': app_config.get("DB_NAME"),
        'USER': app_config.get("DB_USER"),
        'PASSWORD': app_config.get("DB_PASSWORD"),
        'HOST': app_config.get("DB_HOST"),
        'PORT': app_config.get("DB_PORT"),
    }
}

AUTH_PASSWORD_VALIDATORS = []

# Internationalization
# https://docs.djangoproject.com/en/3.0/topics/i18n/

LANGUAGE_CODE = 'es-ar'

TIME_ZONE = 'America/Argentina/Buenos_Aires'

USE_I18N = False

USE_L10N = True

USE_TZ = True

FILE_UPLOAD_PERMISSIONS = 0o777

SEND_MAIL = app_config.get("SEND_MAIL")

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.0/howto/static-files/

STATIC_URL = '/static/'

FORMS_BUILDER_HELPTEXT_MAX_LENGTH = 1000
FORMS_BUILDER_LABEL_MAX_LENGTH = 1000

LOGIN_URL = "/accounts/login/"

LOGIN_REDIRECT_URL = "/accounts/profile/"
LOGOUT_REDIRECT_URL = "/"

AUTH_USER_MODEL = "catus.CatusUser"

ANIMAL_ESTADO_CHOICES = [("D", "En Adopción"), ("R", "Reservado"), ("A", "Adoptado"), ("E", "Expirado")]
ANIMAL_TIPO = [("G", "Gato"), ("P", "Perro")]

FACEBOOK_APP_ID = app_config.get("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = app_config.get("FACEBOOK_APP_SECRET")

OPENIA_API_KEY = app_config.get("OPENIA_API_KEY")
OPENIA_API_ORG_ID = app_config.get("OPENIA_API_ORG_ID")

EMAIL_BACKEND = "sgbackend.SendGridBackend"
SENDGRID_API_KEY = app_config.get("SENDGRID_API_KEY")

ADMIN_URL = app_config.get("ADMIN_URL")

if ENV == "LOCAL":
    """LOGGING = {
        'version': 1,
        'filters': {
            'require_debug_true': {
                '()': 'django.utils.log.RequireDebugTrue',
            }
        },
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'filters': ['require_debug_true'],
                'class': 'logging.StreamHandler',
            }
        },
        'loggers': {
            'django.db.backends': {
                'level': 'DEBUG',
                'handlers': ['console'],
            }
        }
    }"""
    LOGGING = {}

try:
    from .settings_local import *
except:
    pass


