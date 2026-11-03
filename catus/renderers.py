from bootstrap4.renderers import FieldRenderer as BootstrapFieldRenderer


class FieldRenderer(BootstrapFieldRenderer):
    """django-bootstrap4's, without the <br> it puts before a file input (the
    1.1.1 the forms were laid out with had none: it added a blank line under
    every attachment's label)."""

    def fix_file_input_label(self, html):
        return html
