/*
 * Selector de recorte cuadrado para Instagram.
 *
 * Abre la foto con un cuadro 1:1 que se arrastra y se agranda, y al lado muestra una
 * vista previa aproximada de como va a quedar el posteo (marco blanco, logo y la barra
 * con el nombre), para poder elegir sin que el animal quede cortado ni tapado.
 *
 * El recorte se guarda en fracciones (0 a 1) de la foto original, asi que no depende
 * del tamano en el que se la muestre.
 *
 *   CatusCrop.open({
 *       src: "/gallery/foto.jpeg",
 *       crop: {x: 0, y: 0.1, w: 1, h: 0.42},   // o null si todavia no tiene
 *       nombre: "Willy",
 *       subtitulo: "2 anios - Macho",
 *       posicionNombre: "Izquierda (abajo)",
 *       onSave: function (crop) { ... }        // crop es null si eligio automatico
 *   });
 */
(function (window, document) {
    "use strict";

    // el posteo final es un lienzo de 1400 con la foto de 1200 pegada en (100, 100)
    var CANVAS = 1400;
    var PHOTO = 1200;
    var INSET = 100;
    var LOGO_CIRCLE = 330;
    var LOGO = 250;

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
            ".catus-crop-dialog{background:#fff;border-radius:10px;max-width:900px;width:100%;",
            "max-height:95vh;overflow:auto;padding:18px;box-shadow:0 10px 40px rgba(0,0,0,.4);}",
            ".catus-crop-title{font-weight:700;margin:0 0 4px;font-size:18px;color:#333;}",
            ".catus-crop-help{margin:0 0 14px;font-size:13px;color:#777;}",
            ".catus-crop-body{display:flex;gap:18px;flex-wrap:wrap;}",
            ".catus-crop-stage{flex:1 1 320px;min-width:260px;}",
            ".catus-crop-stage img{max-width:100%;display:block;}",
            ".catus-crop-side{flex:0 0 240px;}",
            ".catus-crop-side-label{font-size:12px;color:#777;margin-bottom:6px;text-align:center;}",
            ".catus-crop-post{position:relative;width:100%;padding-top:100%;background:#fff;",
            "border:1px solid #e2e2e2;border-radius:4px;overflow:hidden;}",
            ".catus-crop-photo{position:absolute;overflow:hidden;background:#f2f2f2;}",
            ".catus-crop-namebar{position:absolute;left:0;background:rgb(147,186,183);color:#fff;",
            "display:flex;align-items:center;font-family:Impact,'Arial Narrow',sans-serif;",
            "white-space:nowrap;overflow:hidden;}",
            ".catus-crop-subtitle{position:absolute;color:#fff;white-space:nowrap;",
            "font-family:Montserrat,Arial,sans-serif;text-shadow:0 1px 2px rgba(0,0,0,.45);}",
            ".catus-crop-logo{position:absolute;border-radius:50%;background:#fff;",
            "display:flex;align-items:center;justify-content:center;}",
            ".catus-crop-logo img{width:76%;height:76%;object-fit:contain;}",
            ".catus-crop-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;",
            "margin-top:16px;padding-top:14px;border-top:1px solid #eee;}",
            ".catus-crop-actions .btn{min-width:120px;}",
            ".catus-crop-auto{margin-right:auto;}",
            "@media (max-width:640px){.catus-crop-side{flex:1 1 100%;}",
            ".catus-crop-actions .btn{flex:1 1 100%;min-width:0;}}"
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

    function buildPreview(container, options) {
        /* Arma la vista previa del posteo. Devuelve el nodo donde Cropper dibuja la foto. */

        var post = make("div", "catus-crop-post", container);

        var photo = make("div", "catus-crop-photo", post);
        photo.style.left = percent(INSET);
        photo.style.top = percent(INSET);
        photo.style.width = percent(PHOTO);
        photo.style.height = percent(PHOTO);

        var abajo = (options.posicionNombre || "").indexOf("abajo") !== -1;

        if (options.nombre) {
            var bar = make("div", "catus-crop-namebar", post);
            bar.textContent = options.nombre;
            bar.style.top = percent(abajo ? 1005 : 100);
            bar.style.height = percent(175);
            bar.style.paddingLeft = percent(105);
            bar.style.paddingRight = percent(25);
            bar.style.fontSize = percent(150);
        }

        if (options.subtitulo) {
            var subtitle = make("div", "catus-crop-subtitle", post);
            subtitle.textContent = options.subtitulo;
            subtitle.style.top = percent(abajo ? 1205 : 305);
            subtitle.style.left = percent(140);
            subtitle.style.fontSize = percent(60);
        }

        var logo = make("div", "catus-crop-logo", post);
        logo.style.width = percent(LOGO_CIRCLE);
        logo.style.height = percent(LOGO_CIRCLE);
        logo.style.right = "0";
        logo.style.bottom = "0";

        var logoImg = make("img", null, logo);
        logoImg.src = options.logoUrl || "/static/logo_2.png";
        logoImg.alt = "";
        logoImg.onerror = function () {
            logo.style.display = "none";
        };

        return photo;
    }

    function toFractions(cropper) {
        /* Pasa el recorte de pixeles de la foto original a fracciones. */

        var data = cropper.getData(true);
        var image = cropper.getImageData();

        var width = image.naturalWidth;
        var height = image.naturalHeight;

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

        var image = cropper.getImageData();
        var width = image.naturalWidth;
        var height = image.naturalHeight;

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

        var help = make("p", "catus-crop-help", dialog);
        help.textContent = "Movés y agrandás el cuadro para elegir qué parte de la foto se publica. "
            + "A la derecha ves cómo queda el posteo.";

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
            var crop = cropper ? toFractions(cropper) : null;
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
