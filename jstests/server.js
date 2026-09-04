/*
 * Servidor mínimo para los tests: sirve los estáticos con las MISMAS rutas que el sitio
 * (/static/js/crop-widget.js, /static/vendor/cropper/...), así el harness carga los
 * archivos de verdad y no una copia que se puede desincronizar.
 *
 * Sin dependencias a propósito: sólo http y fs de node.
 */
const http = require("http");
const fs = require("fs");
const path = require("path");

const RAIZ = path.join(__dirname, "..");
const ESTATICOS = path.join(RAIZ, "catus", "static");
const FIXTURES = path.join(__dirname, "fixtures");

const TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
};

function resolver(url) {

    const limpia = decodeURIComponent(url.split("?")[0]);

    // /static/... sale de catus/static, igual que en producción
    if (limpia.startsWith("/static/")) {
        return path.join(ESTATICOS, limpia.slice("/static/".length));
    }

    return path.join(FIXTURES, limpia === "/" ? "harness.html" : limpia.slice(1));
}

const server = http.createServer(function (req, res) {

    const archivo = resolver(req.url);

    // que un test no pueda leer fuera de las dos carpetas que servimos
    if (!archivo.startsWith(ESTATICOS) && !archivo.startsWith(FIXTURES)) {
        res.writeHead(403).end("nope");
        return;
    }

    fs.readFile(archivo, function (error, contenido) {

        if (error) {
            res.writeHead(404, {"Content-Type": "text/plain"}).end("no existe: " + req.url);
            return;
        }

        res.writeHead(200, {
            "Content-Type": TIPOS[path.extname(archivo)] || "application/octet-stream",
            "Cache-Control": "no-store",
        });
        res.end(contenido);
    });
});

server.listen(Number(process.env.PORT) || 4173, function () {
    console.log("harness en http://127.0.0.1:" + server.address().port + "/");
});
