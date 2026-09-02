import uuid
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
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

        #se escala por el lado LARGO: escalando siempre por el ancho, una foto vertical
        #de celular (1080x1920) terminaba agrandada a 1200x2133, mas pesada y sin mas detalle
        if max(img.size) > max_width:

            ratio = max_width / float(max(img.size))
            nuevo_tamano = (max(1, int(img.size[0] * ratio)), max(1, int(img.size[1] * ratio)))

            img = img.resize(nuevo_tamano, Image.ANTIALIAS)

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

    def crop_box_from_fractions(self, img, crop):
        """Convierte un recorte en fracciones (x, y, w, h) a una caja cuadrada de pixeles."""

        width, height = img.size

        left = max(0, int(round(crop[0] * width)))
        top = max(0, int(round(crop[1] * height)))
        right = min(width, int(round((crop[0] + crop[2]) * width)))
        bottom = min(height, int(round((crop[1] + crop[3]) * height)))

        #el selector recorta en cuadrado, pero los redondeos pueden dejarlo apenas rectangular
        side = min(right - left, bottom - top)
        if side <= 0:
            return None

        return (left, top, left + side, top + side)

    def crop_to_square(self, img, base_size, centered=True, crop=None):
        """Recorta la foto a un cuadrado de base_size x base_size.

        Si viene un recorte manual (fracciones) se respeta tal cual. Si no, se cae al
        recorte automatico de siempre: escalar el lado corto y cortar desde el borde
        o desde el centro.
        """

        if crop is not None:
            box = self.crop_box_from_fractions(img, crop)
            if box is not None:
                return img.crop(box).resize((base_size, base_size), Image.ANTIALIAS)

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
                    img_centered_start_y = int((img.size[1] - base_size) / 2)

                boundaries = (0, img_centered_start_y, base_size, base_size + img_centered_start_y)
            else:
                #horizontal image
                if img.size[0] > base_size:
                    img_centered_start_x = int((img.size[0] - base_size) / 2)

                boundaries = (img_centered_start_x, 0, base_size + img_centered_start_x, base_size)
        else:
            boundaries = (0, img_centered_start_y, base_size, base_size + img_centered_start_y)

        return img.crop(boundaries)

    def suggest_crop(self, image_field, steps=40, center_bias=0.12):
        """Propone el recorte cuadrado que mas detalle concentra (donde suele estar el animal).

        Devuelve (x, y, w, h) en fracciones, o None si la foto ya es cuadrada o no se pudo leer.
        """

        try:
            #si es un campo de Django leemos del disco: viene de optimize(), que ya lo cerro
            source = getattr(image_field, "path", None)
            if not source:
                source = image_field
                if hasattr(image_field, "seek"):
                    image_field.seek(0)

            img = self.rotate(Image.open(source).convert("L"))
        except Exception:
            return None

        width, height = img.size
        if width == height or width < 2 or height < 2:
            return None

        #la busqueda corre sobre una version chica: alcanza para ubicar al animal y es instantanea
        preview_size = 240
        scale = preview_size / float(max(width, height))
        preview = img.resize((max(1, int(width * scale)), max(1, int(height * scale))))
        edges = preview.filter(ImageFilter.FIND_EDGES)

        #FIND_EDGES dibuja como borde el marco de la foto: si no lo apagamos, todo recorte
        #pegado a un borde suma energia falsa y la sugerencia se va justo para afuera
        ImageDraw.Draw(edges).rectangle([0, 0, edges.size[0] - 1, edges.size[1] - 1], outline=0)

        preview_width, preview_height = preview.size
        side = min(preview_width, preview_height)
        is_horizontal = preview_width > preview_height
        long_side = preview_width if is_horizontal else preview_height
        span = long_side - side

        if span <= 0:
            return None

        best_offset = 0
        best_score = None

        #recorremos del centro hacia los bordes: si dos posiciones empatan (una foto plana,
        #un fondo liso) nos quedamos con la mas centrada
        offsets = [int(round(span * step / float(steps))) for step in range(steps + 1)]
        offsets.sort(key=lambda value: abs((value + side / 2.0) - long_side / 2.0))

        for offset in offsets:

            if is_horizontal:
                box = (offset, 0, offset + side, side)
            else:
                box = (0, offset, side, offset + side)

            energy = ImageStat.Stat(edges.crop(box)).sum[0]

            #a igual detalle preferimos el centro, para no pegar el recorte contra un borde
            distance = abs((offset + side / 2.0) - long_side / 2.0)
            score = energy * (1 - center_bias * (distance / (span / 2.0)))

            if best_score is None or score > best_score:
                best_score = score
                best_offset = offset

        offset_fraction = best_offset / float(long_side)

        if is_horizontal:
            return (offset_fraction, 0.0, side / float(preview_width), 1.0)

        return (0.0, offset_fraction, 1.0, side / float(preview_height))

    def generate_logo_image(self, animal, image_field, centered=True, nombre_font_size=150, posicion_nombre="Izquierda", posicion_edad_sexo="Izquierda", crop=None):

        img_parts_dir = os.path.join(settings.STATICFILES_DIRS[0])

        base_size = 1200
        back_margin_white = 200

        logo_size = 250
        offset = 40
        offset2 = 40

        img = Image.open(image_field).convert("RGBA")
        logo = Image.open(os.path.join(img_parts_dir, "logo_2.png")).convert("RGBA")
        logo = logo.resize((logo_size, logo_size), Image.ANTIALIAS)

        img = self.crop_to_square(img, base_size, centered=centered, crop=crop)
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
