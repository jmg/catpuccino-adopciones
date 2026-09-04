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

Single Django app `catus/`, project package `catus_project/`.

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
python manage.py test catus                 # the whole suite
python manage.py test catus.tests.test_crop                          # one module
python manage.py test catus.tests.test_crop.CleanCropTest.test_rechaza_infinitos_y_nan   # one test
```

## Tests

`catus/tests/` holds the suite; `catus/tests/factories.py` builds the objects (`make_animal`,
`make_user`, `make_estado_formulario`, `uploaded_photo`). Tests and their names are in
Spanish, like the rest of the code.

Views are exercised by calling them directly with `RequestFactory` — either
`ViewClass.as_view()(request, **kwargs)` when the test cares about the permission mixins, or
by instantiating the view and setting `view.request` when it only needs one method. That
sidesteps the URLconf, which `django-conventions` builds by walking the view classes and
which needs the whole project booted.

Most tests double as a record of a bug that reached production: their docstring says what
used to break and for whom. When touching that code, keep the assertion.

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
admin, *not* Django forms in this repo — `views/adoption.py::PreAdoptionView` resolves them by
`slug` (`PreAdoptionView.form_slug`), falling back to the old positional lookup with a log line
if the slug is gone. On submit it saves a `FormEntry`, wraps it in a new `EstadoFormulario` with
a uuid hash, and emails both the rescuer and the applicant. `AdoptionService` reads answers back
out of the `FieldEntry` rows **by Spanish label** ("Nombre y Apellido", "Email", …), so
renaming a field label in the admin silently breaks parsing.

`catus/signals.py` keeps the forms-builder "which animal" dropdown in sync: any `Animal` or
`Form` save/delete rewrites that `Field.choices` string with the current adoptable animal ids.
It finds each field by label (`ANIMAL_FIELD_LABELS`), handles cats and dogs independently so a
failure on one doesn't stall the other, and logs what it swallows — it runs inside `Animal.save()`
and must never make saving an animal fail.

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

**Square crop for Instagram.** Posts are 1200×1200 inside a 1400×1400 white frame, so every
photo has to be cropped square. `AnimalImage.crop_x/y/w/h` hold the chosen crop as fractions
(0–1) of the source photo, so it survives rescaling; `get_crop()`/`set_crop()` wrap them.
`ImageService.crop_to_square()` honours that crop and otherwise falls back to the old
`centered` heuristic, and `suggest_crop()` proposes one by scanning edge energy for the
squarest window holding the most detail (pure Pillow, no extra dependency). The crop is
picked with a Cropper.js selector (`static/js/crop-widget.js`, vendored in
`static/vendor/cropper/`) in two places: the upload formset in `animal/edit.html`, and the
per-image controls in `tools/makeimages.html`. Uploads without a crop get `suggest_crop()`
applied in `views/animal.py::EditView.set_suggested_crop`. Crop fractions come from the
browser, so they are validated by `utils.clean_crop` before use, and `AnimalImageForm`
declares them as `CharField` on purpose — a malformed crop is ignored rather than making
the form invalid and blocking the animal from being saved.

**GPT** (`services/gpt.py`) scrapes an Instagram post's `og:title`, asks the OpenAI API to
extract name/type/sex/age/description as JSON, and prefills the animal form
(`/animal/pulldatafromig/`). Responses are cached in `ChatGTPResponse`.

**Automatic post review** (`services/moderacion.py`). When an animal is created — or edited
in a way that changes its photos, `nombre`, `datos` or `tipo` — its photos and text go to a
cheap vision model to catch listings that are not an animal in adoption: screenshots,
landscapes, ads, spam, inappropriate content. The verdict lands in
`Animal.revision_ia_estado` (`P` sin revisar / `OK` / `R` revisar / `E` no se pudo revisar)
plus `revision_ia_motivo`, and `/tools/animalespendientes/` sorts flagged listings first.

Two invariants hold the design together, and both have tests that fail if they break:

- **It can never stop someone publishing an animal.** Every failure path — API down, no
  credit, refusal (`content=None`), malformed JSON, a failed save — returns `E`, which never
  blocks saving and never marks the listing as suspicious. `E` and `R` look similar but they
  are not interchangeable: a parsing failure of *ours* must never be reported as suspicion of
  *theirs*.

**The review is what approves a listing** (`views/animal.py::EditView`, on create). `OK`
auto-approves — for anyone, no track record needed — and that approval also schedules the
Instagram post, so a listing can go from upload to the shelter's public account with nobody
in between; the delay window in `/tools/colainstagram/` is the only human gate. `R` never
auto-approves. `E` is *not* a verdict, so it does not approve on its own: it falls back to the
old rule, `cargado_por.automatic_approve` (granted by the `automatic_approve` cron at 5
hand-approved animals). That fallback is what keeps an OpenAI outage from stalling established
rescuers without opening the door for brand-new accounts — which matters because registration
is open. The whole matrix is pinned in `tests/test_moderacion.py::AutoAprobacionTest`;
reverting any leg of it fails a test.
- **The model describes, the code decides.** `PROMPT` asks only for what is visible;
  `decidir()` holds the policy. An earlier version asked the model to judge and it echoed the
  prompt's rules instead of looking, flagging 10 of 14 real gallery photos. After the split,
  0 of 24. Keep policy out of the prompt.

Other constraints baked in: the listing text is framed as unverified data (that framing is
what makes prompt injection through `nombre`/`datos` fail, and a test asserts it survives);
photos are downscaled to 512px and capped at 3 per call; the SDK runs with `max_retries=0`
and an 8s timeout because the upload POST waits on it and the worker cuts at 30s; there is a
per-user daily cap (`MODERACION_IA_MAX_POR_DIA`) because registration is open and each upload
costs money; expected API failures log at `warning`, not `exception`, since Sentry attaches
the session cookie to `ERROR` events. Inactive when `ENV=LOCAL`, when `MODERACION_IA_ACTIVA`
is off, or when there is no `OPENIA_API_KEY`. Supports both openai SDK generations, since the
production version is unknown.

## Permissions

Registration at `/accounts/register/` is open and self-service, so **"is logged in" is not a
permission** — an attacker gets an account for free. Two rules carry the model:

- `views/base.py::puede_editar_animal(user, animal)` — the rescuer who loaded the animal
  (`cargado_por`), or any superuser. Use it for anything scoped to one animal: editing it,
  changing its state, its adoption forms, its contract and the contract PDF.
- `views/base.py::SuperuserRequiredMixin` — team-only actions with no per-animal owner:
  approving an animal, writing internal notes, linking the Instagram account. The `/tools/`
  views predate the mixin and inline the same check, returning plain text instead of a
  redirect; match whichever style the file already uses.

Two endpoints are deliberately open and must stay that way: `/contrato/<hash>/`, where the
adopter fills in their half without an account, and `/animal/photos/`, used by the public
pre-adoption form (it only serves approved animals).

Anything reached by a sequential id (`/formulario/<id>/…`, `/contrato_adopcion/<id>/…`) is
enumerable, so it needs an ownership check, not just a login.

## Known rough edges

- `requirements.txt` is a `pip freeze` of the production box and is **incomplete**: Pillow,
  reportlab and Twisted are commented out, and openai, tiktoken, pathlib2, selenium,
  django-conventions and PyPDF2's runtime companions are needed but variously missing. Expect
  to install missing packages by hand.
- `catus/services/tables.py` is an unused near-duplicate of `services/base.py`; only
  `services/base.py` is imported anywhere. Don't edit both.
- Most of `BaseService` is dead: its methods still call `dict.iteritems()` (Python 2) and
  `open_search`, the one part that used to run, lost its only caller when the broken
  `/formslist/` view was removed. `render` is what's actually in use.
- Positional lookups against `forms_builder` data are a recurring source of bugs — the app
  used to pick the public form with `Form.objects.all()[0]`/`[3]` and the animal dropdown
  with `Field.objects.all()[0]`. Both now resolve by `slug`/`label`. Don't reintroduce
  index-based lookups: deleting one form in the admin silently shifts the rest.
- The public form's answers are attacker-controlled text. `AdoptionService` marks only the
  `<img>`/`<a>` it builds for uploaded photos as safe; never add `|safe` back to the
  templates that render those values.
- Rich text written by users (`Animal.datos`, `CatusUser.description`) goes through the
  `|html_seguro` filter, backed by `services/html_seguro.py` — an allowlist sanitizer built
  on stdlib. Don't swap it for `|safe`, and don't reach for a sanitizer library: `deploy.sh`
  is a `git pull` with no `pip install`, so a new dependency breaks the next deploy.
- Decimal values written into HTML inputs need `{% localize off %}`. With `LANGUAGE_CODE`
  `es-ar` Django renders `0.25` as `0,25`, which no longer parses as a number on the way
  back — that silently wiped saved Instagram crops.
- `CacheService` talks to memcached on `localhost` with pickled values; every call site is
  currently commented out.
- `MEDIA_URL = "/"` with `MEDIA_ROOT = <repo>/gallery`, so uploads are served from the site
  root, e.g. `/gallery/<uuid>.jpeg`.
- Broad `try/except: pass` is common in this codebase (signals, form parsing, email sending).
  Match the surrounding style rather than tightening it opportunistically, but don't add new
  bare excepts around code you write.
- `test.html` (600KB of saved Instagram HTML) and `forms.sql` at the repo root are scratch
  data, not part of the app.
