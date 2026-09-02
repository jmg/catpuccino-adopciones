# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Django 2.0 site for **Catpuccino Adopciones** (adopciones.catpuccino.org): a pet-adoption
platform where rescuers publish cats and dogs, the public submits pre-adoption / transit
forms, and admins track each candidate through to a signed adoption contract PDF. It also
auto-publishes listings to Instagram via the Facebook Graph API and drafts listing text
with the OpenAI API.

All user-facing copy, model field names and template names are in **Spanish** (`LANGUAGE_CODE = es-ar`,
`TIME_ZONE = America/Argentina/Buenos_Aires`). Keep new code in the same language as the
surrounding code — `gato`, `estado`, `cargado_por`, `aprobado`, `fecha_ingreso` are domain
terms, not incidental naming.

Single Django app `catus/`, project package `catus_project/`. There is effectively no test
suite (`catus/tests.py` is the empty stub).

## Commands

The shell scripts hardcode a virtualenv at `/home/jm/Envs/catus`, which only exists on the
author's machine. In any other environment run `manage.py` directly.

```bash
python manage.py runserver localhost:8000   # dev server (ENV unset => LOCAL => DEBUG=True)
python manage.py check
python manage.py migrate
python manage.py makemigrations catus
python manage.py shell
python manage.py collectstatic --noinput
python manage.py test                       # runs, but there are no real tests
python manage.py test catus.tests.SomeTest.test_x   # single test
```

`./dev_tools.sh <shell|migrate|makemigrations|createsuperuser|collectstatic|test|check|clean|requirements|backup|reset_db>`
wraps the same commands behind the author's venv. `./start.sh [port]` and `./run_dev.sh`
start the server the same way. `./deploy.sh` ssh's to production, `git pull`s and restarts
the `catpuccino_adopciones` supervisor program — so **production runs whatever is on the
default branch**.

Custom management commands in `catus/management/commands/` are the cron/batch surface:
`publish` (post queued animals to Instagram), `update_post_id`, `update_status_in_ig`
(comment "adoptado" on published posts), `refresh_token` (renew the long-lived Facebook
token before expiry), `pull_from_ig`, `automatic_approve`, `optimize_images`,
`update_estado_form`, plus several `test_*` scratch commands.

## Configuration — nothing runs without it

`catus_project/settings.py` reads secrets through `catus_project/config.py`:

- `ENV=LOCAL` (the default) or `TEST` → `catus/config/config.<env>.json`
- any other `ENV` → `/etc/secrets/catpuccino_adopciones.<env>.json`

`catus/config/` is gitignored, and a missing or malformed file raises `SystemExit` at import
time — so a fresh clone cannot even run `manage.py check` until that JSON exists. Required
keys: `DJANGO_SECRET_KEY`, `DB_ENGINE`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`
(optional `DB_OPTIONS`), `ADMIN_PASSWORD`, `ADMIN_URL`, `SEND_MAIL`, `SENDGRID_API_KEY`,
`SENTRY_DSN`, `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `OPENIA_API_KEY`,
`OPENIA_API_ORG_ID`, `PROXY_USER`, `PROXY_PASSWORD`.

`DEBUG` is derived as `ENV == "LOCAL"`; Sentry and the real `ALLOWED_HOSTS` only activate
when `ENV != "LOCAL"`. `catus_project/settings_local.py` is imported last if present.

Production uses MySQL through PyMySQL (`pymysql.install_as_MySQLdb()`); `forms.sql` is a
MySQL dump of the `forms_builder` tables used to seed the adoption forms.

## URL and template conventions (django-conventions)

`catus_project/urls.py` does not enumerate app routes. `UrlsManager(urlpatterns, catus.views)`
walks every view class in `catus/views/*.py` and registers it:

- A class attribute `url = r"^adopciones/$"` (or a **list** of regexes) defines the route
  explicitly. Named groups become view kwargs.
- A view with **no** `url` attribute gets a route derived from module + class name:
  `views/animal.py::AprobarView` → `/animal/aprobar/`, `accounts.py::CheckHandleView` →
  `/accounts/checkhandle/`, `animal.py::MarcarAdoptado` → `/animal/marcaradoptado/`. These
  are hardcoded in templates' jQuery/htmx calls — grep the templates before renaming a view
  class, since there are no URL names to follow.
- `template_name` is likewise derived from module + class name when absent:
  `home.py::IndexView` → `templates/home/index.html`, `usuario.py::AnimalesView` →
  `templates/usuario/animales.html`.

Only the admin, `forms_builder` (`/forms/`), auth views and media are wired manually. The
admin lives at the URL from config (`ADMIN_URL`), not `/admin/`.

## Architecture

**Views** (`catus/views/`) subclass `BaseView` (`views/base.py`), a `TemplateView` with
`json_response()`, `render()`, `response()`, `redirect()` helpers. Most override
`render_to_response(context)` to populate context, or define `get`/`post` directly.
Auth is `LoginRequiredMixin` per view. Views hold a fair amount of business logic and call
into services rather than the other way round.

**Services** (`catus/services/`) are plain classes instantiated per call (`AdoptionService()`,
`MailService()`, `ImageService()`, `GPTService()`). `BaseService` (`services/base.py`) is a
generic repository wrapper: `__getattr__` delegates unknown methods to `self.entity.objects`,
plus pagination, `get_or_new`, and `open_search()` — the server-side DataTables endpoint used
by `views/forms.py::ListView`, which maps column indexes to attribute names or lambdas that
render HTML cells.

**Domain models** (`catus/models.py`), all inheriting `BaseEntity` (auto `created_at`/`updated_at`):

- `Animal` — the listing. `estado` is `D` en adopción / `R` reservado / `A` adoptado /
  `E` expirado; `tipo` is `G` gato / `P` perro. `aprobado` gates public visibility,
  `destacado` gates the homepage. Instagram state lives here too
  (`instagram_listo_para_publicar` → `instagram_publicado` → `instagram_post_id` →
  `instagram_comment_id`). Use `Animal.get_all_for_adoption(...)`, which already filters
  `aprobado=True, estado="D"` and prefetches images.
- `AnimalImage` — gallery photo plus a separately generated `image_for_instagram` and its
  layout parameters (font size, name/age placement).
- `EstadoFormulario` — a submitted adoption form's pipeline state, keyed by a uuid `hash`
  that is emailed as an unauthenticated link (`/formularios/<hash>/`). `tipo` is
  `A`/`AP` pre-adopción gatos/perros, `T`/`TP` tránsito.
- `CatusUser` — `AUTH_USER_MODEL`, logs in by **email**, has a public `handle` serving
  `/<handle>/` as a mini-profile of that rescuer's animals.
- `Contrato` / `ContratoPersona` — the adoption contract's data, again reachable by `hash`
  so the adopter can fill in their own half at `/contrato/<hash>/`.
- `FacebookAccount` — single row holding the long-lived token and IG business account ids.

**Adoption form flow.** Public forms are `django-forms-builder` `Form` objects created in the
admin, *not* Django forms in this repo — `views/adoption.py::PreAdoptionView` picks them
positionally (`Form.objects.all()[0]`, `[3]` for dogs), so reordering forms in the database
breaks the site. On submit it saves a `FormEntry`, wraps it in a new `EstadoFormulario` with a
uuid hash, and emails both the rescuer and the applicant. `AdoptionService` reads answers back
out of the `FieldEntry` rows **by Spanish label** ("Nombre y Apellido", "Email", …), so
renaming a field label in the admin silently breaks parsing.

`catus/signals.py` keeps the forms-builder "which animal" dropdown in sync: any `Animal` or
`Form` save/delete rewrites that `Field.choices` string with the current adoptable animal ids.
It swallows all exceptions and locates the cat field as `Field.objects.all()[0]` — fragile in
the same positional way.

**Contract PDFs** (`services/contrato.py`) stamp text onto the static templates
`catus/static/contrato/contrato.pdf` / `contrato_perros.pdf` with reportlab + PyPDF2, at
hardcoded x/y coordinates per page, and write the result to
`catus/static/contrato/<hash>/`. That directory is gitignored, and the blank source PDFs are
not in the repo. `contrato_test/contrato.py` renders a contract from fake objects for
iterating on coordinates without a database.

**Instagram publishing** (`services/facebook.py`, all classmethods). `ImageService` composes
the branded post image (logo, name, age/sex overlay); `FacebookApiService` uploads it as a
single image or carousel container, polls `wait_for_media_ready`, publishes, then later posts
an "adoptado" comment when the animal's `estado` changes. Tokens are refreshed by
`refresh_token`.

**GPT** (`services/gpt.py`) scrapes an Instagram post's `og:title`, asks the OpenAI API to
extract name/type/sex/age/description as JSON, and prefills the animal form
(`/animal/pulldatafromig/`). Responses are cached in `ChatGTPResponse`.

## Known rough edges

- `requirements.txt` is a `pip freeze` of the production box and is **incomplete**: Pillow,
  reportlab and Twisted are commented out, and openai, tiktoken, pathlib2, selenium,
  django-conventions and PyPDF2's runtime companions are needed but variously missing. Expect
  to install missing packages by hand.
- `catus/services/tables.py` is an unused near-duplicate of `services/base.py`; only
  `services/base.py` is imported anywhere. Don't edit both.
- Several `BaseService` methods (`save`, `_get_data`, `update_or_create`, `set_attrs`,
  `get_action_params`, `check_nullables`) still call `dict.iteritems()` and would raise on
  Python 3 — they are dead code paths, not working helpers. `open_search` and `render` are
  the parts actually in use.
- `CacheService` talks to memcached on `localhost` with pickled values; every call site is
  currently commented out.
- `MEDIA_URL = "/"` with `MEDIA_ROOT = <repo>/gallery`, so uploads are served from the site
  root, e.g. `/gallery/<uuid>.jpeg`.
- Broad `try/except: pass` is common in this codebase (signals, form parsing, email sending).
  Match the surrounding style rather than tightening it opportunistically, but don't add new
  bare excepts around code you write.
- `test.html` (600KB of saved Instagram HTML) and `forms.sql` at the repo root are scratch
  data, not part of the app.
