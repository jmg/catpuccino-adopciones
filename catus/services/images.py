import uuid
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
import os.path
from io import BytesIO


class ImageService():

    #el posteo de Instagram recorta un cuadrado del LADO CORTO de la foto, así que
    #achicar por debajo de esto es perder nitidez justo en lo que se publica
    LADO_CUADRADO_IG = 1200

    #tope duro para que una foto muy alargada no se guarde entera
    TOPE_LADO_LARGO = 2600

    #el lienzo del posteo: 1200 de foto + 200 de marco blanco (ver generate_logo_image)
    LADO_LIENZO_POSTEO = 1400

    #add_nombre_y_edad dibuja la barra del nombre desde x=0 hasta 130 + el ancho del texto
    MARGEN_BARRA_NOMBRE = 130

    #que la barra no llegue a tocar el borde: el mismo margen que se le deja al logo
    MARGEN_BORDE_POSTEO = 40

    #los mismos tamaños que ofrece /tools/generarimagen/: la elección automática no puede
    #terminar en un tamaño que después nadie pueda reproducir a mano desde la pantalla
    TAMANOS_NOMBRE = (150, 125, 100, 75, 50)

    #el renglón de abajo (edad y sexo) no lo ofrece ninguna pantalla, así que acá los
    #tamaños son sólo el margen que tiene el ajuste automático para achicarlo
    TAMANOS_EDAD_SEXO = (60, 50, 40, 30, 25)

    FUENTE_NOMBRE = "impact.ttf"
    FUENTE_EDAD_SEXO = "montserrat.ttf"

    #add_nombre_y_edad escribe la edad y el sexo empezando en esta x
    MARGEN_TEXTO_EDAD_SEXO_X = 140

    #Arriba, que es donde venía cayendo el default de /tools/makeimages/ ("Izquierda").
    #Abajo la barra del nombre se dibuja DESPUÉS del logo y sobre las mismas coordenadas:
    #con un nombre largo le pasa por encima y el posteo sale sin logo.
    POSICION_NOMBRE_AUTOMATICA = "Izquierda (arriba)"
    POSICION_EDAD_SEXO_AUTOMATICA = "Izquierda (arriba)"

    def _ratio_para_optimizar(self, size, max_width):
        """Cuánto achicar una foto recién subida. Devuelve 1.0 si no hay que tocarla.

        Escalar siempre por el ancho agrandaba las verticales (1080x1920 -> 1200x2133).
        Pero escalar por el lado largo a secas las achicaba a 675x1200, y entonces el
        cuadrado de Instagram se armaba estirando 675 hasta 1200: peor todavía, porque
        tira los píxeles que ese recorte necesita. Se achica por el lado largo, sin
        bajar el lado corto de lo que pide el cuadrado, y sin agrandar nunca.
        """

        lado_corto, lado_largo = min(size), max(size)

        if not lado_corto or not lado_largo:
            return 1.0

        #si la foto ya venía con el lado corto por debajo del cuadrado, se respeta:
        #no hay nada que ganar estirándola. Y el piso tampoco puede pasarse del ancho que
        #pidieron a mano: mientras miraba sólo el cuadrado, un --max-width 600 sobre una
        #3000x2000 devolvía 1800x1200, exactamente lo mismo que sin el flag
        minimo_corto = min(lado_corto, self.LADO_CUADRADO_IG, max_width)

        ratio = min(1.0, max_width / float(lado_largo))

        if lado_corto * ratio < minimo_corto:
            ratio = minimo_corto / float(lado_corto)

        #una panorámica podría quedar enorme al respetar el lado corto: le ponemos techo
        if lado_largo * ratio > self.TOPE_LADO_LARGO:
            ratio = self.TOPE_LADO_LARGO / float(lado_largo)

        return min(ratio, 1.0)

    def necesita_optimizar(self, size, max_width):
        """¿Esta foto va a cambiar de tamaño, o no hay nada que hacerle?

        optimize() siempre reencoda a JPEG 70 y siempre guarda con nombre nuevo, borrando
        el archivo anterior: pasarle una foto que ya está en tamaño le baja la calidad una
        vez por corrida y rompe las URLs que ya salieron por mail.
        """

        return self._ratio_para_optimizar(size, max_width) < 1.0

    def optimize(self, image_field, max_width):

        OUTPUT_FORMAT = "JPEG"
        OUTPUT_QUALITY = 70

        img = Image.open(image_field)
        img = img.convert('RGB')

        random_name = f'{uuid.uuid4()}.jpeg'

        ratio = self._ratio_para_optimizar(img.size, max_width)

        if ratio < 1.0:
            #truncar dejaba el lado corto un pixel abajo del cuadrado (2191 * 1200/2191 da
            #1199.9999..., o sea 1199) y el posteo de IG volvía a armarse estirando
            nuevo_tamano = (max(1, int(round(img.size[0] * ratio))), max(1, int(round(img.size[1] * ratio))))
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

    def get_font(self, fuente, tamano):

        fonts_dir = os.path.join(settings.STATICFILES_DIRS[0], "fonts")

        return ImageFont.truetype(os.path.join(fonts_dir, fuente), tamano)

    def ancho_del_texto(self, texto, fuente, tamano):
        """Cuánto mide un texto en píxeles, con la fuente con la que se va a dibujar."""

        return self.get_font(fuente, tamano).getsize(texto or "")[0]

    def tamano_que_entra(self, texto, fuente, ancho_disponible, tamanos):
        """El tamaño más grande, de los que se ofrecen, con el que el texto entra.

        Se mide con la fuente de verdad en vez de estimar por la cantidad de letras: una
        "i" y una "W" no ocupan lo mismo, y lo que decide si el renglón se sale del
        lienzo es el ancho en píxeles.
        """

        for tamano in sorted(tamanos, reverse=True):
            if self.ancho_del_texto(texto, fuente, tamano) <= ancho_disponible:
                return tamano

        #un texto absurdamente largo no entra ni con el más chico: se usa igual, porque
        #recortarle el nombre (o la edad) al animal es peor que un renglón que se pasa
        return min(tamanos)

    def ancho_del_nombre(self, nombre, tamano):
        """Cuánto mide el nombre en píxeles, con la fuente con la que se va a dibujar."""

        return self.ancho_del_texto(nombre, self.FUENTE_NOMBRE, tamano)

    def tamano_de_letra_para_el_nombre(self, nombre):
        """El tamaño más grande, de los que ofrece la pantalla, con el que la barra entra.

        Con el default de 150, "Bartolomeo Maximiliano de los Santos" mide 2356 px sobre
        un lienzo de 1400: la barra se iba por la derecha y el nombre salía cortado.
        Mientras las imágenes se armaban a mano no importaba —el que las generaba veía la
        previsualización y bajaba el tamaño—, pero el cron no mira.
        """

        entra = self.LADO_LIENZO_POSTEO - self.MARGEN_BARRA_NOMBRE - self.MARGEN_BORDE_POSTEO

        return self.tamano_que_entra(nombre, self.FUENTE_NOMBRE, entra, self.TAMANOS_NOMBRE)

    def texto_de_edad_y_sexo(self, animal):
        """El renglón de abajo del posteo."""

        if not animal.edad:
            return animal.get_sexo_display()

        if animal.sexo == "D":
            return u"{}".format(animal.edad)

        return u"{} - {}".format(animal.edad, animal.get_sexo_display())

    def tamano_de_letra_para_edad_y_sexo(self, texto):
        """Lo mismo que para el nombre, pero para el renglón de abajo.

        El ajuste cubría sólo el nombre, así que la edad seguía saliéndose: la escribe el
        rescatista a mano y "aproximadamente 3 años y medio - Macho y Hembra" mide 1661 px
        con los 60 fijos de siempre, sobre 1220 de lienzo útil. Se salía por la derecha y
        no lo veía nadie, porque el posteo lo arma el cron.
        """

        entra = self.LADO_LIENZO_POSTEO - self.MARGEN_TEXTO_EDAD_SEXO_X - self.MARGEN_BORDE_POSTEO

        return self.tamano_que_entra(texto, self.FUENTE_EDAD_SEXO, entra, self.TAMANOS_EDAD_SEXO)

    def generar_imagen_para_instagram(self, imagen, forzar=False):
        """Arma y guarda el image_for_instagram de una foto, sin nadie mirando.

        Es la misma composición que hace /tools/makeimages/, pero con lo que ya tiene
        guardado la foto (layout, centrado, posiciones) en vez de con lo que venga del
        POST, y con el recorte que eligió el rescatista o, si no eligió ninguno, el que
        propone suggest_crop().

        Devuelve False si la foto ya tenía su imagen: rearmarla cuesta segundos de CPU,
        guarda un archivo nuevo con otro nombre y deja colgada la URL que ya se le pasó a
        Instagram.
        """

        if imagen.image_for_instagram and not forzar:
            return False

        animal = imagen.animal

        crop = imagen.get_crop()
        if crop is None:
            crop = self.suggest_crop(imagen.image)

        #el tamaño guardado es un techo, no una orden: el default del modelo son 150 y
        #nadie los eligió, así que bajarlo cuando el nombre no entra no le pisa la decisión
        #a nadie; al revés, un 50 elegido a mano se respeta
        tamano = min(
            imagen.image_font_size or max(self.TAMANOS_NOMBRE),
            self.tamano_de_letra_para_el_nombre(animal.nombre),
        )

        posicion_nombre = imagen.image_posicion_nombre or self.POSICION_NOMBRE_AUTOMATICA
        posicion_edad_sexo = imagen.image_posicion_edad_sexo or self.POSICION_EDAD_SEXO_AUTOMATICA

        if imagen.image_layout:
            contenido = self.generate_logo_image(
                animal,
                imagen.image,
                centered=imagen.image_centered,
                nombre_font_size=tamano,
                posicion_nombre=posicion_nombre,
                posicion_edad_sexo=posicion_edad_sexo,
                crop=crop,
            ).read()
        else:
            #sin layout se publica la foto tal cual, igual que en /tools/makeimages/
            with imagen.image.open("rb") as archivo:
                contenido = archivo.read()

        imagen.image_font_size = tamano
        imagen.image_posicion_nombre = posicion_nombre
        imagen.image_posicion_edad_sexo = posicion_edad_sexo
        #el recorte queda guardado: así la pantalla muestra el que se usó y la corrida
        #siguiente no propone otro
        imagen.set_crop(crop)

        #save=True guarda de paso los campos de acá arriba: es un solo UPDATE
        imagen.image_for_instagram.save(f'{uuid.uuid4()}.jpeg', ContentFile(contenido), save=True)

        return True

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

        draw = ImageDraw.Draw(image)
        font = self.get_font(self.FUENTE_NOMBRE, nombre_font_size)

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

        bottom_text = self.texto_de_edad_y_sexo(animal)

        font2 = self.get_font(self.FUENTE_EDAD_SEXO, self.tamano_de_letra_para_edad_y_sexo(bottom_text))

        margin_text_bottom_x = self.MARGEN_TEXTO_EDAD_SEXO_X
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
