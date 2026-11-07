/*
 * Tests de navegador del selector de recorte para Instagram
 * (catus/static/js/crop-widget.js).
 *
 * Corren en Chromium de verdad, con dos perfiles: escritorio con mouse y un iPhone 13
 * con touch. Cada test dice qué se rompía y para quién, como el resto de la suite.
 *
 *   cd jstests && npm test
 */
const {test, expect} = require("@playwright/test");

// el posteo es un lienzo de 1400 con la foto de 1200 adentro
const CANVAS = 1400;
const NOMBRE_FONT = 150;

// tolerancia en fracciones: Cropper redondea a pixeles enteros y la foto se muestra
// escalada, asi que un par de pixeles de deriva sobre 3000 es esperable
const TOLERANCIA = 0.01;

const FOTOS = {
    // apaisada comun, sin EXIF
    paisaje: {width: 2000, height: 1000, orientacion: 1},
    // la foto tipica de celular: se saca apaisada y el EXIF dice que va rotada 90
    celular: {width: 4032, height: 3024, orientacion: 6},
};

async function abrirSelector(page) {
    /* Abre el selector y espera a que Cropper termine de acomodarse. */

    await page.getByRole("button", {name: "Elegir recorte"}).click();
    await expect(page.locator(".catus-crop-overlay")).toBeVisible();

    // el boton se habilita en el callback ready de Cropper: es la senial de que ya hay recorte
    await expect(page.getByRole("button", {name: "Guardar recorte"})).toBeEnabled({timeout: 15000});
    await expect(page.locator(".cropper-crop-box")).toBeVisible();
}

async function guardar(page) {

    await page.getByRole("button", {name: "Guardar recorte"}).click();
    await expect(page.locator(".catus-crop-overlay")).toHaveCount(0);

    return page.evaluate(() => window.harness.leer());
}

async function arrastrar(page, esMobile, desde, hasta, pasos = 12) {
    /* Arrastra de verdad: mouse en escritorio, touch real por CDP en el celular.
     *
     * No alcanza con usar el mouse en los dos: Cropper escucha eventos de puntero y el
     * celular no tiene mouse, asi que un test que arrastra con mouse en el perfil mobile
     * estaria probando algo que en el telefono de la persona no pasa nunca.
     */

    if (!esMobile) {
        await page.mouse.move(desde.x, desde.y);
        await page.mouse.down();
        for (let i = 1; i <= pasos; i++) {
            await page.mouse.move(
                desde.x + (hasta.x - desde.x) * i / pasos,
                desde.y + (hasta.y - desde.y) * i / pasos,
            );
        }
        await page.mouse.up();
        return;
    }

    const cdp = await page.context().newCDPSession(page);

    const tocar = (type, punto) => cdp.send("Input.dispatchTouchEvent", {
        type,
        touchPoints: type === "touchEnd" ? [] : [{x: Math.round(punto.x), y: Math.round(punto.y)}],
    });

    await tocar("touchStart", desde);
    for (let i = 1; i <= pasos; i++) {
        await tocar("touchMove", {
            x: desde.x + (hasta.x - desde.x) * i / pasos,
            y: desde.y + (hasta.y - desde.y) * i / pasos,
        });
    }
    await tocar("touchEnd", hasta);
    await cdp.detach();
}

function esCuadradoEnPixeles(crop, marco) {
    /* El recorte se guarda en fracciones de cada lado, asi que "cuadrado" no es w == h:
     * es w * ancho == h * alto. Instagram publica 1200x1200; si esto no da cuadrado, el
     * posteo sale estirado. */

    return Math.abs(crop.w * marco.width - crop.h * marco.height);
}

test.beforeEach(async ({page}) => {

    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;

    await page.goto("/");
    await page.waitForFunction(() => window.CatusCrop && window.Cropper && window.harness);
});

test.afterEach(async ({page}) => {
    // un TypeError en un handler de Cropper deja el selector a medias sin que se note
    expect(page.errores, "la pagina no tiene que tirar errores de JS").toEqual([]);
});


test.describe("el recorte que se guarda", () => {

    test("es un cuadrado que entra dentro de la foto", async ({page}) => {
        /* Si el cuadro se va del borde, crop_to_square recorta menos de lo pedido y el
         * posteo sale con una franja gris. */

        await page.evaluate((foto) => window.harness.preparar(foto), FOTOS.paisaje);
        await abrirSelector(page);

        const crop = await guardar(page);
        const marco = await page.evaluate(() => window.harness.marcoEsperado());

        expect(crop).not.toBeNull();
        for (const clave of ["x", "y", "w", "h"]) {
            expect(crop[clave], `${clave} tiene que ser una fraccion entre 0 y 1`).toBeGreaterThanOrEqual(0);
            expect(crop[clave]).toBeLessThanOrEqual(1);
        }
        expect(crop.x + crop.w, "el cuadro se pasa por la derecha").toBeLessThanOrEqual(1 + TOLERANCIA);
        expect(crop.y + crop.h, "el cuadro se pasa por abajo").toBeLessThanOrEqual(1 + TOLERANCIA);

        expect(esCuadradoEnPixeles(crop, marco)).toBeLessThan(marco.width * TOLERANCIA);
    });

    test("de una foto vertical de celular se mide sobre el marco que ve la persona", async ({page}) => {
        /* EL bug que motivó estos tests.
         *
         * Cropper le pone image-orientation:0deg al clon y aplica el EXIF por su cuenta,
         * asi que getData() viene en el marco rotado (3024x4032, lo que la persona ve)
         * pero naturalWidth/naturalHeight siguen siendo los del archivo (4032x3024).
         * Dividiendo por el lado equivocado, el rescatista elegia la cara del gato y se
         * publicaba cualquier otra parte. */

        await page.evaluate((foto) => window.harness.preparar(foto), FOTOS.celular);
        await abrirSelector(page);

        const crop = await guardar(page);

        // marco visible 3024x4032: el cuadrado mas grande ocupa todo el ancho
        // y 3024/4032 = 0.75 del alto. Con el bug daba justo al reves.
        expect(crop.w, "tiene que tomar todo el ancho del marco vertical").toBeCloseTo(1, 2);
        expect(crop.h, "3024/4032").toBeCloseTo(0.75, 2);
        expect(crop.y, "centrado vertical: (1 - 0.75) / 2").toBeCloseTo(0.125, 2);
        expect(crop.x).toBeCloseTo(0, 2);

        // y en pixeles del marco visible tiene que dar cuadrado
        expect(esCuadradoEnPixeles(crop, {width: 3024, height: 4032})).toBeLessThan(40);
    });

    test("se escribe con punto decimal y no con coma", async ({page}) => {
        /* El sitio corre en es-ar. Un "0,25" en el input no vuelve a parsear como numero
         * y el recorte guardado se perdia en silencio. */

        await page.evaluate((foto) => window.harness.preparar(foto), FOTOS.paisaje);
        await abrirSelector(page);
        await page.getByRole("button", {name: "Guardar recorte"}).click();

        const crudo = await page.evaluate(() => window.harness.crudo());

        for (const [clave, valor] of Object.entries(crudo)) {
            expect(valor, `${clave} no puede venir vacio`).not.toBe("");
            expect(valor, `${clave} = ${valor} tiene coma decimal`).not.toContain(",");
            expect(Number.isFinite(parseFloat(valor)), `${clave} = ${valor} no parsea`).toBe(true);
        }
    });
});


test.describe("la ida y vuelta del recorte", () => {

    for (const [nombre, foto] of Object.entries(FOTOS)) {

        test(`un recorte guardado de una foto ${nombre} se reabre en el mismo lugar`, async ({page}) => {
            /* Si abrir y guardar sin tocar nada corre el encuadre, cada vez que alguien
             * entra a mirar el recorte se lo mueve un poco. */

            const marco = nombre === "celular"
                ? {width: foto.height, height: foto.width}
                : {width: foto.width, height: foto.height};

            // un cuadrado de verdad sobre el marco visible, pegado arriba a la izquierda
            const lado = Math.min(marco.width, marco.height) * 0.6;
            const crop = {
                x: 0.1, y: 0.1,
                w: lado / marco.width,
                h: lado / marco.height,
            };

            await page.evaluate((datos) => window.harness.preparar(datos), {...foto, crop});
            await abrirSelector(page);

            const vuelta = await guardar(page);

            expect(vuelta.x).toBeCloseTo(crop.x, 2);
            expect(vuelta.y).toBeCloseTo(crop.y, 2);
            expect(vuelta.w).toBeCloseTo(crop.w, 2);
            expect(vuelta.h).toBeCloseTo(crop.h, 2);
        });
    }

    test("mover el cuadro cambia el recorte y lo deja valido", async ({page}, testInfo) => {
        /* Con mouse en escritorio y con el dedo en el celular: son dos caminos de
         * eventos distintos adentro de Cropper. */

        const esMobile = testInfo.project.name === "mobile";

        await page.evaluate((foto) => window.harness.preparar(foto), FOTOS.paisaje);
        await abrirSelector(page);

        const inicial = await page.evaluate(() => {
            const c = window.harness;
            return c.leer();
        });

        const caja = await page.locator(".cropper-crop-box").boundingBox();
        expect(caja, "tiene que haber cuadro de recorte").not.toBeNull();

        const centro = {x: caja.x + caja.width / 2, y: caja.y + caja.height / 2};
        await arrastrar(page, esMobile, centro, {x: centro.x - caja.width * 0.35, y: centro.y});

        const crop = await guardar(page);
        const marco = await page.evaluate(() => window.harness.marcoEsperado());

        expect(crop).not.toBeNull();
        const movio = inicial === null || Math.abs(crop.x - inicial.x) > TOLERANCIA;
        expect(movio, "arrastrar tiene que mover el encuadre").toBe(true);

        expect(crop.x).toBeGreaterThanOrEqual(0);
        expect(crop.x + crop.w).toBeLessThanOrEqual(1 + TOLERANCIA);
        expect(esCuadradoEnPixeles(crop, marco)).toBeLessThan(marco.width * TOLERANCIA);
    });
});


test.describe("no perder el recorte que ya estaba", () => {

    test("guardar esta deshabilitado hasta que Cropper termina de abrir la foto", async ({page}) => {
        /* Guardar antes de tiempo devolvia null, que significa "recorte automatico", asi
         * que un click apurado le borraba a la persona el encuadre que ya habia elegido. */

        await page.evaluate((foto) => window.harness.preparar(foto), FOTOS.celular);

        // todo en el mismo tick: Cropper abre la foto en un callback asincrónico, asi que
        // mientras no soltemos el hilo tenemos garantizado el estado "todavia no listo".
        // Separarlo en dos evaluate no sirve: entre uno y otro Cropper ya termino.
        const antesDeEstarListo = await page.evaluate(() => {
            document.getElementById("abrir").click();

            const boton = document.querySelector(".catus-crop-actions .btn-primary");
            const deshabilitado = boton.disabled;

            // y aunque alguien lo habilite por su cuenta, no hay recorte para guardar
            boton.disabled = false;
            boton.click();

            return {deshabilitado: deshabilitado, guardados: window.harness.guardados.length};
        });

        expect(antesDeEstarListo.deshabilitado, "el boton arranca deshabilitado").toBe(true);
        expect(antesDeEstarListo.guardados, "sin Cropper listo no se guarda nada").toBe(0);

        await expect(page.getByRole("button", {name: "Guardar recorte"})).toBeEnabled({timeout: 15000});
    });

    test("cancelar no toca el recorte guardado", async ({page}) => {

        const crop = {x: 0.1, y: 0.1, w: 0.5, h: 1};
        await page.evaluate((datos) => window.harness.preparar(datos), {...FOTOS.paisaje, crop});
        await abrirSelector(page);

        await page.getByRole("button", {name: "Cancelar"}).click();
        await expect(page.locator(".catus-crop-overlay")).toHaveCount(0);

        expect(await page.evaluate(() => window.harness.guardados.length)).toBe(0);
        expect(await page.evaluate(() => window.harness.leer())).toEqual(crop);
    });

    test("usar recorte automatico borra el recorte a proposito", async ({page}) => {

        await page.evaluate((datos) => window.harness.preparar(datos),
            {...FOTOS.paisaje, crop: {x: 0.1, y: 0.1, w: 0.5, h: 1}});
        await abrirSelector(page);

        await page.getByRole("button", {name: "Usar recorte automático"}).click();
        await expect(page.locator(".catus-crop-overlay")).toHaveCount(0);

        expect(await page.evaluate(() => window.harness.guardados)).toEqual([null]);
        expect(await page.evaluate(() => window.harness.leer())).toBeNull();
    });
});


test.describe("la vista previa del posteo", () => {

    test("dibuja el nombre en pixeles proporcionales al ancho, no en porcentaje", async ({page}) => {
        /* Un font-size en % se resuelve contra el font-size del padre, no contra el
         * ancho: el nombre salia de ~1.7px y la barra verde quedaba una astilla. Se ve
         * distinto en cada pantalla, por eso el test corre en los dos perfiles. */

        await page.evaluate((foto) => window.harness.preparar(foto), FOTOS.paisaje);
        await abrirSelector(page);

        const medidas = await page.evaluate(() => {
            const post = document.querySelector(".catus-crop-post");
            const bar = document.querySelector(".catus-crop-namebar");
            return {
                anchoPost: post.clientWidth,
                fuenteBar: parseFloat(window.getComputedStyle(bar).fontSize),
                altoBar: bar.getBoundingClientRect().height,
            };
        });

        expect(medidas.anchoPost, "la preview tiene que tener ancho").toBeGreaterThan(50);

        const esperada = NOMBRE_FONT * medidas.anchoPost / CANVAS;
        expect(medidas.fuenteBar).toBeCloseTo(esperada, 1);

        // y con eso el nombre tiene que ser legible, no una astilla
        expect(medidas.fuenteBar, "el nombre quedo ilegible").toBeGreaterThan(4);
        expect(medidas.altoBar).toBeGreaterThan(medidas.fuenteBar);
    });

    test("el dialogo entra en la pantalla sin scroll horizontal", async ({page}) => {
        /* En el celular la vista previa se va abajo por el @media de 640px. Si algo se
         * pasa de ancho, los botones quedan fuera de alcance. */

        await page.evaluate((foto) => window.harness.preparar(foto), FOTOS.celular);
        await abrirSelector(page);

        const desborde = await page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth,
            visible: document.documentElement.clientWidth,
        }));

        expect(desborde.scroll, "la pagina scrollea de costado").toBeLessThanOrEqual(desborde.visible + 1);

        // los tres botones tienen que estar dentro de la ventana y ser clickeables
        for (const nombre of ["Usar recorte automático", "Cancelar", "Guardar recorte"]) {
            const boton = page.getByRole("button", {name: nombre});
            await expect(boton).toBeVisible();
            const caja = await boton.boundingBox();
            expect(caja.x, `${nombre} se sale por la izquierda`).toBeGreaterThanOrEqual(-1);
            expect(caja.x + caja.width, `${nombre} se sale por la derecha`)
                .toBeLessThanOrEqual(desborde.visible + 1);
        }
    });
});


test.describe("cuando algo no carga", () => {

    test("sin Cropper avisa y no rompe la pantalla", async ({page}) => {
        /* Si el estatico no carga, el boton no puede tirar un TypeError y dejar al
         * rescatista sin poder guardar el animal. */

        await page.goto("/sin-cropper.html");
        await page.waitForFunction(() => window.CatusCrop);

        await page.getByRole("button", {name: "Elegir recorte"}).click();

        expect(await page.evaluate(() => window.avisos)).toEqual([
            "No se pudo cargar el selector de recorte. Refrescá la página e intentá de nuevo.",
        ]);
        expect(await page.evaluate(() => window.errores)).toEqual([]);
        await expect(page.locator(".catus-crop-overlay")).toHaveCount(0);

        page.errores = [];
    });

    test("una foto que no carga avisa y cierra", async ({page}) => {

        await page.evaluate(() => {
            window.avisos = [];
            window.alert = (mensaje) => window.avisos.push(mensaje);
            window.harness.preparar({});
        });

        await page.evaluate(() => {
            window.CatusCrop.open({
                src: "/no-existe-esta-foto.jpg",
                crop: null,
                nombre: "Willy",
                onSave: () => window.harness.guardados.push("NO"),
            });
        });

        await expect(page.locator(".catus-crop-overlay")).toHaveCount(0, {timeout: 15000});
        expect(await page.evaluate(() => window.avisos)).toEqual(["No se pudo cargar la foto para recortar."]);
        expect(await page.evaluate(() => window.harness.guardados)).toEqual([]);
    });
});
