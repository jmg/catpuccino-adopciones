from django.dispatch import Signal

# Sent with form=; form_valid also with entry=.
form_invalid = Signal()
form_valid = Signal()
