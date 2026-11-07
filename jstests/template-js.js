/*
 * El JS de catus/templates/animal/edit.html, recortado del template DE VERDAD, no de una
 * copia. Lo usan crop-formset.spec.js (el selector de recorte del formset de fotos) y
 * guardar.spec.js (el botón "Guardar Cambios"), que se lo sirven a su harness en la URL
 * que él pide con <script src>.
 *
 * Antes fixtures/harness-formset.html tenía pegado el bloque <script> de edit.html. Se
 * revirtió a mano el arreglo de updateRemoveAdded en el template y los 116 tests siguieron
 * en verde: estaban probando el copy/paste, que nadie había revertido. Ahora el bloque se
 * recorta del archivo.
 *
 * Va del lado de los tests y no en server.js porque el recorte necesita resolver la
 * sintaxis de Django que el template tiene adentro del JS, y qué se sustituye es parte de
 * lo que el test afirma (ver RESUELTO_POR_DJANGO). Si algún día se muda al server, los
 * harness no se enteran: siguen pidiendo la misma URL.
 */
const fs = require("fs");
const path = require("path");

const TEMPLATE = path.join(__dirname, "..", "catus", "templates", "animal", "edit.html");
const RUTA_JS = "/template-js/animal-edit.js";

/*
 * Toda la sintaxis de Django que hay hoy adentro de ese <script>, con el valor fijo que la
 * reemplaza. Es una sola expresión, y es el token que el template mete en el POST de
 * /animal/validatename/, que en los harness no se llama nunca.
 *
 * Si mañana aparece otra, el extractor corta con un error en vez de servir JS mal armado:
 * un `{{ ... }}` suelto es un SyntaxError que dejaría la página sin enganchar nada y los
 * tests en rojo sin decir por qué.
 */
const RESUELTO_POR_DJANGO = {
    "{{ csrf_token }}": "csrf-de-prueba",
};

function jsDelTemplate() {

    const html = fs.readFileSync(TEMPLATE, "utf8");

    // el único <script> sin atributos del template; los demás son <script src="...">
    const bloques = html.match(/<script>[\s\S]*?<\/script>/g) || [];

    if (bloques.length !== 1) {
        throw new Error("Se esperaba UN solo <script> inline en " + TEMPLATE + " y hay "
            + bloques.length + ". Si el template se partió en varios bloques, hay que decidir"
            + " acá cuál es el que se prueba.");
    }

    let js = bloques[0].replace(/^<script>/, "").replace(/<\/script>$/, "");

    Object.keys(RESUELTO_POR_DJANGO).forEach(function (expresion) {
        js = js.split(expresion).join(RESUELTO_POR_DJANGO[expresion]);
    });

    const sobrante = js.match(/\{%[\s\S]{0,80}?%\}|\{\{[\s\S]{0,80}?\}\}/);

    if (sobrante) {
        throw new Error("Quedó sintaxis de Django sin resolver en el JS de animal/edit.html: "
            + sobrante[0] + ". Agregala a RESUELTO_POR_DJANGO en jstests/template-js.js y"
            + " anotala en jstests/README.md, así se sabe qué se está sustituyendo.");
    }

    return js;
}

module.exports = {TEMPLATE, RUTA_JS, RESUELTO_POR_DJANGO, jsDelTemplate};
