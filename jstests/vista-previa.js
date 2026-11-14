/*
 * Dónde dibuja el server la tarjeta del posteo, y dónde la muestra la vista previa.
 *
 * Lo usan crop.spec.js (el selector suelto, como en tools/generarimagen.html) y
 * crop-formset.spec.js (el formset de animal/edit.html). No es un spec: playwright sólo
 * levanta los *.spec.js.
 */

/*
 * El oráculo: lo que hace ImageService.medidas_de_la_tarjeta (catus/services/images.py)
 * en el lienzo de 1400 del posteo. Sale de leer el server, no el widget:
 *
 *   - la foto ocupa todo el lienzo y la tarjeta termina en y=1310 (TARJETA_ABAJO);
 *   - va centrada: (1400 - ancho) // 2;
 *   - nunca sale de la franja que muestra la grilla del perfil, x entre 190 y 1210
 *     (FRANJA_SEGURA): achica el nombre o lo pasa a dos renglones;
 *   - el nombre y el renglón de edad y sexo van adentro.
 *
 * Las posiciones del nombre y la edad eran del diseño anterior: las pantallas las siguen
 * mandando, pero no mueven la tarjeta. Por eso las cuatro combinaciones esperan lo mismo.
 */
const ABAJO = "Izquierda (abajo)";
const ARRIBA = "Izquierda (arriba)";

const COMBINACIONES = [
    {nombre: ARRIBA, edadSexo: ARRIBA, que: "lo automático: todo arriba"},
    {nombre: ARRIBA, edadSexo: ABAJO, que: "nombre arriba y edad abajo"},
    {nombre: ABAJO, edadSexo: ARRIBA, que: "nombre abajo y edad arriba"},
    {nombre: ABAJO, edadSexo: ABAJO, que: "todo abajo"},
];

// en unidades del lienzo de 1400: en una vista previa de 240 px un pixel son casi 6
const TOLERANCIA_LIENZO = 6;

function dondeDibujaElServer() {
    /* No depende de las posiciones: la tarjeta va siempre en el mismo lugar. */

    return {abajo: 1310, centro: 700, franja: [190, 1210]};
}

function medirVistaPrevia(page) {
    /* Dónde quedaron la tarjeta, el nombre y el renglón en la vista previa, en unidades
     * del lienzo.
     *
     * Se mide la caja que se ve, no el style, contra el alto del .catus-crop-post, que
     * es lo que hay que comparar con el server. */

    return page.evaluate(() => {

        const post = document.querySelector(".catus-crop-post");
        const caja = post.getBoundingClientRect();
        const escala = 1400 / post.clientWidth;

        function enLienzo(selector) {
            const nodo = document.querySelector(".catus-crop-post " + selector);
            if (!nodo || nodo.style.display === "none") {
                return null;
            }
            const r = nodo.getBoundingClientRect();
            return {
                izquierda: (r.left - caja.left - post.clientLeft) * escala,
                derecha: (r.right - caja.left - post.clientLeft) * escala,
                arriba: (r.top - caja.top - post.clientTop) * escala,
                abajo: (r.bottom - caja.top - post.clientTop) * escala,
            };
        }

        return {
            tarjeta: enLienzo(".catus-crop-card"),
            nombre: enLienzo(".catus-crop-card-name"),
            renglon: enLienzo(".catus-crop-card-line"),
        };
    });
}

function compararConElServer(expect, medido, esperado, contexto) {
    /* Con expect.soft: si la vista previa se corre, el test lista TODO lo que no
     * coincide en vez de cortar en lo primero. */

    expect(medido.tarjeta, `${contexto}: no hay tarjeta`).not.toBeNull();
    expect(medido.nombre, `${contexto}: no hay nombre en la tarjeta`).not.toBeNull();

    const {tarjeta} = medido;
    const centro = (tarjeta.izquierda + tarjeta.derecha) / 2;

    expect.soft(Math.abs(tarjeta.abajo - esperado.abajo),
        `${contexto}: la tarjeta termina en ${tarjeta.abajo} y el server la termina en ${esperado.abajo}`)
        .toBeLessThanOrEqual(TOLERANCIA_LIENZO);
    expect.soft(Math.abs(centro - esperado.centro),
        `${contexto}: la tarjeta está centrada en ${centro} y el server en ${esperado.centro}`)
        .toBeLessThanOrEqual(TOLERANCIA_LIENZO);
    expect.soft(tarjeta.izquierda, `${contexto}: la tarjeta sale de la franja por la izquierda`)
        .toBeGreaterThanOrEqual(esperado.franja[0] - TOLERANCIA_LIENZO);
    expect.soft(tarjeta.derecha, `${contexto}: la tarjeta sale de la franja por la derecha`)
        .toBeLessThanOrEqual(esperado.franja[1] + TOLERANCIA_LIENZO);

    for (const [que, caja] of [["el nombre", medido.nombre], ["el renglón de edad y sexo", medido.renglon]]) {
        if (!caja) {
            continue;
        }
        expect.soft(caja.izquierda, `${contexto}: ${que} sale de la tarjeta`).toBeGreaterThanOrEqual(tarjeta.izquierda);
        expect.soft(caja.derecha, `${contexto}: ${que} sale de la tarjeta`).toBeLessThanOrEqual(tarjeta.derecha);
        expect.soft(caja.arriba, `${contexto}: ${que} sale de la tarjeta`).toBeGreaterThanOrEqual(tarjeta.arriba);
        expect.soft(caja.abajo, `${contexto}: ${que} sale de la tarjeta`).toBeLessThanOrEqual(tarjeta.abajo);
    }
}

module.exports = {ABAJO, ARRIBA, COMBINACIONES, dondeDibujaElServer, medirVistaPrevia, compararConElServer};
