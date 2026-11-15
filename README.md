# Catpuccino Adopciones

El sitio de [adopciones.catpuccino.org](https://adopciones.catpuccino.org): una plataforma
gratuita donde rescatistas y refugios publican gatos y perros en adopción, la gente completa
un formulario de pre-adopción y cada rescatista sigue a sus candidatos hasta el contrato de
adopción. Los animales aprobados se publican solos en Instagram.

Es un proyecto Django 5.2 (Python 3.12) con una sola app, `catus/`. Todo el texto del sitio y
los nombres del código están en español.

## Puesta en marcha

Hace falta Python 3.12 y, para compilar `mysqlclient`, un compilador y las cabeceras de
MariaDB o MySQL. En Debian o Ubuntu:

```bash
sudo apt-get install gcc libc6-dev pkg-config libmariadb-dev
```

Después:

```bash
git clone https://github.com/jmg/catpuccino-adopciones.git
cd catpuccino-adopciones

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c constraints.prod.txt

# la configuración (ver más abajo): sin este archivo no arranca ni manage.py check
mkdir -p catus/config
cp config.ejemplo.json catus/config/config.local.json

python manage.py migrate
python manage.py loaddata formularios     # los cuatro formularios públicos
python manage.py createsuperuser          # pide un email y una contraseña

python manage.py runserver localhost:8000
```

El sitio queda en <http://localhost:8000>. Se entra con el email del superusuario en
`/accounts/login/`, y desde `/accounts/profile/` se carga el primer animal. El admin de
Django está en la ruta que diga `ADMIN_URL` (con el ejemplo, `/admin-local/`).

Con el archivo de ejemplo la base es un SQLite (`db.sqlite3`) y no se manda ningún mail ni
se publica nada en Instagram: alcanza para ver y tocar todo el sitio.

## Configuración

El sitio lee su configuración de un JSON, según la variable de entorno `ENV`:

| `ENV` | Archivo |
|---|---|
| sin definir, o `LOCAL` | `catus/config/config.local.json` (con `DEBUG` prendido) |
| `TEST` | `catus/config/config.test.json` |
| cualquier otro valor | `/etc/secrets/catpuccino_adopciones.<env>.json` |

`catus/config/` no se sube al repositorio. `config.ejemplo.json` tiene todas las claves, con
valores que sirven para desarrollo:

| Clave | Para qué |
|---|---|
| `DJANGO_SECRET_KEY` | La clave secreta de Django. |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | La base de datos. Producción usa MySQL (`django.db.backends.mysql`); `DB_OPTIONS` es opcional. |
| `ADMIN_URL` | La ruta del admin de Django, con la barra al final. Tiene que llevar un guion (`admin-local/`): una sola palabra, como `admin/`, la toma el perfil público de un rescatista (`/<usuario>/`) y da 404. |
| `ADMIN_PASSWORD` | Contraseña maestra con la que el equipo entra como otra cuenta. Fuera de tu máquina tiene que ser larga y secreta. |
| `SEND_MAIL`, `SENDGRID_API_KEY` | El remitente de los mails y la clave de SendGrid. |
| `SENTRY_DSN` | A dónde se reportan los errores. |
| `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` | La app de Meta con la que se publica en Instagram. |
| `OPENIA_API_KEY`, `OPENIA_API_ORG_ID` | OpenAI: la revisión automática de las publicaciones y «Obtener datos desde Instagram». |
| `PROXY_USER`, `PROXY_PASSWORD` | El proxy con el que se leen posteos de Instagram. |

Las claves de servicios externos pueden quedar vacías: lo que depende de ellas no anda, el
resto sí.

## Los formularios

Los formularios públicos de pre-adopción y de tránsito no son formularios de Django: son
objetos de `forms_builder` guardados en la base, y el sitio los busca por su `slug`.
`python manage.py loaddata formularios` carga los cuatro (`catus/fixtures/formularios.json`),
con las preguntas y los requisitos que usa el sitio. Mientras se cargan, la consola avisa
varias veces que no encuentra el campo «Gato a adoptar»: es esperable, el campo se carga un
momento después.

Las respuestas se leen por la etiqueta de cada pregunta («Nombre y Apellido», «Email»,
«Celular»…), así que cambiar una etiqueta desde el admin rompe esa lectura.

## Tests

```bash
cp config.ejemplo.json catus/config/config.test.json
ENV=TEST python manage.py test catus forms_builder
```

La corrida termina con un error de importación de `test_insta`, un comando suelto que
necesita `selenium`: es conocido y no es una falla de la suite.

Los tests del selector de recorte, del buscador y de la portada corren en un navegador de
verdad, con Playwright. Están en `jstests/`, con su propio [README](jstests/README.md):

```bash
cd jstests
npm install
npx playwright install chromium
npm test
```

## Cómo está armado

- `catus/` es la app: modelos, vistas, servicios, plantillas y estáticos.
- `catus_project/` tiene los settings y las URLs. Las rutas no se listan a mano: salen de
  las clases de `catus/views/` (ver `django_conventions/`).
- `forms_builder/` y `django_conventions/` son copias de django-forms-builder y
  django-conventions adaptadas a Django 5.2.
- `catus/management/commands/` son los procesos que corren por cron: publicar en Instagram,
  preparar las imágenes, expirar las publicaciones de más de un mes.
- `jstests/` son los tests de navegador.

[CLAUDE.md](CLAUDE.md) explica la arquitectura con más detalle: el flujo de los formularios,
los permisos, la publicación en Instagram, la revisión automática y el deploy.

## Producción

El sitio corre en DeployCloud, desde la rama `deploycloud`. Las migraciones no corren solas
al deployar: hay que aplicarlas después de cada deploy que traiga una. El detalle está en
[CLAUDE.md](CLAUDE.md).
