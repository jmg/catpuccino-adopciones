/*
 * Tests de navegador del selector de recorte DENTRO DEL FORMSET DE FOTOS
 * (catus/templates/animal/edit.html, funciones field / setupCropButton / setupCropButtons).
 *
 * crop.spec.js prueba el selector en sí, con un recorte solo, como en
 * tools/generarimagen.html. Acá se prueba el otro lugar donde se usa, que es el frágil:
 * el formset de subida de fotos, donde hay N filas, los índices se arman a mano
 * concatenando strings y "Agregar Foto" agrega filas después de que la página cargó.
 *
 * Lo que se rompe sólo acá:
 *
 *   - una fila escribe el recorte en los inputs de otra (el clásico de las closures
 *     sobre el índice del for),
 *   - la fila que se agrega después no queda enganchada y no tiene botón,
 *   - cambiar la foto de una fila borra el recorte de todas,
 *   - borrar una fila deja sus hidden del recorte sueltos en el <form>.
 *
 * En los tres primeros el animal se guarda igual, sin error: el rescatista se entera
 * cuando el posteo sale de Instagram con la parte equivocada de la foto. El cuarto es
 * al revés: el animal no se guarda más, y el error habla de una foto que ya no está.
 *
 *   cd jstests && npx playwright test crop-formset.spec.js
 */
const {test, expect} = require("@playwright/test");
const fs = require("fs");
const path = require("path");

/*
 * El JS que se prueba sale del template DE VERDAD, no de una copia.
 *
 * Antes fixtures/harness-formset.html tenía pegado el bloque <script> de edit.html. Se
 * revirtió a mano el arreglo de updateRemoveAdded en el template y los 116 tests siguieron
 * en verde: estaban probando el copy/paste, que nadie había revertido. Ahora el bloque se
 * recorta del archivo y se le sirve al harness en la URL que él pide con <script src>.
 *
 * Va acá y no en server.js porque el recorte necesita resolver la sintaxis de Django que
 * el template tiene adentro del JS, y qué se sustituye es parte de lo que el test afirma
 * (ver RESUELTO_POR_DJANGO). Si algún día se muda al server, el harness no se entera: sigue
 * pidiendo la misma URL.
 */
const TEMPLATE = path.join(__dirname, "..", "catus", "templates", "animal", "edit.html");
const RUTA_JS = "/template-js/animal-edit.js";

/*
 * Toda la sintaxis de Django que hay hoy adentro de ese <script>, con el valor fijo que la
 * reemplaza. Es una sola expresión, y es el token que el template mete en el POST de
 * /animal/validatename/, que en el harness no se llama nunca.
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
            + " acá cuál es el del formset.");
    }

    let js = bloques[0].replace(/^<script>/, "").replace(/<\/script>$/, "");

    Object.keys(RESUELTO_POR_DJANGO).forEach(function (expresion) {
        js = js.split(expresion).join(RESUELTO_POR_DJANGO[expresion]);
    });

    const sobrante = js.match(/\{%[\s\S]{0,80}?%\}|\{\{[\s\S]{0,80}?\}\}/);

    if (sobrante) {
        throw new Error("Quedó sintaxis de Django sin resolver en el JS de animal/edit.html: "
            + sobrante[0] + ". Agregala a RESUELTO_POR_DJANGO en este archivo y anotala en"
            + " jstests/README.md, así se sabe qué se está sustituyendo.");
    }

    return js;
}

const JS_DEL_TEMPLATE = jsDelTemplate();

// las fotos del harness son 2000x1000; el recorte se guarda en fracciones de esos lados
const FOTO = {width: 2000, height: 1000};

// lo que el server escribió en las filas 0 y 2 (un cuadrado de 800x800 sobre 2000x1000).
// Son los centinelas: si alguna operación sobre OTRA fila los mueve, el test lo agarra.
const CENTINELA = {
    0: {x: "0.05", y: "0.1", w: "0.4", h: "0.8"},
    2: {x: "0.55", y: "0.05", w: "0.4", h: "0.8"},
};

const SIN_RECORTE = {x: "", y: "", w: "", h: ""};

const TOLERANCIA = 0.01;

function grupo(page, fila) {
    /* El .form-group de esa fila: es donde setupCropButton cuelga el botón y el cartel. */
    return page.locator(`.form-group:has(#id_animalimage_set-${fila}-image)`);
}

function boton(page, fila) {
    return grupo(page, fila).locator("button");
}

function cartel(page, fila) {
    return grupo(page, fila).locator("small.form-text");
}

function crudo(page, fila) {
    return page.evaluate((i) => window.harness.crudo(i), fila);
}

function leer(page, fila) {
    return page.evaluate((i) => window.harness.leer(i), fila);
}

async function ponerFoto(page, fila, nombre) {
    /* Carga una foto de verdad en el input de esa fila, como cuando la persona la elige.
     *
     * La imagen la arma CatusFixtures en el navegador (canvas + JPEG) y se la pasa a
     * setInputFiles como buffer: así el input queda con un File posta, getSource() pasa
     * por createObjectURL y el evento change sale del navegador, no de un dispatchEvent
     * a mano que no probaría el mismo camino.
     */

    const dataUrl = await page.evaluate(
        ([w, h]) => window.CatusFixtures.foto(w, h, 1), [FOTO.width, FOTO.height]);

    await page.locator(`#id_animalimage_set-${fila}-image`).setInputFiles({
        name: nombre || `foto-${fila}.jpg`,
        mimeType: "image/jpeg",
        buffer: Buffer.from(dataUrl.split(",")[1], "base64"),
    });
}

async function abrirSelector(page, fila) {
    /* Abre el selector de esa fila y espera a que Cropper termine de acomodarse. */

    await boton(page, fila).click();
    await expect(page.locator(".catus-crop-overlay")).toBeVisible();

    // el botón se habilita en el callback ready de Cropper: es la señal de que ya hay recorte
    await expect(page.getByRole("button", {name: "Guardar recorte"})).toBeEnabled({timeout: 15000});
    await expect(page.locator(".cropper-crop-box")).toBeVisible();
}

async function guardar(page, fila) {

    await page.getByRole("button", {name: "Guardar recorte"}).click();
    await expect(page.locator(".catus-crop-overlay")).toHaveCount(0);

    return leer(page, fila);
}

function esCuadradoEnPixeles(crop) {
    /* El recorte va en fracciones de cada lado, así que "cuadrado" no es w == h:
     * es w * ancho == h * alto. Si no da cuadrado, el posteo sale estirado. */

    return Math.abs(crop.w * FOTO.width - crop.h * FOTO.height);
}

test.beforeEach(async ({page}) => {

    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;

    /* El <script src> del harness pide esto y nadie más lo sirve: si esta ruta no
     * estuviera, la página se queda sin JS y los tests se caen en el beforeEach, que es
     * exactamente lo que tiene que pasar. */
    await page.route("**" + RUTA_JS, (route) => route.fulfill({
        status: 200,
        contentType: "text/javascript; charset=utf-8",
        body: JS_DEL_TEMPLATE,
    }));

    await page.goto("/harness-formset.html");
    await page.waitForFunction(() => window.CatusCrop && window.Cropper && window.jQuery && window.harness.crudo);

    // el harness arranca con tres filas: la 0 y la 2 con recorte guardado, la 1 sin
    await expect(boton(page, 0)).toBeVisible();
    await expect(boton(page, 1)).toBeVisible();
    await expect(boton(page, 2)).toBeVisible();
});

test.afterEach(async ({page}) => {
    // un TypeError adentro de un handler deja media pantalla sin enganchar y no se nota
    expect(page.errores, "la página no tiene que tirar errores de JS").toEqual([]);
});


test.describe("cada fila escribe en la suya", () => {

    test("elegir el recorte de la fila 1 no toca el de la 0 ni el de la 2", async ({page}) => {
        /* El clásico de este patrón: los cuatro inputs se buscan por id armando el string
         * '#id_animalimage_set-' + index + '-crop_x', y si el índice se toma de la
         * variable del for en vez del parámetro de la función, TODAS las filas terminan
         * escribiendo en la última (o en la primera, según cómo se rompa).
         *
         * En pantalla no se ve nada raro: el animal se guarda, y recién en Instagram
         * aparece que la foto 2 salió con el encuadre que se eligió para la 3. */

        expect(await crudo(page, 0)).toEqual(CENTINELA[0]);
        expect(await crudo(page, 2)).toEqual(CENTINELA[2]);
        expect(await leer(page, 1), "la fila 1 tiene que arrancar sin recorte").toBeNull();

        await abrirSelector(page, 1);
        const crop = await guardar(page, 1);

        expect(crop, "la fila 1 tiene que quedar con el recorte que se eligió").not.toBeNull();
        expect(esCuadradoEnPixeles(crop)).toBeLessThan(FOTO.width * TOLERANCIA);

        expect(await crudo(page, 0), "la fila 0 quedó pisada").toEqual(CENTINELA[0]);
        expect(await crudo(page, 2), "la fila 2 quedó pisada").toEqual(CENTINELA[2]);
    });

    test("cambiar la foto de una fila borra el recorte de esa fila y nada más", async ({page}) => {
        /* El recorte son fracciones de UNA foto: si se cambia la foto, el encuadre viejo
         * apunta a otra parte. Por eso el change del input hace setCrop(null).
         *
         * Lo que se controla acá es el "y nada más": el mismo handler, mal escrito,
         * limpia los cuatro inputs de todas las filas y la persona pierde los encuadres
         * que ya había elegido para las otras fotos sólo por cambiar una. */

        await ponerFoto(page, 0);

        expect(await leer(page, 0), "cambiar la foto tiene que borrar el recorte viejo").toBeNull();
        expect(await crudo(page, 0)).toEqual(SIN_RECORTE);

        expect(await crudo(page, 2), "el recorte de la fila 2 no se toca").toEqual(CENTINELA[2]);
        expect(await leer(page, 1)).toBeNull();

        // y la fila 0 vuelve a ofrecer elegir, porque ya no tiene recorte
        await expect(boton(page, 0)).toHaveText(/Elegir recorte para Instagram/);
    });
});


test.describe("las filas que se agregan después de cargar la página", () => {

    test("la foto agregada con 'Agregar Foto' también tiene botón de recorte", async ({page}) => {
        /* setupCropButtons() recorre de 0 a TOTAL_FORMS y engancha lo que falte. Si sólo
         * corriera al cargar, las filas nuevas quedarían sin botón: con extra=0 en el
         * formset, un animal nuevo arranca con CERO filas y todas las fotos entran por
         * este camino, así que nadie podría elegir recorte al cargar un animal.
         *
         * Lo sostiene el orden de los dos handlers de #add_more: primero el que agrega la
         * fila y sube TOTAL_FORMS, y recién después setupCropButtons. Si alguien mueve
         * uno, o si el primero tira una excepción (jQuery corta la cadena y no llama al
         * resto), este test se pone en rojo. */

        expect(await page.evaluate(() => window.harness.total())).toBe(3);

        await page.locator("#add_more").click();

        expect(await page.evaluate(() => window.harness.total()), "TOTAL_FORMS").toBe(4);
        await expect(page.locator("#id_animalimage_set-3-image")).toHaveCount(1);

        // todavía sin foto: el botón existe pero está escondido, no tendría qué recortar
        await expect(boton(page, 3)).toHaveCount(1);
        await expect(boton(page, 3)).toBeHidden();

        await ponerFoto(page, 3);
        await expect(boton(page, 3)).toBeVisible();

        await abrirSelector(page, 3);
        const crop = await guardar(page, 3);

        expect(crop, "la fila nueva tiene que guardar su propio recorte").not.toBeNull();
        expect(esCuadradoEnPixeles(crop)).toBeLessThan(FOTO.width * TOLERANCIA);

        // y escribe en la suya, no en las que ya estaban
        expect(await crudo(page, 0)).toEqual(CENTINELA[0]);
        expect(await leer(page, 1)).toBeNull();
        expect(await crudo(page, 2)).toEqual(CENTINELA[2]);
    });

    test("dos filas nuevas seguidas quedan con un recorte cada una", async ({page}) => {
        /* Los índices se arman concatenando el valor de TOTAL_FORMS, que es un string.
         * Si en vez de parseInt+1 se sumara el string, la segunda fila se llamaría "31"
         * y las dos escribirían en cualquier lado. Además setupCropButton se saltea las
         * filas ya enganchadas por data('crop-ready'): si esa marca no funcionara, la
         * fila vieja se llenaría de botones repetidos. */

        await page.locator("#add_more").click();
        await page.locator("#add_more").click();

        expect(await page.evaluate(() => window.harness.total())).toBe(5);
        await expect(page.locator("#id_animalimage_set-4-image")).toHaveCount(1);

        // ninguna fila se quedó con dos botones
        for (const fila of [0, 1, 2, 3, 4]) {
            await expect(boton(page, fila), `la fila ${fila} tiene un solo botón`).toHaveCount(1);
        }

        await ponerFoto(page, 3);
        await ponerFoto(page, 4);

        await abrirSelector(page, 4);
        const crop4 = await guardar(page, 4);

        expect(crop4).not.toBeNull();
        expect(await leer(page, 3), "la otra fila nueva no se tiene que llenar sola").toBeNull();

        await abrirSelector(page, 3);
        const crop3 = await guardar(page, 3);

        expect(crop3).not.toBeNull();
        expect(await leer(page, 4), "la fila 4 quedó pisada por la 3").toEqual(crop4);
    });
});


test.describe("lo que ve la persona en cada fila", () => {

    test("el botón y el cartel de cada fila dicen si esa fila ya tiene recorte", async ({page}) => {
        /* Son tres fotos iguales en la pantalla: sin el cartel por fila no hay forma de
         * saber a cuál ya se le eligió el encuadre y a cuál la va a recortar el server
         * sola. Y el estado tiene que ser por fila, no uno global. */

        await expect(boton(page, 0)).toHaveText(/Cambiar recorte/);
        await expect(cartel(page, 0)).toHaveText("Recorte elegido: así se va a ver en Instagram.");

        await expect(boton(page, 1)).toHaveText(/Elegir recorte para Instagram/);
        await expect(cartel(page, 1)).toHaveText("Si no elegís, lo recortamos automáticamente.");

        await expect(boton(page, 2)).toHaveText(/Cambiar recorte/);

        await abrirSelector(page, 1);
        await guardar(page, 1);

        await expect(boton(page, 1), "la fila 1 ya tiene recorte").toHaveText(/Cambiar recorte/);
        await expect(cartel(page, 1)).toHaveText("Recorte elegido: así se va a ver en Instagram.");

        // las otras dos no cambiaron de cartel
        await expect(boton(page, 0)).toHaveText(/Cambiar recorte/);
        await expect(boton(page, 2)).toHaveText(/Cambiar recorte/);
    });

    test("usar recorte automático en una fila deja las otras como estaban", async ({page}) => {
        /* "Usar recorte automático" guarda null a propósito. Es la operación más fácil de
         * hacer global sin querer: borra los cuatro inputs, y si no los busca por índice
         * borra los de todo el formset. */

        await abrirSelector(page, 0);
        await page.getByRole("button", {name: "Usar recorte automático"}).click();
        await expect(page.locator(".catus-crop-overlay")).toHaveCount(0);

        expect(await leer(page, 0)).toBeNull();
        await expect(boton(page, 0)).toHaveText(/Elegir recorte para Instagram/);

        expect(await crudo(page, 2), "la fila 2 tenía que quedar intacta").toEqual(CENTINELA[2]);
        await expect(boton(page, 2)).toHaveText(/Cambiar recorte/);
    });
});


test.describe("la fila de plantilla del formset", () => {

    test("__prefix__ no se lleva ningún botón ni ningún recorte", async ({page}) => {
        /* #empty_form es el molde que se clona en cada "Agregar Foto": sus inputs se
         * llaman animalimage_set-__prefix__-crop_x. Dos cosas tienen que valer:
         *
         *  - setupCropButtons no lo tiene que enganchar (recorre índices numéricos), o el
         *    botón se clonaría en cada fila nueva y quedarían dos por fila;
         *  - nada tiene que escribirle un recorte, porque ese valor se copiaría a la
         *    próxima foto que se agregue, que es una foto distinta. */

        await expect(page.locator("#empty_form button"), "el molde no lleva botón").toHaveCount(0);

        const vacio = () => page.evaluate(() =>
            document.getElementById("id_animalimage_set-__prefix__-crop_x").value);

        expect(await vacio()).toBe("");

        await abrirSelector(page, 1);
        await guardar(page, 1);

        expect(await vacio(), "el molde se llevó el recorte de la fila 1").toBe("");

        // y la fila que sale del molde no arrastra el __prefix__ sin reemplazar
        await page.locator("#add_more").click();

        const html = await page.locator("#form-set").innerHTML();
        expect(html, "quedó un __prefix__ suelto en el formset").not.toContain("__prefix__");

        expect(await page.evaluate(() =>
            document.getElementById("id_animalimage_set-3-crop_x").value)).toBe("");
    });
});


test.describe("borrar una fila recién agregada", () => {

    test("no deja el recorte suelto en el POST", async ({page}) => {
        /* Regresión que trajo el selector de recorte.
         *
         * updateRemoveAdded() sacaba dos nodos contados a mano: el .form-group del
         * checkbox Delete y su .prev(). En la fila clonada de #empty_form eso son el
         * Delete y el .form-group de la foto. Los cuatro hidden del recorte NO se iban:
         * el molde los tiene adentro de <table class='no_error'>, y el parser del
         * navegador saca los <div> de la tabla pero deja adentro los <input type=hidden>.
         * TOTAL_FORMS tampoco baja.
         *
         * Entonces el POST llevaba animalimage_set-3-crop_x=0.25 y ningún
         * animalimage_set-3-image. Como CropField.has_changed() compara números,
         * "0.25" contra None da que la fila cambió, así que el formset dejaba de tratarla
         * como fila extra vacía, la validaba entera y pedía la imagen. Comprobado contra
         * el formset de verdad (inlineformset_factory + AnimalImageForm):
         *
         *     fila borrada CON recorte -> valid: False, [{}, {'image': ['This field is required.']}]
         *     fila borrada SIN recorte -> valid: True
         *     fila borrada entera      -> valid: True
         *
         * O sea: el rescatista agregaba una foto, le elegía el recorte, se arrepentía y la
         * borraba, y no podía guardar el animal. El error hablaba de una foto que ya no
         * estaba en la pantalla, así que no había nada para corregir salvo recargar y
         * cargar todo de nuevo. Antes del recorte no pasaba: lo que quedaba suelto
         * (-id y -animal) venía vacío y la fila se salteaba.
         *
         * Se mira el POST y no el DOM porque lo que rompe el guardado es lo que se
         * serializa: un input sacado de su .form-group pero todavía dentro del <form>
         * viaja igual. */

        await page.locator("#add_more").click();
        await ponerFoto(page, 3);

        await abrirSelector(page, 3);
        expect(await guardar(page, 3), "la fila nueva tiene recorte elegido").not.toBeNull();

        const antesDeBorrar = await page.evaluate(() => window.harness.postDeLaFila(3));
        expect(antesDeBorrar.length, "antes de borrar, la fila 3 sí viajaba").toBeGreaterThan(0);

        await page.locator("#id_animalimage_set-3-DELETE").click();

        // la parte visible se va: el input de la foto y su botón de recorte
        await expect(page.locator("#id_animalimage_set-3-image")).toHaveCount(0);

        expect(await page.evaluate(() => window.harness.postDeLaFila(3)),
            "la fila borrada se lleva el recorte al POST y bloquea el guardado").toEqual([]);
    });

    test("borrar la fila nueva no se lleva las fotos que ya estaban", async ({page}) => {
        /* El arreglo saca la fila entera por su prefijo del formset, así que tiene el
         * riesgo del otro lado: barrer de más y borrar las filas que la persona no tocó.
         * El animal se guardaría sin las fotos que ya tenía, o directamente sin ninguna
         * y rebotando con "Al menos una foto del animal es requerida". */

        await page.locator("#add_more").click();
        await ponerFoto(page, 3);

        await abrirSelector(page, 3);
        await guardar(page, 3);

        await page.locator("#id_animalimage_set-3-DELETE").click();

        // las tres filas del server siguen enteras, con su recorte y su botón
        expect(await crudo(page, 0)).toEqual(CENTINELA[0]);
        expect(await crudo(page, 2)).toEqual(CENTINELA[2]);
        expect(await leer(page, 1)).toBeNull();

        for (const fila of [0, 1, 2]) {
            await expect(boton(page, fila), `la fila ${fila} quedó sin botón`).toBeVisible();
        }

        // y el selector de las que quedaron sigue andando
        await abrirSelector(page, 1);
        expect(await guardar(page, 1)).not.toBeNull();
        expect(await crudo(page, 0), "la fila 0 quedó pisada").toEqual(CENTINELA[0]);
    });

    test("después de borrar una fila se puede agregar otra y elegirle recorte", async ({page}) => {
        /* TOTAL_FORMS no baja al borrar, a propósito: la fila borrada queda como hueco
         * vacío y el formset la saltea. Lo que no puede pasar es que la fila nueva
         * reutilice el índice de la borrada y herede sus hidden. */

        await page.locator("#add_more").click();
        await ponerFoto(page, 3);
        await abrirSelector(page, 3);
        await guardar(page, 3);

        await page.locator("#id_animalimage_set-3-DELETE").click();

        await page.locator("#add_more").click();
        expect(await page.evaluate(() => window.harness.total()), "TOTAL_FORMS").toBe(5);

        await ponerFoto(page, 4);
        await abrirSelector(page, 4);

        expect(await guardar(page, 4), "la fila de después de un borrado no guarda").not.toBeNull();
        expect(await page.evaluate(() => window.harness.postDeLaFila(3)),
            "la fila borrada revivió").toEqual([]);
    });
});
