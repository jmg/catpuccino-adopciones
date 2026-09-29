import uuid
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps
from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
import os.path
from io import BytesIO


class ImageService():

    def optimize(self, image_field, max_width):

        OUTPUT_FORMAT = "JPEG"
        OUTPUT_QUALITY = 70

        img = Image.open(image_field)
        img = img.convert('RGB')

        random_name = f'{uuid.uuid4()}.jpeg'

        if img.size[1] > max_width or img.size[0] > max_width:

            wpercent = (max_width / float(img.size[0]))
            hsize = int((float(img.size[1]) * float(wpercent)))

            print (max_width, hsize)
            img = img.resize((max_width, hsize), Image.ANTIALIAS)

        img = self.rotate(img)

        output = BytesIO()
        img.save(output, format=OUTPUT_FORMAT, quality=OUTPUT_QUALITY, optimize=True, progressive=True)
        output.seek(0)

        content_file = ContentFile(output.read())
        file = File(content_file)

        os.remove(image_field.path)

        image_field.save(random_name, file, save=True)

    def rotate(self, image):

        try:
            return ImageOps.exif_transpose(image)
        except:
            return image

    def save_image(self, image):

        OUTPUT_FORMAT = "JPEG"
        OUTPUT_QUALITY = 70

        output = BytesIO()

        image = image.convert('RGB')
        image.save(output, format=OUTPUT_FORMAT, quality=OUTPUT_QUALITY, optimize=True, progressive=True)

        output.seek(0)

        return output

    def generate_logo_image(self, animal, image_field, centered=True, nombre_font_size=150, posicion_nombre="Izquierda", posicion_edad_sexo="Izquierda"):

        img_parts_dir = os.path.join(settings.STATICFILES_DIRS[0])

        base_size = 1200
        back_margin_white = 200

        logo_size = 250
        offset = 40
        offset2 = 40

        img = Image.open(image_field).convert("RGBA")
        logo = Image.open(os.path.join(img_parts_dir, "logo_2.png")).convert("RGBA")
        logo = logo.resize((logo_size, logo_size), Image.ANTIALIAS)
        is_horizontal_image = img.size[0] > img.size[1]

        if is_horizontal_image:
            #horizontal image
            wpercent = (base_size / float(img.size[1]))
            hsize = int((float(img.size[0]) * float(wpercent)))

            img = img.resize((hsize, base_size), Image.ANTIALIAS)
        else:
            #vertical image
            wpercent = (base_size / float(img.size[0]))
            hsize = int((float(img.size[1]) * float(wpercent)))

            img = img.resize((base_size, hsize), Image.ANTIALIAS)

        #cut image to square (centered)
        img_centered_start_y = 0
        img_centered_start_x = 0

        if centered:
            if not is_horizontal_image:
                #vertical image
                if img.size[1] > base_size:
                    img_centered_start_y = img.size[1] / 4

                boundaries = (0, img_centered_start_y, base_size, base_size + img_centered_start_y)
            else:
                #horizontal image
                if img.size[0] > base_size:
                    img_centered_start_x = img.size[0] / 4

                boundaries = (img_centered_start_x, 0, base_size + img_centered_start_x, base_size)
        else:
            boundaries = (0, img_centered_start_y, base_size, base_size + img_centered_start_y)

        img = img.crop(boundaries)
        canvas_size = base_size + back_margin_white

        image = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255))
        image.paste(img, (100, 100), img)

        draw = ImageDraw.Draw(image)

        logo_x = canvas_size - logo.size[0] - offset
        logo_y = canvas_size - logo.size[1] - offset

        draw.ellipse([(logo_x - offset2, logo_y - offset2), (logo_x + logo.size[0] + offset2, logo_y + logo.size[1] + offset2)], fill=(255, 255, 255))

        image.paste(logo, (logo_x, logo_y), logo)

        self.add_nombre_y_edad(animal, image, canvas_size, nombre_font_size, posicion_nombre, posicion_edad_sexo)

        output = self.save_image(image)

        return output

    def add_nombre_y_edad(self, animal, image, canvas_size, nombre_font_size, posicion_nombre, posicion_edad_sexo):

        fonts_dir = os.path.join(settings.STATICFILES_DIRS[0], "fonts")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(os.path.join(fonts_dir, "impact.ttf"), nombre_font_size)

        color_back_animal_nombre = (147, 186, 183)
        color_text_animal_nombre = (255,255,255)
        color_text_bottom_text = (255,255,255)

        back_margin = -5
        if nombre_font_size == 125:
            back_margin = 0
        elif nombre_font_size == 100:
            back_margin = 5
        elif nombre_font_size == 75:
            back_margin = 10
        elif nombre_font_size == 50:
            back_margin = 15

        animal_name_len, animal_name_height = font.getsize(animal.nombre)

        if posicion_nombre == "Izquierda (abajo)":
            position_text_name_y_end = 1160
        else:
            position_text_name_y_end = 260

        margin_text_name_x = 105

        position_back_name_y_end = position_text_name_y_end + 20

        position_text_name_y_start = position_text_name_y_end - animal_name_height

        if posicion_nombre == "Izquierda (arriba)":
            position_back_name_y_start = 100
        else:
            position_back_name_y_start = position_text_name_y_start - back_margin

        position_text_animal_name = (margin_text_name_x, position_text_name_y_start)
        position_back_animal_name_start = (0, position_back_name_y_start)
        position_back_animal_name_end = (130 + animal_name_len, position_back_name_y_end)

        draw.rectangle([position_back_animal_name_start, position_back_animal_name_end], fill=color_back_animal_nombre)
        draw.text(position_text_animal_name, animal.nombre, color_text_animal_nombre, font=font, align='center')

        #if es_plural and sexo.lower() in ["macho", "hembra"]:
        #    sexo = "{}S".format(sexo)

        if animal.edad:
            if animal.sexo == "D":
                bottom_text = u"{}".format(animal.edad)
            else:
                bottom_text = u"{} - {}".format(animal.edad, animal.get_sexo_display())
        else:
            bottom_text = animal.get_sexo_display()

        font2 = ImageFont.truetype(os.path.join(fonts_dir, "montserrat.ttf"), 60)

        margin_text_bottom_x = 140
        if posicion_edad_sexo == "Izquierda (abajo)":
            margin_text_bottom_y = 1205
        else:
            margin_text_bottom_y = 305

        draw.text((margin_text_bottom_x, margin_text_bottom_y), bottom_text, color_text_bottom_text, font=font2)

    def resize(self, image_field, base_width):

        img = Image.open(image_field)

        if img.size[1] > base_width or img.size[0] > base_width:

            wpercent = (base_width / float(img.size[0]))
            hsize = int((float(img.size[1]) * float(wpercent)))

            print (base_width, hsize)
            img = img.resize((base_width, hsize), Image.ANTIALIAS)

            output = self.save_image(img)
            output.seek(0)

            content_file = ContentFile(output.read())
            file = File(content_file)
            random_name = f'{uuid.uuid4()}.jpeg'
            image_field.save(random_name, file, save=False)


# Photos attached to the adoption forms arrive straight from phones: 4000 px
# and several MB each, with nothing that needs more than a screen's worth of
# pixels. They are shrunk on the way in, before forms_builder stores them, so
# the gallery stops growing by ~16 GB a year. The file keeps its name and its
# format, since the name is what the form entry stores and links to; only
# its bytes change, and only when that saves something.
UPLOAD_MAX_SIDE = 1920
UPLOAD_JPEG_QUALITY = 82
UPLOAD_MIN_SAVING = 0.10


def shrink_uploaded_image(upload):
    """A smaller copy of an uploaded photo, or the upload itself when it is not
    a photo Pillow can read (HEIC, video, PDF) or would not get smaller."""
    from django.core.files.uploadedfile import InMemoryUploadedFile

    try:
        upload.seek(0)
        image = Image.open(upload)
        fmt = image.format  # by content: some .jpg are PNG or WEBP inside
        if fmt not in ("JPEG", "MPO", "PNG", "WEBP"):
            upload.seek(0)
            return upload
        image.load()
    except Exception:
        upload.seek(0)
        return upload

    icc = image.info.get("icc_profile")
    extra = {"icc_profile": icc} if icc else {}
    image = ImageOps.exif_transpose(image)  # bake the phone's rotation into the pixels
    output = BytesIO()
    if fmt in ("JPEG", "MPO"):  # MPO: several JPEGs in one file; the first is the photo
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((UPLOAD_MAX_SIDE, UPLOAD_MAX_SIDE), Image.LANCZOS)
        image.save(output, "JPEG", quality=UPLOAD_JPEG_QUALITY, optimize=True, progressive=True, **extra)
        content_type = "image/jpeg"
    elif fmt == "WEBP":
        image.thumbnail((UPLOAD_MAX_SIDE, UPLOAD_MAX_SIDE), Image.LANCZOS)
        image.save(output, "WEBP", quality=UPLOAD_JPEG_QUALITY, method=6, **extra)
        content_type = "image/webp"
    else:  # PNG stays PNG: transparency and exact pixels are why it is a PNG
        if image.mode == "P":
            image = image.convert("RGBA")
        image.thumbnail((UPLOAD_MAX_SIDE, UPLOAD_MAX_SIDE), Image.LANCZOS)
        image.save(output, "PNG", optimize=True, **extra)
        content_type = "image/png"

    size = output.tell()
    upload.seek(0)
    if size > upload.size * (1 - UPLOAD_MIN_SAVING):
        return upload
    output.seek(0)
    return InMemoryUploadedFile(output, upload.field_name, upload.name, content_type, size, None)


def shrink_uploads(files):
    """request.FILES with every photo in it shrunk; anything else untouched."""
    if not files:
        return files
    from django.utils.datastructures import MultiValueDict

    shrunk = MultiValueDict()
    for key in files:
        shrunk.setlist(key, [shrink_uploaded_image(f) for f in files.getlist(key)])
    return shrunk
