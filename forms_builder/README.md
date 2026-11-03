# forms_builder

django-forms-builder 0.14.0 (Stephen McDonald, BSD; LICENSE), the last release,
copied here because it does not run on current Django: it used APIs that
Django 3.0-4.0 removed (`python_2_unicode_compatible`, `ugettext`,
`models.permalink`, `render_to_response`, `request.is_ajax()`,
`Signal(providing_args=...)`, `urlquote`) and the `future` package. The port
changes only that, plus:

- `send_mail_template` lives in `forms/utils.py`: it came from
  django-email-extras, which does not run on current Django either. Same mails,
  without its GnuPG encryption, which no form here used.
- The admin's "View form on site / entries / export" links show as links again
  (`allow_tags` stopped working in Django 2.0, which escaped them).
- The entries page loads its jQuery over https (over http browsers block it).
- `forms/migrations/0003_sizes_from_settings.py` gives label and help text the
  sizes from the site's settings (1000), which the tables already had; there
  it changes nothing.

The app keeps its label (`forms`) and tables, so the data stays as it was.
