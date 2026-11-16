import uuid
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
import os.path
from io import BytesIO


def text_size(font, text):
    """What FreeTypeFont.getsize gave before Pillow 10 removed it: the
    bottom-right corner of the text's box, from the drawing origin."""
    left, top, right, bottom = font.getbbox(text)
    return right, bottom


class ImageService():

    #el posteo de Instagram recorta un cuadrado del LADO CORTO de la foto, así que
    #achicar por debajo de esto es perder nitidez justo en lo que se publica
    LADO_CUADRADO_IG = 1200

    #tope duro para que una foto muy alargada no se guarde entera
    TOPE_LADO_LARGO = 2600

    #El posteo: la foto ocupa todo el lienzo y abajo, centrada, va una tarjeta blanca con
    #el nombre, la edad y el sexo, y el logo (ver generate_logo_image). Reemplazó en
    #noviembre de 2026 al marco blanco con la barra verde y el logo en un círculo, que
    #tapaba la esquina de la foto y que la grilla del perfil cortaba.
    LADO_LIENZO_POSTEO = 1400

    #La grilla del perfil de Instagram muestra las miniaturas en vertical (3:4) y a un
    #posteo cuadrado le corta 175 px de cada costado. Todo lo que tiene que leerse queda
    #entre estas dos x: con el diseño anterior la grilla mostraba "ngela" en vez de
    #"Ángela" y medio logo.
    FRANJA_SEGURA = (190, 1210)

    #la tarjeta: dónde termina (su borde de abajo) y sus márgenes por dentro
    TARJETA_ABAJO = 1310
    TARJETA_PADDING_X = 54
    TARJETA_PADDING_ARRIBA = 60
    TARJETA_PADDING_ABAJO = 48
    TARJETA_RADIO = 34
    TARJETA_BORDE = 4
    LOGO_ALTO_EN_TARJETA = 104
    HUECO_TEXTO_LOGO = 44

    #El nombre va en un renglón con el tamaño más grande que entre, mientras no baje de
    #MINIMO_NOMBRE_EN_UN_RENGLON; si no, en dos renglones. La edad y el sexo se achican
    #hasta entrar: los escribe el rescatista y pueden ser larguísimos.
    TAMANOS_NOMBRE = (140, 126, 112, 100, 88, 76)
    MINIMO_NOMBRE_EN_UN_RENGLON = 88
    TAMANOS_EDAD_SEXO = (54, 50, 46, 42, 38, 34)
    #por debajo de esto el texto ya no se lee; solo se llega con textos absurdos
    TAMANO_MINIMO = 20

    #Open Sans, la letra del sitio (licencia en static/fonts/OPEN-SANS-LICENSE.txt). En
    #woff2: el Pillow de la imagen de producción los lee directo.
    FUENTE_NOMBRE = "opensans-extrabold.woff2"
    FUENTE_EDAD_SEXO = "opensans-semibold.woff2"

    #los colores del sitio (catus/static/css/modern.css)
    COLOR_TARJETA = (255, 255, 255)
    COLOR_BORDE_TARJETA = (226, 211, 250)  #lavanda, como el borde de las fichas
    COLOR_NOMBRE = (138, 43, 226)  #--primary-color
    COLOR_EDAD_SEXO = (45, 55, 72)  #--text-color
    COLOR_SEPARADOR = (138, 43, 226)
    SEPARADOR_EDAD_SEXO = "  ·  "

    #Las posiciones del nombre y la edad eran del diseño anterior, que los dibujaba arriba
    #o abajo a la izquierda. La tarjeta va siempre centrada abajo, así que ya no mueven
    #nada en el posteo; se siguen guardando y pasando para no tocar las pantallas que las
    #leen.
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

    def bytes_optimizados(self, archivo, max_width):
        """Los bytes exactos que optimize() guardaría para esta foto, sin guardar nada.

        Está aparte porque lo que queda en el disco no es lo que se subió: optimize()
        reencoda siempre. Para saber si una foto que alguien está subiendo ya está
        guardada en otro animal (services/duplicados.py) hay que comparar contra esto, no
        contra el archivo subido. Tiene que ser la misma cuenta que usa optimize(): si se
        copiara, alcanza con cambiarle la calidad a una de las dos para que la comparación
        deje de encontrar nada, sin que falle ningún guardado.
        """

        OUTPUT_FORMAT = "JPEG"
        OUTPUT_QUALITY = 70

        img = Image.open(archivo)
        img = img.convert('RGB')

        ratio = self._ratio_para_optimizar(img.size, max_width)

        if ratio < 1.0:
            #truncar dejaba el lado corto un pixel abajo del cuadrado (2191 * 1200/2191 da
            #1199.9999..., o sea 1199) y el posteo de IG volvía a armarse estirando
            nuevo_tamano = (max(1, int(round(img.size[0] * ratio))), max(1, int(round(img.size[1] * ratio))))
            img = img.resize(nuevo_tamano, Image.LANCZOS)

        img = self.rotate(img)

        output = BytesIO()
        img.save(output, format=OUTPUT_FORMAT, quality=OUTPUT_QUALITY, optimize=True, progressive=True)

        return output.getvalue()

    def optimize(self, image_field, max_width):

        contenido = self.bytes_optimizados(image_field, max_width)

        random_name = f'{uuid.uuid4()}.jpeg'

        file = File(ContentFile(contenido))

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
                return img.crop(box).resize((base_size, base_size), Image.LANCZOS)

        is_horizontal_image = img.size[0] > img.size[1]

        if is_horizontal_image:
            #horizontal image
            wpercent = (base_size / float(img.size[1]))
            hsize = int((float(img.size[0]) * float(wpercent)))

            img = img.resize((hsize, base_size), Image.LANCZOS)
        else:
            #vertical image
            wpercent = (base_size / float(img.size[0]))
            hsize = int((float(img.size[1]) * float(wpercent)))

            img = img.resize((base_size, hsize), Image.LANCZOS)

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

        return text_size(self.get_font(fuente, tamano), texto or "")[0]

    def tamano_que_entra(self, texto, fuente, ancho_disponible, tamanos):
        """El tamaño más grande, de los que se ofrecen, con el que el texto entra.

        Se mide con la fuente de verdad en vez de estimar por la cantidad de letras: una
        "i" y una "W" no ocupan lo mismo, y lo que decide si el renglón se sale de la
        tarjeta es el ancho en píxeles. Si no entra ni con el más chico, se sigue
        achicando de a 2 hasta TAMANO_MINIMO: la edad la escribe el rescatista a mano, y
        un renglón que se sale de la tarjeta (y de lo que muestra la grilla) es peor que
        uno chico.
        """

        candidatos = sorted(tamanos, reverse=True)
        candidatos += list(range(candidatos[-1] - 2, self.TAMANO_MINIMO - 1, -2))

        for tamano in candidatos:
            if self.ancho_del_texto(texto, fuente, tamano) <= ancho_disponible:
                return tamano

        return self.TAMANO_MINIMO

    def ancho_del_nombre(self, nombre, tamano):
        """Cuánto mide el nombre en píxeles, con la fuente con la que se va a dibujar."""

        return self.ancho_del_texto(nombre, self.FUENTE_NOMBRE, tamano)

    def logo_para_la_tarjeta(self):
        """El logo negro del sitio, recortado a lo que tiene dibujado y del alto de la tarjeta."""

        logo = Image.open(os.path.join(settings.STATICFILES_DIRS[0], "logo_2.png")).convert("RGBA")
        logo = logo.crop(logo.getchannel("A").getbbox())
        alto = self.LOGO_ALTO_EN_TARJETA
        return logo.resize((round(logo.size[0] * alto / logo.size[1]), alto), Image.LANCZOS)

    def ancho_para_el_texto_de_la_tarjeta(self, logo):
        """Lo que le queda al texto: la franja segura, menos los márgenes y el logo."""

        izquierda, derecha = self.FRANJA_SEGURA
        return derecha - izquierda - 2 * self.TARJETA_PADDING_X - logo.size[0] - self.HUECO_TEXTO_LOGO

    def partir_en_dos(self, texto, tamano, ancho_disponible):
        """El texto en un renglón si entra; si no, en dos, cortando en el espacio que deja
        los dos renglones más parejos. Una palabra sola no se corta."""

        if self.ancho_del_nombre(texto, tamano) <= ancho_disponible or " " not in texto.strip():
            return [texto]

        palabras = texto.split()
        mejor = None
        for i in range(1, len(palabras)):
            renglones = [" ".join(palabras[:i]), " ".join(palabras[i:])]
            mas_largo = max(self.ancho_del_nombre(r, tamano) for r in renglones)
            if mejor is None or mas_largo < mejor[0]:
                mejor = (mas_largo, renglones)

        return mejor[1]

    def nombre_en_renglones(self, nombre, ancho_disponible):
        """(tamaño, renglones) del nombre en la tarjeta.

        Un renglón con el tamaño más grande que entre, mientras no baje de
        MINIMO_NOMBRE_EN_UN_RENGLON: "Tomy bicolor" va en uno solo. Si no, dos renglones
        con el tamaño más grande que entre, y si ni así, se sigue achicando: "Bartolomeo
        Maximiliano de los Santos" mide 2356 px con 150, sobre 1400 de lienzo.
        """

        nombre = (nombre or "").strip() or "Sin nombre"

        for tamano in self.TAMANOS_NOMBRE:
            if tamano < self.MINIMO_NOMBRE_EN_UN_RENGLON:
                break
            if self.ancho_del_nombre(nombre, tamano) <= ancho_disponible:
                return tamano, [nombre]

        candidatos = list(self.TAMANOS_NOMBRE)
        candidatos += list(range(candidatos[-1] - 4, self.TAMANO_MINIMO - 1, -4))
        for tamano in candidatos:
            renglones = self.partir_en_dos(nombre, tamano, ancho_disponible)
            if all(self.ancho_del_nombre(r, tamano) <= ancho_disponible for r in renglones):
                return tamano, renglones

        return self.TAMANO_MINIMO, self.partir_en_dos(nombre, self.TAMANO_MINIMO, ancho_disponible)

    def partes_de_edad_y_sexo(self, animal):
        """La edad y el sexo, lo que haya: "Desconocido" no se escribe."""

        partes = []
        if animal.edad and str(animal.edad).strip():
            partes.append(str(animal.edad).strip())
        if animal.sexo != "D":
            partes.append(animal.get_sexo_display())
        return partes

    def texto_de_edad_y_sexo(self, animal):
        """El renglón de abajo de la tarjeta, como se lee."""

        return self.SEPARADOR_EDAD_SEXO.join(self.partes_de_edad_y_sexo(animal))

    def tamano_de_letra_para_edad_y_sexo(self, texto, ancho_disponible=None):
        """El tamaño del renglón de la edad y el sexo: el más grande que entre en la tarjeta.

        El renglón se salía del lienzo: la edad la escribe el rescatista a mano y
        "aproximadamente 3 años y medio - Macho y Hembra" no entraba con el tamaño fijo de
        siempre. Se salía por la derecha y no lo veía nadie, porque el posteo lo arma el cron.
        """

        if ancho_disponible is None:
            ancho_disponible = self.ancho_para_el_texto_de_la_tarjeta(self.logo_para_la_tarjeta())

        return self.tamano_que_entra(texto, self.FUENTE_EDAD_SEXO, ancho_disponible, self.TAMANOS_EDAD_SEXO)

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

        posicion_nombre = imagen.image_posicion_nombre or self.POSICION_NOMBRE_AUTOMATICA
        posicion_edad_sexo = imagen.image_posicion_edad_sexo or self.POSICION_EDAD_SEXO_AUTOMATICA

        if imagen.image_layout:
            contenido = self.generate_logo_image(
                animal,
                imagen.image,
                centered=imagen.image_centered,
                posicion_nombre=posicion_nombre,
                posicion_edad_sexo=posicion_edad_sexo,
                crop=crop,
            ).read()
        else:
            #sin layout se publica la foto tal cual, igual que en /tools/makeimages/
            with imagen.image.open("rb") as archivo:
                contenido = archivo.read()

        #image_font_size NO se toca: es lo que eligió una persona en /tools/makeimages/ con
        #el diseño anterior. La tarjeta elige el tamaño sola.
        imagen.image_posicion_nombre = posicion_nombre
        imagen.image_posicion_edad_sexo = posicion_edad_sexo
        #el recorte queda guardado: así la pantalla muestra el que se usó y la corrida
        #siguiente no propone otro
        imagen.set_crop(crop)

        #save=True guarda de paso los campos de acá arriba: es un solo UPDATE
        imagen.image_for_instagram.save(f'{uuid.uuid4()}.jpeg', ContentFile(contenido), save=True)

        return True

    def generate_logo_image(self, animal, image_field, centered=True, nombre_font_size=None, posicion_nombre=None, posicion_edad_sexo=None, crop=None):
        """El posteo: la foto en todo el lienzo y la tarjeta encima.

        nombre_font_size y las posiciones eran del diseño anterior y ya no cambian nada:
        la tarjeta elige el tamaño sola y va siempre centrada abajo. Se aceptan para no
        romper a quien los pasa.
        """

        #self.rotate() endereza por EXIF, igual que hace suggest_crop antes de medir el
        #recorte: sin esto las fracciones se calculaban sobre la foto derecha y se
        #aplicaban sobre la cruda, o sea sobre el eje equivocado. Para todo lo que entró
        #por EditView es un no-op —optimize() ya la guarda enderezada y sin EXIF—, pero
        #una foto cargada desde el admin conserva su orientación y salía de costado.
        img = self.rotate(Image.open(image_field)).convert("RGBA")
        image = self.crop_to_square(img, self.LADO_LIENZO_POSTEO, centered=centered, crop=crop)

        self.dibujar_tarjeta(image, animal)

        return self.save_image(image)

    def medidas_de_la_tarjeta(self, animal):
        """Todo lo que hace falta para dibujar la tarjeta, sin dibujarla.

        Las alturas salen de medidas fijas de la letra (la altura de las mayúsculas y lo
        que bajan la g o la y), no de la tinta de cada nombre: medir la tinta subía
        "Ángela" (por la g) por encima de "Rocco", y la tarjeta cambiaba de alto con
        cada nombre.
        """

        logo = self.logo_para_la_tarjeta()
        ancho_texto_max = self.ancho_para_el_texto_de_la_tarjeta(logo)

        tamano_nombre, renglones = self.nombre_en_renglones(animal.nombre, ancho_texto_max)
        fuente_nombre = self.get_font(self.FUENTE_NOMBRE, tamano_nombre)

        partes = self.partes_de_edad_y_sexo(animal)
        texto = self.SEPARADOR_EDAD_SEXO.join(partes)
        fuente_linea = None
        if texto:
            fuente_linea = self.get_font(
                self.FUENTE_EDAD_SEXO, self.tamano_de_letra_para_edad_y_sexo(texto, ancho_texto_max))

        alto_mayuscula = -fuente_nombre.getbbox("H", anchor="ls")[1]
        interlinea = round(tamano_nombre * 1.08)

        ancho_texto = max(fuente_nombre.getbbox(r, anchor="ls")[2] for r in renglones)
        alto = self.TARJETA_PADDING_ARRIBA + alto_mayuscula + interlinea * (len(renglones) - 1)

        hueco = alto_linea = 0
        if fuente_linea:
            #lo que bajan la g o la y del nombre, más un respiro, hasta las mayúsculas del renglón
            hueco = round(fuente_nombre.getmetrics()[1] * 0.8) + 18
            alto_linea = -fuente_linea.getbbox("H", anchor="ls")[1]
            ancho_texto = max(ancho_texto, fuente_linea.getbbox(texto, anchor="ls")[2])
            alto += hueco + alto_linea
        else:
            #sin renglón, lo que baja el nombre ocupa el lugar del margen
            alto += round(fuente_nombre.getmetrics()[1] * 0.5)
        alto += self.TARJETA_PADDING_ABAJO

        ancho = 2 * self.TARJETA_PADDING_X + ancho_texto + self.HUECO_TEXTO_LOGO + logo.size[0]
        x = (self.LADO_LIENZO_POSTEO - ancho) // 2
        y = self.TARJETA_ABAJO - alto

        return {
            "caja": (x, y, x + ancho, y + alto),
            "logo": logo,
            "fuente_nombre": fuente_nombre,
            "renglones": renglones,
            "interlinea": interlinea,
            "base_nombre": y + self.TARJETA_PADDING_ARRIBA + alto_mayuscula,
            "fuente_linea": fuente_linea,
            "partes": partes,
            "base_linea": y + self.TARJETA_PADDING_ARRIBA + alto_mayuscula + interlinea * (len(renglones) - 1) + hueco + alto_linea,
        }

    def dibujar_tarjeta(self, image, animal):
        """La tarjeta blanca centrada abajo: el nombre en violeta, la edad y el sexo en gris
        con un punto violeta en el medio, y el logo negro a la derecha. Como la ficha de
        cada animal en el sitio."""

        m = self.medidas_de_la_tarjeta(animal)
        x0, y0, x1, y1 = m["caja"]

        #una sombra suave para que la tarjeta se despegue de fotos claras; se desenfoca
        #solo el pedazo de alrededor, no el lienzo entero
        margen = 60
        zona = (max(0, x0 - margen), max(0, y0 - margen), min(image.size[0], x1 + margen), min(image.size[1], y1 + margen))
        sombra = Image.new("L", (zona[2] - zona[0], zona[3] - zona[1]), 0)
        ImageDraw.Draw(sombra).rounded_rectangle(
            [(x0 - zona[0], y0 - zona[1] + 10), (x1 - zona[0], y1 - zona[1] + 10)], self.TARJETA_RADIO, fill=110)
        sombra = sombra.filter(ImageFilter.GaussianBlur(22))
        negro = Image.new("RGBA", sombra.size, (0, 0, 0, 255))
        negro.putalpha(sombra)
        image.alpha_composite(negro, (zona[0], zona[1]))

        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle([(x0, y0), (x1, y1)], self.TARJETA_RADIO, fill=self.COLOR_TARJETA,
                               outline=self.COLOR_BORDE_TARJETA, width=self.TARJETA_BORDE)

        texto_x = x0 + self.TARJETA_PADDING_X
        base = m["base_nombre"]
        for renglon in m["renglones"]:
            draw.text((texto_x, base), renglon, self.COLOR_NOMBRE, font=m["fuente_nombre"], anchor="ls")
            base += m["interlinea"]

        if m["fuente_linea"]:
            fuente = m["fuente_linea"]
            x = texto_x + 2
            for i, parte in enumerate(m["partes"]):
                if i:
                    draw.text((x, m["base_linea"]), self.SEPARADOR_EDAD_SEXO, self.COLOR_SEPARADOR, font=fuente, anchor="ls")
                    x += fuente.getlength(self.SEPARADOR_EDAD_SEXO)
                draw.text((x, m["base_linea"]), parte, self.COLOR_EDAD_SEXO, font=fuente, anchor="ls")
                x += fuente.getlength(parte)

        logo = m["logo"]
        image.alpha_composite(logo, (x1 - self.TARJETA_PADDING_X - logo.size[0], y0 + (y1 - y0 - logo.size[1]) // 2))

    def resize(self, image_field, base_width):
        """Achica el banner o el logo del perfil para que ningún lado pase de base_width.
        Nunca agranda.

        Escalaba siempre para dejar el ANCHO en base_width, aunque lo que pasara el límite
        fuera el alto: un banner vertical de 1080x1920 (límite 1500) quedaba en 1500x2666 y
        un logo de 400x800 (límite 500) en 500x1000, agrandados en vez de achicados y con el
        alto todavía por encima del límite. Ahora se escala por el lado largo.
        """

        img = Image.open(image_field)

        lado_largo = max(img.size)
        if lado_largo > base_width:

            ratio = base_width / float(lado_largo)
            nuevo_tamano = (max(1, round(img.size[0] * ratio)), max(1, round(img.size[1] * ratio)))

            img = img.resize(nuevo_tamano, Image.LANCZOS)

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

# How many pixels a photo that comes from outside may declare. The header says it before
# anything is decoded, and decoding is what costs: a palette PNG of a couple of hundred KB
# can declare 13000×13000 and take close to 1 GB once loaded and turned into RGBA, and the
# public form shrank every file in the POST before validating anything. A JPEG is decoded
# already reduced (draft), so it may be as big as a 108 Mpx phone photo; PNG and WEBP have
# no such shortcut. Pillow's own limit (MAX_IMAGE_PIXELS, set from this in CatusConfig)
# only warns below twice its value, so it is not the check: these are.
MAX_PIXELES = 110_000_000
MAX_PIXELES_SIN_REDUCIR = 40_000_000
MENSAJE_FOTO_GRANDE = ("Una de las fotos es demasiado grande para procesarla. "
                       "Probá con otra foto o con una captura de pantalla.")


class FotoDemasiadoGrande(Exception):
    """The photo declares more pixels than we are willing to decode."""


def revisar_pixeles(image):
    """Raise FotoDemasiadoGrande when an opened (not yet loaded) image is too big."""
    width, height = image.size
    limite = MAX_PIXELES if image.format in ("JPEG", "MPO") else MAX_PIXELES_SIN_REDUCIR
    if width * height > limite:
        raise FotoDemasiadoGrande()


def abrir_foto_subida(archivo, lado=UPLOAD_MAX_SIDE):
    """An uploaded photo, opened and loaded without decoding more than it needs.

    A JPEG is decoded at the smallest scale (1/2, 1/4, 1/8) that still leaves both sides
    at least `lado`. FotoDemasiadoGrande if it declares too many pixels; whatever else
    Pillow raises (not an image, truncated) goes up as is.
    """
    try:
        image = Image.open(archivo)
    except Image.DecompressionBombError:
        raise FotoDemasiadoGrande()
    revisar_pixeles(image)
    if image.format in ("JPEG", "MPO"):
        image.draft(None, (lado, lado))
    image.load()
    return image


def shrink_uploaded_image(upload):
    """A smaller copy of an uploaded photo, or the upload itself when it is not
    a photo Pillow can read (HEIC, video, PDF) or would not get smaller.
    FotoDemasiadoGrande when it declares more pixels than we decode."""
    from django.core.files.uploadedfile import InMemoryUploadedFile

    try:
        upload.seek(0)
        image = Image.open(upload)
        fmt = image.format  # by content: some .jpg are PNG or WEBP inside
        if fmt not in ("JPEG", "MPO", "PNG", "WEBP"):
            upload.seek(0)
            return upload
    except Image.DecompressionBombError:
        raise FotoDemasiadoGrande()
    except Exception:
        upload.seek(0)
        return upload

    revisar_pixeles(image)
    try:
        if fmt in ("JPEG", "MPO"):
            image.draft(None, (UPLOAD_MAX_SIDE, UPLOAD_MAX_SIDE))
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
    # A big upload arrives as a TemporaryUploadedFile, which has no field_name.
    return InMemoryUploadedFile(output, getattr(upload, "field_name", None), upload.name, content_type, size, None)


def shrink_uploads(files, claves=None):
    """request.FILES with every photo in it shrunk; anything else untouched.

    With `claves`, only those keys are kept: the form's own file fields. Anything else in
    the POST is dropped without being opened, since nobody reads it and every file costs a
    decode. FotoDemasiadoGrande goes up to the caller."""
    if not files:
        return files
    from django.utils.datastructures import MultiValueDict

    shrunk = MultiValueDict()
    for key in files:
        if claves is not None and key not in claves:
            continue
        shrunk.setlist(key, [shrink_uploaded_image(f) for f in files.getlist(key)])
    return shrunk
