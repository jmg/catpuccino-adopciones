/*
 * Selector de recorte cuadrado para Instagram.
 *
 * Abre la foto con un cuadro 1:1 que se arrastra y se agranda, y al lado (abajo, en el
 * celular) muestra una vista previa aproximada de como va a quedar el posteo (la foto en
 * todo el cuadrado y, abajo y centrada, la tarjeta con el nombre, la edad y el sexo, y el
 * logo), para poder elegir sin que el animal quede cortado ni tapado.
 *
 * El recorte se guarda en fracciones (0 a 1) de la foto original, asi que no depende
 * del tamano en el que se la muestre.
 *
 *   CatusCrop.open({
 *       src: "/gallery/foto.jpeg",
 *       crop: {x: 0, y: 0.1, w: 1, h: 0.42},   // o null si todavia no tiene
 *       nombre: "Willy",
 *       subtitulo: "2 anios - Macho",
 *       // del diseno anterior: se aceptan, pero la tarjeta va siempre en el mismo lugar
 *       posicionNombre: "Izquierda (abajo)",
 *       posicionEdadSexo: "Izquierda (arriba)",
 *       onSave: function (crop) { ... }        // crop es null si eligio automatico
 *   });
 */
(function (window, document) {
    "use strict";

    // El posteo final es un lienzo de 1400 con la foto en todo el lienzo y, abajo y
    // centrada, una tarjeta blanca con el nombre, la edad y el sexo, y el logo. Las
    // medidas son las de ImageService (catus/services/images.py, medidas_de_la_tarjeta):
    // si cambian alla, cambian aca.
    var CANVAS = 1400;
    var TARJETA_ABAJO = 1310;
    // lo que muestra la grilla del perfil, que corta 175 de cada costado
    var FRANJA_SEGURA = [190, 1210];
    var PADDING_X = 54;
    var PADDING_ARRIBA = 60;
    var PADDING_ABAJO = 48;
    var RADIO = 34;
    var BORDE = 4;
    var HUECO_TEXTO_LOGO = 44;
    var LOGO_ALTO = 104;
    // el png del logo tiene aire alrededor: lo dibujado va de (156, 42) a (824, 936)
    // sobre 980x980, y la tarjeta usa solo eso
    var LOGO_PNG = 980;
    var LOGO_DIBUJO = {x: 156, y: 42, w: 668, h: 894};
    var TAMANOS_NOMBRE = [140, 126, 112, 100, 88, 76];
    var MINIMO_NOMBRE_EN_UN_RENGLON = 88;
    var TAMANOS_EDAD_SEXO = [54, 50, 46, 42, 38, 34];
    var TAMANO_MINIMO = 20;
    // de Open Sans, medidas con Pillow: alto de las mayusculas y lo que bajan g, j, p, q, y
    var MAYUSCULA = 0.714;
    var DESCENSO = 0.3;
    var FUENTE = "'Open Sans', Arial, sans-serif";
    var SEPARADOR = "  \u00b7  ";
    var VIOLETA = "rgb(138,43,226)";

    var STYLE_ID = "catus-crop-styles";

    function percent(value) {
        return (value / CANVAS * 100) + "%";
    }

    function injectStyles() {

        if (document.getElementById(STYLE_ID)) {
            return;
        }

        var css = [
            ".catus-crop-overlay{position:fixed;inset:0;top:0;left:0;right:0;bottom:0;z-index:2000;",
            "background:rgba(0,0,0,.75);display:flex;align-items:center;justify-content:center;padding:15px;}",
            ".catus-crop-dialog{background:#fff;border-radius:16px;max-width:900px;width:100%;",
            "max-height:95vh;overflow:auto;padding:18px;box-shadow:0 10px 40px rgba(0,0,0,.4);}",
            ".catus-crop-title{font-weight:800;margin:0 0 4px;font-size:19px;color:#2d3748;}",
            ".catus-crop-help{margin:0 0 14px;font-size:14px;line-height:1.45;color:#5d6474;}",
            ".catus-crop-body{display:flex;gap:18px;flex-wrap:wrap;}",
            ".catus-crop-stage{flex:1 1 320px;min-width:260px;}",
            ".catus-crop-stage img{max-width:100%;display:block;}",
            ".catus-crop-side{flex:0 0 240px;}",
            ".catus-crop-side-label{font-size:13px;color:#5d6474;margin-bottom:6px;text-align:center;}",
            ".catus-crop-post{position:relative;width:100%;padding-top:100%;background:#fff;",
            "border:1px solid #e2e2e2;border-radius:4px;overflow:hidden;}",
            ".catus-crop-photo{position:absolute;overflow:hidden;background:#f2f2f2;}",
            ".catus-crop-card{position:absolute;box-sizing:border-box;background:#fff;",
            "border-style:solid;border-color:rgb(226,211,250);box-shadow:0 3px 8px rgba(0,0,0,.25);}",
            ".catus-crop-card-name,.catus-crop-card-line{position:absolute;white-space:pre;",
            "line-height:1;font-family:" + FUENTE + ";}",
            ".catus-crop-card-name{font-weight:800;color:" + VIOLETA + ";}",
            ".catus-crop-card-line{font-weight:600;color:rgb(45,55,72);}",
            ".catus-crop-card-line .catus-crop-sep{color:" + VIOLETA + ";}",
            ".catus-crop-card-logo{position:absolute;overflow:hidden;}",
            ".catus-crop-card-logo img{position:absolute;max-width:none;}",
            // Los botones quedan pegados abajo del diálogo: en el celular la foto y la vista
            // previa miden más que la pantalla, y "Guardar recorte" quedaba fuera de vista.
            ".catus-crop-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;",
            "position:sticky;bottom:-18px;z-index:2;background:#fff;",
            "margin:16px -18px -18px;padding:12px 18px 18px;border-top:1px solid #e2d3fa;}",
            ".catus-crop-actions .btn{min-width:120px;}",
            ".catus-crop-actions .btn[disabled]{opacity:.5;cursor:not-allowed;}",
            ".catus-crop-auto{margin-right:auto;}",
            "@media (max-width:640px){",
            ".catus-crop-overlay{padding:8px;}",
            ".catus-crop-dialog{max-height:calc(100vh - 16px);max-height:calc(100dvh - 16px);padding:14px;}",
            // la foto no pasa de media pantalla, así la vista previa asoma sin bajar
            ".catus-crop-stage img{max-height:46vh;width:auto;margin:0 auto;}",
            ".catus-crop-side{flex:0 0 200px;margin:0 auto;}",
            ".catus-crop-actions{bottom:-14px;margin:14px -14px -14px;padding:10px 14px 14px;}",
            ".catus-crop-actions .btn{flex:1 1 40%;min-width:0;padding-left:10px;padding-right:10px;white-space:nowrap;}",
            ".catus-crop-auto{flex-basis:100% !important;order:3;margin-right:0;}}",
            // Con el dedo, las ocho manijas del cuadro miden 20px: las de fábrica son de
            // 5px, salvo la de abajo a la derecha.
            "@media (pointer:coarse){",
            ".catus-crop-stage .cropper-point{width:20px;height:20px;opacity:1;border-radius:50%;",
            "background:" + VIOLETA + ";border:2px solid #fff;}",
            ".catus-crop-stage .cropper-point.point-n{top:-10px;margin-left:-10px;}",
            ".catus-crop-stage .cropper-point.point-s{bottom:-10px;margin-left:-10px;}",
            ".catus-crop-stage .cropper-point.point-e{right:-10px;margin-top:-10px;}",
            ".catus-crop-stage .cropper-point.point-w{left:-10px;margin-top:-10px;}",
            ".catus-crop-stage .cropper-point.point-ne{right:-10px;top:-10px;}",
            ".catus-crop-stage .cropper-point.point-nw{left:-10px;top:-10px;}",
            ".catus-crop-stage .cropper-point.point-se{right:-10px;bottom:-10px;}",
            ".catus-crop-stage .cropper-point.point-sw{left:-10px;bottom:-10px;}",
            ".catus-crop-stage .cropper-point.point-se:before{display:none;}}"
        ].join("");

        var style = document.createElement("style");
        style.id = STYLE_ID;
        style.appendChild(document.createTextNode(css));
        document.head.appendChild(style);
    }

    function make(tag, className, parent) {

        var node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (parent) {
            parent.appendChild(node);
        }
        return node;
    }

    var medidor = null;

    function anchoDe(texto, peso, tamano) {
        /* Cuanto mide un texto con la letra del posteo, en unidades del lienzo. */

        medidor = medidor || document.createElement("canvas").getContext("2d");
        medidor.font = peso + " " + tamano + "px " + FUENTE;
        return medidor.measureText(texto).width;
    }

    function baseDesdeArriba(peso, tamano) {
        /* Con line-height:1, a que distancia del borde de arriba de la caja cae la linea
         * base. Sale de la letra que el navegador uso de verdad, asi que vale tambien si
         * Open Sans no cargo y quedo Arial. */

        medidor = medidor || document.createElement("canvas").getContext("2d");
        medidor.font = peso + " " + tamano + "px " + FUENTE;
        var m = medidor.measureText("H");
        var arriba = m.fontBoundingBoxAscent || tamano * 1.07;
        var abajo = m.fontBoundingBoxDescent || tamano * 0.3;
        return (tamano - arriba - abajo) / 2 + arriba;
    }

    function tamanoQueEntra(texto, peso, ancho, tamanos) {

        var candidatos = tamanos.slice();
        for (var t = tamanos[tamanos.length - 1] - 2; t >= TAMANO_MINIMO; t -= 2) {
            candidatos.push(t);
        }
        for (var i = 0; i < candidatos.length; i++) {
            if (anchoDe(texto, 600, candidatos[i]) <= ancho) {
                return candidatos[i];
            }
        }
        return TAMANO_MINIMO;
    }

    function partirEnDos(texto, tamano, ancho) {

        if (anchoDe(texto, 800, tamano) <= ancho || texto.trim().indexOf(" ") === -1) {
            return [texto];
        }
        var palabras = texto.split(/\s+/).filter(Boolean);
        var mejor = null;
        for (var i = 1; i < palabras.length; i++) {
            var renglones = [palabras.slice(0, i).join(" "), palabras.slice(i).join(" ")];
            var largo = Math.max(anchoDe(renglones[0], 800, tamano), anchoDe(renglones[1], 800, tamano));
            if (mejor === null || largo < mejor.largo) {
                mejor = {largo: largo, renglones: renglones};
            }
        }
        return mejor.renglones;
    }

    function nombreEnRenglones(nombre, ancho) {
        /* Como ImageService.nombre_en_renglones: un renglon con la letra mas grande que
         * entre, sin bajar de MINIMO_NOMBRE_EN_UN_RENGLON; si no, dos renglones. */

        nombre = (nombre || "").trim() || "Sin nombre";
        var i, t, renglones;

        for (i = 0; i < TAMANOS_NOMBRE.length && TAMANOS_NOMBRE[i] >= MINIMO_NOMBRE_EN_UN_RENGLON; i++) {
            if (anchoDe(nombre, 800, TAMANOS_NOMBRE[i]) <= ancho) {
                return {tamano: TAMANOS_NOMBRE[i], renglones: [nombre]};
            }
        }

        var candidatos = TAMANOS_NOMBRE.slice();
        for (t = TAMANOS_NOMBRE[TAMANOS_NOMBRE.length - 1] - 4; t >= TAMANO_MINIMO; t -= 4) {
            candidatos.push(t);
        }
        for (i = 0; i < candidatos.length; i++) {
            renglones = partirEnDos(nombre, candidatos[i], ancho);
            var entran = renglones.every(function (r) { return anchoDe(r, 800, candidatos[i]) <= ancho; });
            if (entran) {
                return {tamano: candidatos[i], renglones: renglones};
            }
        }
        return {tamano: TAMANO_MINIMO, renglones: partirEnDos(nombre, TAMANO_MINIMO, ancho)};
    }

    function partesDeEdadYSexo(subtitulo) {
        /* Las pantallas arman el subtitulo "2 años - Macho" (o solo el sexo); la tarjeta
         * lo escribe con un punto en el medio, y "Desconocido" no lo escribe. */

        return (subtitulo || "").split(" - ").map(function (parte) {
            return parte.trim();
        }).filter(function (parte) {
            return parte && parte !== "Desconocido";
        });
    }

    function medidasDeLaTarjeta(options) {
        /* La caja de la tarjeta y donde va cada cosa, en unidades del lienzo de 1400, con
         * las mismas cuentas que ImageService.medidas_de_la_tarjeta. */

        var logoAncho = Math.round(LOGO_DIBUJO.w * LOGO_ALTO / LOGO_DIBUJO.h);
        var anchoTexto = FRANJA_SEGURA[1] - FRANJA_SEGURA[0] - 2 * PADDING_X - logoAncho - HUECO_TEXTO_LOGO;

        var nombre = nombreEnRenglones(options.nombre, anchoTexto);
        var partes = partesDeEdadYSexo(options.subtitulo);
        var texto = partes.join(SEPARADOR);
        var tamanoLinea = texto ? tamanoQueEntra(texto, 600, anchoTexto, TAMANOS_EDAD_SEXO) : 0;

        var mayuscula = Math.round(MAYUSCULA * nombre.tamano);
        var interlinea = Math.round(nombre.tamano * 1.08);
        var descenso = DESCENSO * nombre.tamano;

        var usado = 0;
        nombre.renglones.forEach(function (r) {
            usado = Math.max(usado, anchoDe(r, 800, nombre.tamano));
        });

        var alto = PADDING_ARRIBA + mayuscula + interlinea * (nombre.renglones.length - 1);
        var baseNombre = PADDING_ARRIBA + mayuscula;
        var baseLinea = null;
        if (texto) {
            var hueco = Math.round(descenso * 0.8) + 18;
            alto += hueco + Math.round(MAYUSCULA * tamanoLinea);
            baseLinea = alto;
            usado = Math.max(usado, anchoDe(texto, 600, tamanoLinea));
        } else {
            alto += Math.round(descenso * 0.5);
        }
        alto += PADDING_ABAJO;

        var ancho = 2 * PADDING_X + usado + HUECO_TEXTO_LOGO + logoAncho;

        return {
            x: Math.floor((CANVAS - ancho) / 2), y: TARJETA_ABAJO - alto, ancho: ancho, alto: alto,
            nombre: nombre, interlinea: interlinea, baseNombre: baseNombre,
            partes: partes, tamanoLinea: tamanoLinea, baseLinea: baseLinea, logoAncho: logoAncho
        };
    }

    function dibujarTarjeta(post, options) {
        /* Ubica la tarjeta en pixeles, contra el ancho real de la preview.
         *
         * Todo se calcula en unidades del lienzo y se pasa a pixeles aca: un font-size
         * en porcentaje se resuelve contra el font-size del PADRE, no contra el ancho, y
         * con un padre de 14px el nombre salia de 1.7px.
         */

        var tarjeta = post.querySelector(".catus-crop-card");
        var escala = post.clientWidth / CANVAS;

        if (!tarjeta || !escala) {
            return;
        }

        function px(valor) {
            return (valor * escala) + "px";
        }

        var m = medidasDeLaTarjeta(options);

        tarjeta.style.left = px(m.x);
        tarjeta.style.top = px(m.y);
        tarjeta.style.width = px(m.ancho);
        tarjeta.style.height = px(m.alto);
        tarjeta.style.borderRadius = px(RADIO);
        tarjeta.style.borderWidth = px(BORDE);

        // las posiciones de adentro van contra el borde de afuera de la tarjeta, como
        // en el server: se les descuenta el borde, que el absolute cuenta desde adentro
        var adentro = BORDE;

        var nombre = tarjeta.querySelector(".catus-crop-card-name");
        nombre.textContent = "";
        nombre.style.fontSize = px(m.nombre.tamano);
        nombre.style.left = px(PADDING_X - adentro);
        nombre.style.top = px(m.baseNombre - baseDesdeArriba(800, m.nombre.tamano) - adentro);
        nombre.style.lineHeight = px(m.interlinea);
        m.nombre.renglones.forEach(function (renglon, i) {
            if (i) {
                nombre.appendChild(document.createElement("br"));
            }
            nombre.appendChild(document.createTextNode(renglon));
        });
        // con line-height igual a la interlinea, el primer renglon baja la mitad de lo que
        // sobra; se corrige para que su base caiga donde la pone el server
        nombre.style.marginTop = px(-(m.interlinea - m.nombre.tamano) / 2);

        var linea = tarjeta.querySelector(".catus-crop-card-line");
        linea.textContent = "";
        if (m.baseLinea === null) {
            linea.style.display = "none";
        } else {
            linea.style.display = "";
            linea.style.fontSize = px(m.tamanoLinea);
            linea.style.left = px(PADDING_X + 2 - adentro);
            linea.style.top = px(m.baseLinea - baseDesdeArriba(600, m.tamanoLinea) - adentro);
            m.partes.forEach(function (parte, i) {
                if (i) {
                    var sep = make("span", "catus-crop-sep", linea);
                    sep.textContent = SEPARADOR;
                }
                linea.appendChild(document.createTextNode(parte));
            });
        }

        var logo = tarjeta.querySelector(".catus-crop-card-logo");
        var img = logo.querySelector("img");
        var escalaLogo = LOGO_ALTO / LOGO_DIBUJO.h;
        logo.style.width = px(m.logoAncho);
        logo.style.height = px(LOGO_ALTO);
        logo.style.right = px(PADDING_X - adentro);
        logo.style.top = px((m.alto - LOGO_ALTO) / 2 - adentro);
        img.style.width = px(LOGO_PNG * escalaLogo);
        img.style.height = px(LOGO_PNG * escalaLogo);
        img.style.left = px(-LOGO_DIBUJO.x * escalaLogo);
        img.style.top = px(-LOGO_DIBUJO.y * escalaLogo);
    }

    function buildPreview(container, options) {
        /* Arma la vista previa del posteo. Devuelve el nodo donde Cropper dibuja la foto. */

        var post = make("div", "catus-crop-post", container);

        // la foto ocupa todo el posteo
        var photo = make("div", "catus-crop-photo", post);
        photo.style.left = "0";
        photo.style.top = "0";
        photo.style.width = "100%";
        photo.style.height = "100%";

        var tarjeta = make("div", "catus-crop-card", post);
        make("div", "catus-crop-card-name", tarjeta);
        make("div", "catus-crop-card-line", tarjeta);
        var logo = make("div", "catus-crop-card-logo", tarjeta);
        var logoImg = make("img", null, logo);
        logoImg.src = options.logoUrl || "/static/logo_2.png";
        logoImg.alt = "";
        logoImg.onerror = function () {
            logo.style.display = "none";
        };

        dibujarTarjeta(post, options);

        // si Open Sans termina de cargar despues, los anchos cambian: se vuelve a medir
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(function () {
                if (post.isConnected) {
                    dibujarTarjeta(post, options);
                }
            });
        }

        return photo;
    }

    function marcoVisible(image) {
        /* Cuanto mide la foto como se la ve, que no siempre es como esta guardada.
         *
         * Cropper corre con checkOrientation: baja el archivo, le resetea el byte de
         * orientacion EXIF y se guarda la rotacion en imageData.rotate (Orientation=6
         * -> 90, 8 -> -90), que aplica por transform. Entonces getData() devuelve el
         * cuadro medido en el marco YA ROTADO (el que ve la persona) mientras que
         * naturalWidth/naturalHeight siguen siendo los del archivo crudo. Dividir por el
         * lado equivocado hacia que una foto vertical de celular (4032x3024 con
         * Orientation=6, el caso mas comun) guardara un recorte que no era el elegido.
         *
         * El marco visible es tambien el que ve el server: optimize() endereza con
         * exif_transpose antes de guardar, asi que las fracciones se aplican sobre la
         * foto derecha. Por lo mismo el espejado (scaleX/scaleY de las orientaciones 2,
         * 4, 5 y 7) no se corrige aca: Cropper ya muestra la foto espejada y
         * exif_transpose la guarda igual, las coordenadas coinciden solas.
         *
         * Ida y vuelta con una 4032x3024 rotada 90 (marco visible 3024x4032) y el cuadro
         * pegado abajo: getData da {x: 0, y: 1008, width: 3024, height: 3024}, que sobre
         * 3024x4032 son las fracciones {0, 0.25, 1, 0.75}; applyFractions las multiplica
         * por los mismos lados y devuelve {0, 1008, 3024, 3024}, el mismo cuadro.
         */

        var rotada = Math.abs(image.rotate || 0) % 180 === 90;

        return {
            width: rotada ? image.naturalHeight : image.naturalWidth,
            height: rotada ? image.naturalWidth : image.naturalHeight
        };
    }

    function toFractions(cropper) {
        /* Pasa el recorte de pixeles de la foto original a fracciones. */

        var data = cropper.getData(true);
        var marco = marcoVisible(cropper.getImageData());

        var width = marco.width;
        var height = marco.height;

        if (!width || !height) {
            return null;
        }

        // el cuadro puede quedar apenas afuera de la foto: lo encerramos adentro
        var x = Math.min(Math.max(data.x, 0), width);
        var y = Math.min(Math.max(data.y, 0), height);
        var w = Math.min(data.width, width - x);
        var h = Math.min(data.height, height - y);

        if (w <= 0 || h <= 0) {
            return null;
        }

        return {x: x / width, y: y / height, w: w / width, h: h / height};
    }

    function applyFractions(cropper, crop) {
        /* Coloca el cuadro donde diga el recorte guardado. */

        var marco = marcoVisible(cropper.getImageData());
        var width = marco.width;
        var height = marco.height;

        if (!width || !height) {
            return;
        }

        cropper.setData({
            x: crop.x * width,
            y: crop.y * height,
            width: crop.w * width,
            height: crop.h * height
        });
    }

    function open(options) {

        if (typeof window.Cropper === "undefined") {
            window.alert("No se pudo cargar el selector de recorte. Refrescá la página e intentá de nuevo.");
            return;
        }

        injectStyles();

        var overlay = make("div", "catus-crop-overlay", document.body);
        var dialog = make("div", "catus-crop-dialog", overlay);

        var title = make("p", "catus-crop-title", dialog);
        title.textContent = "Recortar para Instagram";

        // sin decir de que lado: en el celular el @media de 640px manda la vista previa
        // abajo de la foto, y "a la derecha" mandaba a buscarla donde no estaba
        var help = make("p", "catus-crop-help", dialog);
        help.textContent = "Movés y agrandás el cuadro para elegir qué parte de la foto se publica. "
            + "En la vista previa ves cómo queda el posteo.";

        var body = make("div", "catus-crop-body", dialog);

        var stage = make("div", "catus-crop-stage", body);
        var image = make("img", null, stage);
        image.alt = "";

        var side = make("div", "catus-crop-side", body);
        var sideLabel = make("div", "catus-crop-side-label", side);
        sideLabel.textContent = "Vista previa aproximada";
        var previewNode = buildPreview(side, options);

        var actions = make("div", "catus-crop-actions", dialog);

        var autoButton = make("button", "btn btn-link catus-crop-auto", actions);
        autoButton.type = "button";
        autoButton.textContent = "Usar recorte automático";

        var cancelButton = make("button", "btn btn-secondary", actions);
        cancelButton.type = "button";
        cancelButton.textContent = "Cancelar";

        var saveButton = make("button", "btn btn-primary", actions);
        saveButton.type = "button";
        saveButton.textContent = "Guardar recorte";

        // Cropper tarda en abrir la foto (la baja entera por XHR para leerle el EXIF y
        // recien despues clona la imagen), y hasta que no esta listo no hay recorte para
        // guardar: guardar null significa "recorte automatico", asi que clickear apurado
        // le borraba a la persona el encuadre que ya tenia elegido
        saveButton.disabled = true;

        var cropper = null;

        function close() {
            document.removeEventListener("keydown", onKeyDown);
            if (cropper) {
                cropper.destroy();
            }
            if (overlay.parentNode) {
                overlay.parentNode.removeChild(overlay);
            }
        }

        function onKeyDown(event) {
            if (event.key === "Escape" || event.keyCode === 27) {
                close();
            }
        }

        document.addEventListener("keydown", onKeyDown);

        overlay.addEventListener("mousedown", function (event) {
            if (event.target === overlay) {
                close();
            }
        });

        cancelButton.onclick = close;

        saveButton.onclick = function () {

            if (!cropper) {
                return;
            }

            var crop = toFractions(cropper);
            close();
            if (options.onSave) {
                options.onSave(crop);
            }
        };

        autoButton.onclick = function () {
            close();
            if (options.onSave) {
                options.onSave(null);
            }
        };

        image.onload = function () {
            cropper = new window.Cropper(image, {
                aspectRatio: 1,
                viewMode: 1,
                autoCropArea: 1,
                dragMode: "move",
                background: false,
                preview: previewNode,
                ready: function () {
                    if (options.crop) {
                        applyFractions(cropper, options.crop);
                    }
                    saveButton.disabled = false;
                }
            });
        };

        image.onerror = function () {
            close();
            window.alert("No se pudo cargar la foto para recortar.");
        };

        image.src = options.src;
    }

    window.CatusCrop = {open: open};

})(window, document);
