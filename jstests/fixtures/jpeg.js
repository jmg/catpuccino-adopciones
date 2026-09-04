/*
 * Arma fotos JPEG de verdad en el navegador, con su cabecera EXIF, para no tener que
 * versionar binarios ni depender de Pillow para correr los tests.
 *
 * Hace falta EXIF real porque el bug que estos tests cuidan sólo aparece con una foto
 * rotada: Cropper le pone image-orientation:0deg al clon y aplica la rotación él mismo,
 * asi que getData() queda en el marco que ve la persona mientras naturalWidth/Height
 * siguen siendo los del archivo crudo.
 */
window.CatusFixtures = (function () {
    "use strict";

    function dibujar(width, height) {
        /* Bandas de colores distintas arriba/abajo e izquierda/derecha.
         *
         * Que no sea un color plano importa: con una imagen uniforme un recorte
         * equivocado se ve igual que uno correcto, y ademas el JPEG queda degenerado.
         */

        var canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;

        var ctx = canvas.getContext("2d");

        var colores = ["#c0392b", "#27ae60", "#2980b9", "#f1c40f"];
        var mitadX = Math.floor(width / 2);
        var mitadY = Math.floor(height / 2);

        ctx.fillStyle = colores[0];
        ctx.fillRect(0, 0, mitadX, mitadY);
        ctx.fillStyle = colores[1];
        ctx.fillRect(mitadX, 0, width - mitadX, mitadY);
        ctx.fillStyle = colores[2];
        ctx.fillRect(0, mitadY, mitadX, height - mitadY);
        ctx.fillStyle = colores[3];
        ctx.fillRect(mitadX, mitadY, width - mitadX, height - mitadY);

        // una marca en el borde de arriba, para poder mirar a ojo una captura
        ctx.fillStyle = "#000";
        ctx.fillRect(0, 0, width, Math.max(2, Math.round(height * 0.02)));

        return canvas;
    }

    function base64ABytes(base64) {

        var binario = atob(base64);
        var bytes = new Uint8Array(binario.length);

        for (var i = 0; i < binario.length; i++) {
            bytes[i] = binario.charCodeAt(i);
        }

        return bytes;
    }

    function bytesABase64(bytes) {

        var partes = [];

        // de a pedazos: pasarle 4 MB de una a String.fromCharCode revienta el stack
        for (var i = 0; i < bytes.length; i += 8192) {
            partes.push(String.fromCharCode.apply(null, bytes.subarray(i, i + 8192)));
        }

        return btoa(partes.join(""));
    }

    function segmentoExif(orientacion) {
        /* APP1 mínimo con un solo tag: Orientation.
         *
         *   FFE1 0022                      marcador y largo (2 + 6 + 26)
         *   "Exif\0\0"                     6 bytes
         *   "II" 2A00 08000000             cabecera TIFF little endian, IFD0 en el byte 8
         *   0100                           una sola entrada
         *   0112 0300 01000000 XX00 0000   tag Orientation, tipo SHORT, valor
         *   00000000                       no hay IFD siguiente
         */

        return new Uint8Array([
            0xFF, 0xE1, 0x00, 0x22,
            0x45, 0x78, 0x69, 0x66, 0x00, 0x00,
            0x49, 0x49, 0x2A, 0x00, 0x08, 0x00, 0x00, 0x00,
            0x01, 0x00,
            0x12, 0x01, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00, orientacion & 0xFF, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
        ]);
    }

    function conOrientacion(bytes, orientacion) {
        /* Mete el APP1 justo después del SOI, que es donde va segun la especificación. */

        var exif = segmentoExif(orientacion);
        var salida = new Uint8Array(bytes.length + exif.length);

        salida.set(bytes.subarray(0, 2), 0);          // FFD8
        salida.set(exif, 2);
        salida.set(bytes.subarray(2), 2 + exif.length);

        return salida;
    }

    function foto(width, height, orientacion) {
        /* Devuelve un data: URL de una foto de width x height, con EXIF si se pide.
         *
         * Va como data: y no como archivo servido a propósito: Cropper lee el base64
         * directo, sin XHR, asi que el test no depende de CORS ni de la red.
         */

        var base64 = dibujar(width, height).toDataURL("image/jpeg", 0.9).split(",")[1];

        if (!orientacion || orientacion === 1) {
            return "data:image/jpeg;base64," + base64;
        }

        var bytes = conOrientacion(base64ABytes(base64), orientacion);

        return "data:image/jpeg;base64," + bytesABase64(bytes);
    }

    return {foto: foto};
})();
