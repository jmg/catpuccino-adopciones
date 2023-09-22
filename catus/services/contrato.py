from PyPDF2 import PdfFileWriter, PdfFileReader
import io
import os
from django.conf import settings
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import textwrap


def add_pdf_content(existing_pdf, output, page_num, contrato, tipo):

    page = existing_pdf.getPage(page_num)
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)

    packet.seek(0)
    if page_num == 0:
        set_page_0_content(can, contrato)
    if page_num == 1:
        if tipo == "P":
            set_page_1_content_perros(can, contrato)
        else:
            set_page_1_content(can, contrato)
    if page_num == 2:
        output.addPage(page)
        return
    if page_num == 3:
        set_page_3_content(can, contrato)

    can.save()

    new_pdf = PdfFileReader(packet)

    page.mergePage(new_pdf.getPage(0))
    output.addPage(page)


def write_lines(can, text, offset, chars_lim, _x, _y):

    chunks = textwrap.wrap(text or "", chars_lim)
    for i, chunk in enumerate(chunks):
        _offset = i * offset
        can.drawString(_x, _y - _offset, chunk)


def draw_circle(can, x, y, radius):

    can.ellipse(x, y, x + radius, y + radius) #x1, y1, x2, y2


def set_page_0_content(can, contrato):

    y = 2
    x = 0

    #DATOS DE LA PERSONA

    if contrato.adoptante.persona_fecha_nacimiento:
        persona_fecha_nacimiento = "{}      {}      {}".format(
            contrato.adoptante.persona_fecha_nacimiento.strftime("%d"),
            contrato.adoptante.persona_fecha_nacimiento.strftime("%m"),
            contrato.adoptante.persona_fecha_nacimiento.strftime("%Y"),
        )
    else:
        persona_fecha_nacimiento = None

    can.drawString(75 + x, 618 + y, contrato.adoptante.persona_nombre or "")
    can.drawString(115 + x, 578 + y + 14, contrato.adoptante.persona_dni or "")

    if persona_fecha_nacimiento:
        can.drawString(410 + x, 578 + y + 14, persona_fecha_nacimiento)

    can.drawString(135 + x, 553 + y + 14, contrato.adoptante.persona_ocupacion or "")
    can.drawString(120 + x, 525 + y + 14, contrato.adoptante.persona_celular or "")

    write_lines(can, contrato.adoptante.persona_direccion or "", 12, 75, 130+x, 498+y+16)

    can.drawString(132 + x, 473 + y + 14, contrato.adoptante.persona_localidad or "")

    can.drawString(132 + x, 445 + y + 14, contrato.adoptante.persona_instagram or "")
    can.drawString(132 + x, 420 + y + 14, contrato.adoptante.persona_facebook or "")
    can.drawString(170 + x, 395 + y + 14, contrato.adoptante.persona_email or "")

    #DATOS DEL ADOPTADO

    can.drawString(122 + x, 313 + y + 14, contrato.gato_nombre or "")
    if contrato.gato_sexo == "M":
        can.ellipse(352 + x, 302 + y + 14, 352 + 50 + x, 302 + 25 + y + 14) #x1, y1, x2, y2
    if contrato.gato_sexo == "H":
        can.ellipse(294 + x, 302 + y + 14, 295 + 55 + x, 302 + 25 + y + 14) #x1, y1, x2, y2

    can.drawString(110 + x, 301 + y, contrato.gato_color or "")

    if contrato.gato_fecha_nacimiento:
        can.drawString(190 + x, 275 + y, contrato.gato_fecha_nacimiento.strftime("%d      %m      %Y"))

    can.drawString(110 + x, 248 + y, contrato.gato_edad)

    return can


def set_page_1_content(can, contrato):

    y = 2
    x = 0

    #DATOS VACUNACION

    if contrato.gato_vacunacion_triple_1_dosis:
        draw_circle(can, 103 + x, 752 + y, 20)
        if contrato.gato_vacunacion_triple_1_dosis_fecha:
            can.drawString(200 + x, 760 + y, contrato.gato_vacunacion_triple_1_dosis_fecha.strftime("%d     %m       %Y"))
    else:
        draw_circle(can, 125 + x, 752 + y, 20)
        can.drawString(200 + x, 760 + y, "-          -         -")

    if contrato.gato_vacunacion_triple_1_dosis_notas:
        write_lines(can, contrato.gato_vacunacion_triple_1_dosis_notas, 12, 40, 320+x, 762+y)

    if contrato.gato_vacunacion_triple_2_dosis:
        draw_circle(can, 103 + x, 699 + y, 20)
        if contrato.gato_vacunacion_triple_2_dosis_fecha:
            can.drawString(200 + x, 707 + y, contrato.gato_vacunacion_triple_2_dosis_fecha.strftime("%d     %m       %Y"))
    else:
        draw_circle(can, 125 + x, 699 + y, 20)
        can.drawString(200 + x, 707 + y, "-          -         -")

    if contrato.gato_vacunacion_triple_2_dosis_notas:
        write_lines(can, contrato.gato_vacunacion_triple_2_dosis_notas, 12, 40, 320+x, 708+y)

    if contrato.gato_vacunacion_antirabica:
        draw_circle(can, 103 + x, 593 + y, 20)
        if contrato.gato_vacunacion_antirabica_fecha:
            can.drawString(200 + x, 600 + y, contrato.gato_vacunacion_antirabica_fecha.strftime("%d     %m       %Y"))
    else:
        draw_circle(can, 125 + x, 593 + y, 20)
        can.drawString(200 + x, 600 + y, "-          -         -")

    if contrato.gato_vacunacion_antirabica_notas:
        write_lines(can, contrato.gato_vacunacion_antirabica_notas, 12, 40, 320+x, 603+y)

    if contrato.gato_castrado:
        draw_circle(can, 134 + x, 540 + y, 20)
        if contrato.gato_castrado_fecha:
            can.drawString(235 + x, 547 + y, contrato.gato_castrado_fecha.strftime("%d      %m       %Y"))
            can.drawString(80 + x, 505 + y, "-          -            -")
    else:
        draw_circle(can, 156 + x, 540 + y, 20)
        can.drawString(235 + x, 547 + y, "-          -            -")
        if contrato.gato_castracion_fecha_futura:
            can.drawString(80 + x, 505 + y, contrato.gato_castracion_fecha_futura.strftime("%d      %m       %Y"))

    if contrato.gato_castrado_notas:
        write_lines(can, contrato.gato_castrado_notas, 12, 55, 75+x, 485+y)

    if contrato.gato_desparasitado:
        draw_circle(can, 113 + x, 419 + y, 20)
        if contrato.gato_desparasitado_fecha:
            can.drawString(210 + x, 425 + y, contrato.gato_desparasitado_fecha.strftime("%d      %m       %Y"))
    else:
        draw_circle(can, 134 + x, 419 + y, 20)
        can.drawString(210 + x, 425 + y, "-          -         -")

    if contrato.gato_desparasitado_2:
        draw_circle(can, 115 + x, 392 + y, 20)
        if contrato.gato_desparasitado_fecha_2:
            can.drawString(210 + x, 399 + y, contrato.gato_desparasitado_fecha_2.strftime("%d      %m       %Y"))
    else:
        draw_circle(can, 137 + x, 392 + y, 20)
        can.drawString(215 + x, 401 + y, "-          -         -")

    if contrato.gato_desparasitado_producto:
        write_lines(can, contrato.gato_desparasitado_producto, 12, 35, 125+x, 375+y)

    if contrato.gato_desparasitado_notas:
        write_lines(can, contrato.gato_desparasitado_notas, 12, 40, 359+x, 375+y)

    if contrato.gato_pipeta_antipulgas:
        draw_circle(can, 135 + x, 313 + y, 20)
        if contrato.gato_pipeta_antipulgas_fecha:
            can.drawString(230 + x, 320 + y, contrato.gato_pipeta_antipulgas_fecha.strftime("%d      %m       %Y"))
    else:
        draw_circle(can, 156 + x, 313 + y, 20)
        can.drawString(233 + x, 320 + y, "-          -          -")

    if contrato.gato_pipeta_antipulgas_producto:
        write_lines(can, contrato.gato_pipeta_antipulgas_producto, 12, 35, 125+x, 295+y)

    if contrato.gato_pipeta_antipulgas_notas:
        write_lines(can, contrato.gato_pipeta_antipulgas_notas, 12, 40, 359+x, 295+y)

    if contrato.gato_alimento:
        write_lines(can, contrato.gato_alimento, 20, 80, 162+x, 240+y)

    if contrato.gato_cuidados_especiales:
        write_lines(can, contrato.gato_cuidados_especiales, 26, 90, 75+x, 150+y)

    return can


def set_page_1_content_perros(can, contrato):

    y = 2
    x = 0

    #DATOS VACUNACION

    if contrato.perro_vacunacion_quintuple_1_dosis:
        draw_circle(can, 103 + x, 752 + y, 20)
        if contrato.perro_vacunacion_quintuple_1_dosis_fecha:
            can.drawString(200 + x, 760 + y, contrato.perro_vacunacion_quintuple_1_dosis_fecha.strftime("%d     %m       %Y"))
    else:
        draw_circle(can, 125 + x, 752 + y, 20)
        can.drawString(200 + x, 760 + y, "-          -         -")

    if contrato.perro_vacunacion_quintuple_1_dosis_notas:
        write_lines(can, contrato.perro_vacunacion_quintuple_1_dosis_notas, 12, 40, 320+x, 762+y)

    if contrato.perro_vacunacion_quintuple_2_dosis:
        draw_circle(can, 103 + x, 699 + y, 20)
        if contrato.perro_vacunacion_quintuple_2_dosis_fecha:
            can.drawString(200 + x, 707 + y, contrato.perro_vacunacion_quintuple_2_dosis_fecha.strftime("%d     %m       %Y"))
    else:
        draw_circle(can, 125 + x, 699 + y, 20)
        can.drawString(200 + x, 707 + y, "-          -         -")

    if contrato.perro_vacunacion_quintuple_2_dosis_notas:
        write_lines(can, contrato.perro_vacunacion_quintuple_2_dosis_notas, 12, 40, 320+x, 708+y)

    if contrato.gato_vacunacion_antirabica:
        draw_circle(can, 103 + x, 542 + y, 20)
        if contrato.gato_vacunacion_antirabica_fecha:
            can.drawString(200 + x, 548 + y, contrato.gato_vacunacion_antirabica_fecha.strftime("%d     %m       %Y"))
    else:
        draw_circle(can, 125 + x, 542 + y, 20)
        can.drawString(200 + x, 548 + y, "-          -         -")

    if contrato.perro_vacunacion_sextuple_1_dosis:
        draw_circle(can, 103 + x, 620 + y, 20)
        if contrato.perro_vacunacion_sextuple_1_dosis_fecha:
            can.drawString(202 + x, 628 + y, contrato.perro_vacunacion_sextuple_1_dosis_fecha.strftime("%d     %m       %Y"))
    else:
        draw_circle(can, 125 + x, 620 + y, 20)
        can.drawString(202 + x, 628 + y, "-          -         -")

    if contrato.perro_vacunacion_sextuple_1_dosis_notas:
        write_lines(can, contrato.perro_vacunacion_sextuple_1_dosis_notas, 12, 40, 330+x, 628+y)

    if contrato.gato_castrado:
        draw_circle(can, 134 + x, 488 + y, 20)
        if contrato.gato_castrado_fecha:
            can.drawString(235 + x, 495 + y, contrato.gato_castrado_fecha.strftime("%d      %m       %Y"))
            can.drawString(80 + x, 455 + y, "-          -            -")
    else:
        draw_circle(can, 156 + x, 488 + y, 20)
        can.drawString(235 + x, 495 + y, "-          -            -")
        if contrato.gato_castracion_fecha_futura:
            can.drawString(80 + x, 455 + y, contrato.gato_castracion_fecha_futura.strftime("%d      %m       %Y"))

    if contrato.gato_castrado_notas:
        write_lines(can, contrato.gato_castrado_notas, 12, 85, 75+x, 435+y)

    if contrato.gato_desparasitado:
        draw_circle(can, 113 + x, 419 + y - 52, 20)
        if contrato.gato_desparasitado_fecha:
            can.drawString(210 + x, 425 + y - 52, contrato.gato_desparasitado_fecha.strftime("%d      %m       %Y"))
    else:
        draw_circle(can, 134 + x, 419 + y - 52, 20)
        can.drawString(210 + x, 425 + y - 52, "-          -         -")

    if contrato.gato_desparasitado_2:
        draw_circle(can, 115 + x, 392 + y - 52, 20)
        if contrato.gato_desparasitado_fecha_2:
            can.drawString(210 + x, 399 + y - 52, contrato.gato_desparasitado_fecha_2.strftime("%d      %m       %Y"))
    else:
        draw_circle(can, 137 + x, 392 + y - 52, 20)
        can.drawString(215 + x, 401 + y - 52, "-          -         -")

    if contrato.gato_desparasitado_producto:
        write_lines(can, contrato.gato_desparasitado_producto, 12, 35, 125+x, 375+y - 52)

    if contrato.gato_desparasitado_notas:
        write_lines(can, contrato.gato_desparasitado_notas, 12, 40, 359+x, 375+y - 52)

    if contrato.gato_pipeta_antipulgas:
        draw_circle(can, 135 + x, 313 + y - 52, 20)
        if contrato.gato_pipeta_antipulgas_fecha:
            can.drawString(230 + x, 320 + y - 52, contrato.gato_pipeta_antipulgas_fecha.strftime("%d      %m       %Y"))
    else:
        draw_circle(can, 156 + x, 313 + y - 52, 20)
        can.drawString(233 + x, 320 + y - 52, "-          -          -")

    if contrato.gato_pipeta_antipulgas_producto:
        write_lines(can, contrato.gato_pipeta_antipulgas_producto, 12, 35, 125+x, 295+y - 52)

    if contrato.gato_pipeta_antipulgas_notas:
        write_lines(can, contrato.gato_pipeta_antipulgas_notas, 12, 40, 359+x, 295+y - 52)

    if contrato.gato_alimento:
        write_lines(can, contrato.gato_alimento, 20, 80, 162+x, 240+y - 52)

    if contrato.gato_cuidados_especiales:
        write_lines(can, contrato.gato_cuidados_especiales, 26, 90, 75+x, 115+y)

    return can


def set_page_3_content(can, contrato):

    y = 2
    x = 0
    meses = {
        "01": "Enero",
        "02": "Febrero",
        "03": "Marzo",
        "04": "Abril",
        "05": "Mayo",
        "06": "Junio",
        "07": "Julio",
        "08": "Agosto",
        "09": "Septiembre",
        "10": "Octubre",
        "11": "Noviembre",
        "12": "Diciembre",
    }

    if contrato.contrato_fecha:
        can.drawString(83 + x, 693 + y, contrato.contrato_fecha.strftime("%d"))
        mes = contrato.contrato_fecha.strftime("%m")
        try:
            mes = meses[str(mes)]
        except:
            pass
        can.drawString(260 + x, 693 + y, mes)

    try:
        year = str(contrato.contrato_fecha.strftime("%y"))[-1]
    except:
        year = "0"

    can.drawString(435 + x, 690 + y, year)

    can.drawString(250 + x, 640 + y, contrato.adoptante.persona_nombre)
    can.drawString(320 + x, 610 + y, contrato.miembro_adopcion_nombre or "")

    return can


def generate_contrato_pdf(contrato, is_test=False):

    tipo = contrato.get_tipo()
    if tipo == "P":
        contrato_file_name = "contrato_perros.pdf"
    else:
        contrato_file_name = "contrato.pdf"

    if not is_test:

        contracto_vacio_file = os.path.join(settings.STATICFILES_DIRS[0], "contrato", contrato_file_name)
        contracto_completado_dir = os.path.join(settings.STATICFILES_DIRS[0], "contrato", contrato.hash)
        if not os.path.exists(contracto_completado_dir):
            os.mkdir(contracto_completado_dir)

        contrato_completado_file_name = "contrato_adopcion_responsable_completado.pdf"
        contrato_completado_file = os.path.join(contracto_completado_dir, contrato_completado_file_name)
    else:
        contracto_vacio_file = contrato_file_name
        contrato_completado_file = "contrato_2.pdf"

    existing_pdf = PdfFileReader(open(contracto_vacio_file, "rb"))
    output = PdfFileWriter()

    add_pdf_content(existing_pdf, output, 0, contrato, tipo)
    add_pdf_content(existing_pdf, output, 1, contrato, tipo)
    add_pdf_content(existing_pdf, output, 2, contrato, tipo)
    add_pdf_content(existing_pdf, output, 3, contrato, tipo)

    outputStream = open(contrato_completado_file, "wb")
    output.write(outputStream)
    outputStream.close()

    with open(contrato_completado_file, "rb") as f:
        outputStream = f.read()

    if not is_test:
        return "/static/contrato/{}/contrato_adopcion_responsable_completado.pdf".format(contrato.hash), outputStream, contrato_completado_file_name