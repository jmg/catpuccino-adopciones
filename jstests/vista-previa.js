/*
 * Dónde dibuja el server el nombre y la edad, y dónde los muestra la vista previa.
 *
 * Lo usan crop.spec.js (el selector suelto, como en tools/generarimagen.html) y
 * crop-formset.spec.js (el formset de animal/edit.html). No es un spec: playwright sólo
 * levanta los *.spec.js.
 */

/*
 * El oráculo: lo que hace ImageService.add_nombre_y_edad (catus/services/images.py) en
 * el lienzo de 1400 del posteo. Sale de leer el server, no el widget:
 *
 *   - la barra del nombre termina en position_text_name_y_end + 20: 1180 con
 *     "Izquierda (abajo)", 280 con cualquier otra cosa;
 *   - con "Izquierda (arriba)" arranca en 100, el borde de la foto. Con "abajo" arranca
 *     a la altura del texto, que con Impact 150 queda entre 996 y 1011 según las letras
 *     del nombre (medido con Pillow: "Juggy" 996, "Willy" 999, "Pancho" 1011);
 *   - el renglón de edad y sexo va en y=1205 con posicion_edad_sexo "Izquierda (abajo)"
 *     y en y=305 con cualquier otra cosa. No mira posicion_nombre para nada.
 *
 * Las dos posiciones se eligen por separado en los selects de /tools/generarimagen/, así
 * que las cuatro combinaciones salen de la pantalla.
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
const TOLERANCIA_LIENZO = 2;

function dondeDibujaElServer(posicionNombre, posicionEdadSexo) {

    return {
        barra: posicionNombre === ABAJO
            ? {arribaEntre: [996, 1011], abajo: 1180}
            : {arribaEntre: [100, 100], abajo: 280},
        renglon: posicionEdadSexo === ABAJO ? 1205 : 305,
    };
}

function medirVistaPrevia(page) {
    /* Dónde quedaron la barra y el renglón en la vista previa, en unidades del lienzo.
     *
     * Se mide la caja que se ve, no el style: un top en % se resuelve contra el alto del
     * .catus-crop-post, y es eso lo que hay que comparar con el server. */

    return page.evaluate(() => {

        const post = document.querySelector(".catus-crop-post");
        const caja = post.getBoundingClientRect();
        const escala = 1400 / post.clientWidth;

        function enLienzo(selector) {
            const nodo = document.querySelector(".catus-crop-post " + selector);
            if (!nodo) {
                return null;
            }
            const r = nodo.getBoundingClientRect();
            return {
                arriba: (r.top - caja.top - post.clientTop) * escala,
                abajo: (r.bottom - caja.top - post.clientTop) * escala,
            };
        }

        return {barra: enLienzo(".catus-crop-namebar"), renglon: enLienzo(".catus-crop-subtitle")};
    });
}

function compararConElServer(expect, medido, esperado, contexto) {
    /* Con expect.soft: si la vista previa se corre, el test lista TODO lo que no
     * coincide (la barra y el renglón) en vez de cortar en lo primero. */

    const [desde, hasta] = esperado.barra.arribaEntre;

    expect(medido.barra, `${contexto}: no hay barra del nombre`).not.toBeNull();
    expect(medido.renglon, `${contexto}: no hay renglón de edad y sexo`).not.toBeNull();

    expect.soft(Math.abs(medido.renglon.arriba - esperado.renglon),
        `${contexto}: la edad va en ${medido.renglon.arriba} y el server la escribe en ${esperado.renglon}`)
        .toBeLessThanOrEqual(TOLERANCIA_LIENZO);

    expect.soft(medido.barra.arriba,
        `${contexto}: la barra empieza en ${medido.barra.arriba} y el server entre ${desde} y ${hasta}`)
        .toBeGreaterThanOrEqual(desde - TOLERANCIA_LIENZO);
    expect.soft(medido.barra.arriba,
        `${contexto}: la barra empieza en ${medido.barra.arriba} y el server entre ${desde} y ${hasta}`)
        .toBeLessThanOrEqual(hasta + TOLERANCIA_LIENZO);
    expect.soft(Math.abs(medido.barra.abajo - esperado.barra.abajo),
        `${contexto}: la barra termina en ${medido.barra.abajo} y el server en ${esperado.barra.abajo}`)
        .toBeLessThanOrEqual(TOLERANCIA_LIENZO);
}

module.exports = {ABAJO, ARRIBA, COMBINACIONES, dondeDibujaElServer, medirVistaPrevia, compararConElServer};
