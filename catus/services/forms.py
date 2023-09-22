from catus.services.utils.render import render, render_string


def render_comments(estado_form):

    return render("forms/table_comments.html", {"estado_form": estado_form })