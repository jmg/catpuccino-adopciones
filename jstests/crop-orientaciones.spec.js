/*
 * Tests de navegador del recorte cuadrado para Instagram, orientación por orientación y
 * forma por forma (catus/static/js/crop-widget.js).
 *
 * crop.spec.js cubre el flujo: que el botón arranque deshabilitado, que cancelar no pise
 * el recorte, que la vista previa se lea. Acá se cubre la aritmética, que es donde el
 * recorte se rompe en silencio: la foto sale publicada igual, pero mostrando otra parte.
 *
 * Cada test corre en los dos perfiles (escritorio y iPhone 13) porque el rescatista
 * carga desde los dos, y las fracciones se calculan contra medidas de pantalla que en el
 * celular son la mitad de grandes.
 *
 *   cd jstests && npx playwright test crop-orientaciones.spec.js
 */
const {test, expect} = require("@playwright/test");

// tolerancia en fracciones: Cropper redondea el cuadro a pixeles enteros de pantalla y
// la foto se muestra escalada, asi que un par de pixeles de deriva es esperable
const TOLERANCIA = 0.01;

// lado de las miniaturas con las que se compara el contenido del recorte
const MUESTRA = 64;

/*
 * Las ocho orientaciones EXIF.
 *
 * Cropper corre con checkOrientation: le resetea el byte de orientación al archivo y
 * aplica él la transformación, guardándola en imageData.rotate / scaleX / scaleY. Las
 * cuatro que rotan 90 o 270 (5, 6, 7 y 8) intercambian el marco que ve la persona; las
 * cuatro que espejan (2, 4, 5 y 7) no lo cambian de tamaño.
 *
 * `rota` es lo que tiene que ver marcoVisible(); `espeja` es lo que el comentario de esa
 * función afirma que NO hace falta corregir.
 */
const ORIENTACIONES = [
    {valor: 1, rota: false, espeja: false, que: "derecha, sin EXIF"},
    {valor: 2, rota: false, espeja: true, que: "espejada horizontal"},
    {valor: 3, rota: false, espeja: false, que: "cabeza abajo"},
    {valor: 4, rota: false, espeja: true, que: "espejada vertical"},
    {valor: 5, rota: true, espeja: true, que: "transpuesta"},
    {valor: 6, rota: true, espeja: false, que: "90 horaria, la foto tipica de celular"},
    {valor: 7, rota: true, espeja: true, que: "transversal"},
    {valor: 8, rota: true, espeja: false, que: "90 antihoraria"},
];

// apaisada y con los lados bien distintos: si se divide por el lado equivocado, se nota
const BASE = {width: 1200, height: 800};

const FORMAS = [
    {nombre: "cuadrada", width: 1200, height: 1200,
     por: "no queda nada que recortar: el cuadro tiene que ser la foto entera"},
    {nombre: "panoramica", width: 4000, height: 800,
     por: "5:1, el caso de la foto de camara sacada a lo ancho"},
    {nombre: "tira", width: 800, height: 4000,
     por: "1:5, la captura larga de una historia"},
    {nombre: "chica", width: 600, height: 400,
     por: "mas chica que los 1200 del posteo: crop_to_square la va a agrandar"},
];

/* La transformación que endereza cada orientación, en el mismo orden en el que la aplica
 * Cropper (primero espejar, después rotar) y en el que la aplica Pillow con
 * exif_transpose del lado del server. Es el oráculo contra el que se compara. */
const ENDEREZAR = {
    1: [0, 1, 1], 2: [0, -1, 1], 3: [180, 1, 1], 4: [0, 1, -1],
    5: [90, 1, -1], 6: [90, 1, 1], 7: [90, -1, 1], 8: [-90, 1, 1],
};


function marcoVisible(foto, rota) {
    /* El marco que ve la persona, que es contra el que se guardan las fracciones.
     *
     * No se usa window.harness.marcoEsperado() porque el harness sólo intercambia los
     * lados para las orientaciones 6 y 8, y acá hacen falta también la 5 y la 7.
     */

    return rota
        ? {width: foto.height, height: foto.width}
        : {width: foto.width, height: foto.height};
}

function cuadradoCentrado(marco) {
    /* Lo que Cropper propone solo con autoCropArea: 1: el cuadrado mas grande, centrado. */

    const lado = Math.min(marco.width, marco.height);
    const w = lado / marco.width;
    const h = lado / marco.height;

    return {x: (1 - w) / 2, y: (1 - h) / 2, w: w, h: h};
}

function cuadradoEn(marco, x, y, fraccionDelLado) {
    /* Un cuadrado de verdad —mismo pixeles de lado— expresado en fracciones de cada lado. */

    const lado = Math.min(marco.width, marco.height) * fraccionDelLado;

    return {x: x, y: y, w: lado / marco.width, h: lado / marco.height};
}

async function abrirSelector(page, esperarCuadro = true) {

    await page.getByRole("button", {name: "Elegir recorte"}).click();
    await expect(page.locator(".catus-crop-overlay")).toBeVisible();

    // el boton se habilita en el callback ready de Cropper: es la senial de que ya hay recorte
    await expect(page.getByRole("button", {name: "Guardar recorte"})).toBeEnabled({timeout: 20000});

    if (esperarCuadro) {
        await expect(page.locator(".cropper-crop-box")).toBeVisible();
    }
}

async function prepararYAbrir(page, foto, esperarCuadro = true) {

    await page.evaluate((datos) => window.harness.preparar(datos), foto);
    await abrirSelector(page, esperarCuadro);
}

async function guardar(page) {

    await page.getByRole("button", {name: "Guardar recorte"}).click();
    await expect(page.locator(".catus-crop-overlay")).toHaveCount(0);

    return page.evaluate(() => window.harness.leer());
}

async function medirEnPantalla(page) {
    /* Dónde quedó el cuadro sobre la foto, medido en la pantalla y sin preguntarle nada a
     * Cropper.
     *
     * Es el oráculo del que cuelga casi todo lo de acá: .cropper-canvas es la caja de la
     * foto YA ENDEREZADA (initCanvas intercambia los lados cuando rotate % 180 == 90) y
     * el cuadro de recorte está posicionado encima. La fracción del recuadro sobre esa
     * caja es, por definición, la parte de la foto que la persona eligió — y como
     * optimize() endereza con exif_transpose antes de guardar, es también la parte que va
     * a recortar el server. Lo que se guarda tiene que dar exactamente eso.
     */

    return page.evaluate(() => {

        const lienzo = document.querySelector(".cropper-canvas").getBoundingClientRect();
        const cuadro = document.querySelector(".cropper-crop-box").getBoundingClientRect();

        return {
            x: (cuadro.left - lienzo.left) / lienzo.width,
            y: (cuadro.top - lienzo.top) / lienzo.height,
            w: cuadro.width / lienzo.width,
            h: cuadro.height / lienzo.height,
            lienzo: {width: lienzo.width, height: lienzo.height},
        };
    });
}

async function medirPreview(page) {

    return page.evaluate(() => {

        const post = document.querySelector(".catus-crop-post").getBoundingClientRect();
        const caja = document.querySelector(".catus-crop-photo").getBoundingClientRect();
        const img = document.querySelector(".catus-crop-photo img");

        return {
            post: {width: post.width, height: post.height},
            caja: {width: caja.width, height: caja.height},
            img: img ? {width: img.getBoundingClientRect().width,
                        height: img.getBoundingClientRect().height} : null,
            desborde: {scroll: document.documentElement.scrollWidth,
                       visible: document.documentElement.clientWidth},
        };
    });
}

function afirmarFraccionesValidas(crop, cuando) {
    /* Fuera de [0, 1] el server recorta lo que puede y el posteo sale con franja gris. */

    expect(crop, `${cuando}: no se guardó nada`).not.toBeNull();

    for (const clave of ["x", "y", "w", "h"]) {
        expect(Number.isFinite(crop[clave]), `${cuando}: ${clave} = ${crop[clave]} no es un número`).toBe(true);
        expect(crop[clave], `${cuando}: ${clave} quedó abajo de 0`).toBeGreaterThanOrEqual(0);
        expect(crop[clave], `${cuando}: ${clave} quedó arriba de 1`).toBeLessThanOrEqual(1);
    }

    expect(crop.w, `${cuando}: ancho cero`).toBeGreaterThan(0);
    expect(crop.h, `${cuando}: alto cero`).toBeGreaterThan(0);
    expect(crop.x + crop.w, `${cuando}: el cuadro se pasa por la derecha`).toBeLessThanOrEqual(1 + TOLERANCIA);
    expect(crop.y + crop.h, `${cuando}: el cuadro se pasa por abajo`).toBeLessThanOrEqual(1 + TOLERANCIA);
}

function afirmarCuadradoEnPixeles(crop, marco, cuando) {
    /* Cuadrado no es w == h: las fracciones son de lados distintos. Es w * ancho == h * alto.
     * Instagram publica 1200x1200; si esto no da, el posteo sale con el gato estirado. */

    const desvio = Math.abs(crop.w * marco.width - crop.h * marco.height);
    const tolerado = Math.min(marco.width, marco.height) * 0.02;

    expect(desvio,
        `${cuando}: el recorte no es cuadrado sobre ${marco.width}x${marco.height}`)
        .toBeLessThanOrEqual(tolerado);
}

function afirmarCoincideConPantalla(crop, pantalla, cuando) {
    /* Lo guardado tiene que ser lo que la persona vio marcado, lado por lado.
     *
     * La tolerancia va en pixeles de pantalla y no en fracciones: en el celular el
     * lienzo mide la mitad, y una panorámica de 4000x800 se muestra en una banda de 65px
     * de alto, donde un pixel de redondeo ya son 15 milésimas de fracción. */

    const tolX = Math.max(2 / pantalla.lienzo.width, 0.004);
    const tolY = Math.max(2 / pantalla.lienzo.height, 0.004);

    expect(Math.abs(crop.x - pantalla.x),
        `${cuando}: x guardado ${crop.x} pero en pantalla se marcó ${pantalla.x}`).toBeLessThanOrEqual(tolX);
    expect(Math.abs(crop.y - pantalla.y),
        `${cuando}: y guardado ${crop.y} pero en pantalla se marcó ${pantalla.y}`).toBeLessThanOrEqual(tolY);
    expect(Math.abs(crop.w - pantalla.w),
        `${cuando}: ancho guardado ${crop.w} pero en pantalla se marcó ${pantalla.w}`).toBeLessThanOrEqual(tolX);
    expect(Math.abs(crop.h - pantalla.h),
        `${cuando}: alto guardado ${crop.h} pero en pantalla se marcó ${pantalla.h}`).toBeLessThanOrEqual(tolY);
}

async function compararContenido(page, foto, orientacion, guardado) {
    /* Compara pixel a pixel dos cosas que tienen que ser la misma:
     *
     *   - lo que Cropper dice que la persona eligió (getCroppedCanvas, lo mismo que
     *     dibuja la vista previa), capturado ANTES de guardar porque guardar destruye
     *     el cropper;
     *   - lo que va a publicar el server: la foto cruda enderezada como la endereza
     *     exif_transpose, recortada con las fracciones que se guardaron.
     *
     * Devuelve también la diferencia contra el recorte punto-simétrico, que es lo que
     * saldría si el widget midiera sobre el marco crudo en vez del que se ve. Sirve de
     * control: si ese número tampoco es grande, la comparación no prueba nada.
     */

    return page.evaluate(async ({foto, orientacion, guardado, MUESTRA, ENDEREZAR}) => {

        const img = new Image();
        // los mismos pixeles que la foto del test, pero sin EXIF: asi el navegador no la
        // auto-orienta por su cuenta y el enderezado lo hace este código, a la vista
        img.src = window.CatusFixtures.foto(foto.width, foto.height, 1);
        await img.decode();

        const rota = orientacion >= 5;
        const ancho = rota ? foto.height : foto.width;
        const alto = rota ? foto.width : foto.height;

        function recorte(crop) {

            const derecha = document.createElement("canvas");
            derecha.width = ancho;
            derecha.height = alto;

            const ctx = derecha.getContext("2d");
            ctx.translate(ancho / 2, alto / 2);
            ctx.rotate(ENDEREZAR[orientacion][0] * Math.PI / 180);
            ctx.scale(ENDEREZAR[orientacion][1], ENDEREZAR[orientacion][2]);
            ctx.drawImage(img, -foto.width / 2, -foto.height / 2, foto.width, foto.height);

            const salida = document.createElement("canvas");
            salida.width = MUESTRA;
            salida.height = MUESTRA;
            salida.getContext("2d").drawImage(
                derecha,
                crop.x * ancho, crop.y * alto, crop.w * ancho, crop.h * alto,
                0, 0, MUESTRA, MUESTRA);

            return salida;
        }

        function diferencia(a, b) {

            const pa = a.getContext("2d").getImageData(0, 0, MUESTRA, MUESTRA).data;
            const pb = b.getContext("2d").getImageData(0, 0, MUESTRA, MUESTRA).data;
            let suma = 0;

            for (let i = 0; i < pa.length; i += 4) {
                suma += Math.abs(pa[i] - pb[i])
                    + Math.abs(pa[i + 1] - pb[i + 1])
                    + Math.abs(pa[i + 2] - pb[i + 2]);
            }

            return suma / (pa.length / 4 * 3);
        }

        const espejado = {
            x: 1 - guardado.x - guardado.w,
            y: 1 - guardado.y - guardado.h,
            w: guardado.w,
            h: guardado.h,
        };

        return {
            contraServidor: diferencia(window.__elegido, recorte(guardado)),
            contraEspejado: diferencia(window.__elegido, recorte(espejado)),
        };

    }, {foto, orientacion, guardado, MUESTRA, ENDEREZAR});
}


test.beforeEach(async ({page}) => {

    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;

    await page.goto("/");
    await page.waitForFunction(() => window.CatusCrop && window.Cropper && window.harness);
});

test.afterEach(async ({page}) => {
    // un TypeError adentro de un handler de Cropper deja el selector a medias sin que se note
    expect(page.errores, "la pagina no tiene que tirar errores de JS").toEqual([]);
});


test.describe("las ocho orientaciones EXIF", () => {

    for (const caso of ORIENTACIONES) {

        const foto = {...BASE, orientacion: caso.valor};
        const marco = marcoVisible(BASE, caso.rota);

        test(`orientacion ${caso.valor} (${caso.que}): el recorte se mide sobre el marco que se ve`,
            async ({page}) => {
                /* La foto se guarda de una manera y se ve de otra. Dividir por el lado del
                 * archivo en vez del lado visible hacía que el rescatista eligiera la cara
                 * del gato y se publicara la pared: la fracción salía bien formada, nadie
                 * veía un error, y el posteo salía mal. */

                await prepararYAbrir(page, foto);

                const pantalla = await medirEnPantalla(page);

                // el lienzo de Cropper es la foto enderezada: tiene que tener la
                // proporcion del marco visible, no la del archivo
                expect(pantalla.lienzo.width / pantalla.lienzo.height,
                    `Cropper no muestra la foto como ${marco.width}x${marco.height}`)
                    .toBeCloseTo(marco.width / marco.height, 1);

                const crop = await guardar(page);
                const cuando = `orientacion ${caso.valor}`;

                afirmarFraccionesValidas(crop, cuando);
                afirmarCuadradoEnPixeles(crop, marco, cuando);
                afirmarCoincideConPantalla(crop, pantalla, cuando);

                // y sin tocar nada, Cropper propone el cuadrado mas grande centrado
                const esperado = cuadradoCentrado(marco);
                expect(crop.w).toBeCloseTo(esperado.w, 2);
                expect(crop.h).toBeCloseTo(esperado.h, 2);
                expect(crop.x).toBeCloseTo(esperado.x, 2);
                expect(crop.y).toBeCloseTo(esperado.y, 2);
            });

        test(`orientacion ${caso.valor} (${caso.que}): ida y vuelta sin tocar nada`,
            async ({page}) => {
                /* La propiedad que más importa y la que más barato se rompe: abrir un
                 * recorte ya elegido y guardarlo sin moverlo tiene que devolver lo mismo.
                 * Si no, cada vez que alguien entra a mirarlo se lo corre un poco, y
                 * después de tres visitas el gato quedó afuera del cuadro. */

                const crop = cuadradoEn(marco, 0.1, 0.1, 0.5);

                await prepararYAbrir(page, {...foto, crop});
                const vuelta = await guardar(page);

                const cuando = `ida y vuelta orientacion ${caso.valor}`;
                afirmarFraccionesValidas(vuelta, cuando);
                afirmarCuadradoEnPixeles(vuelta, marco, cuando);

                expect(vuelta.x, `${cuando}: x`).toBeCloseTo(crop.x, 2);
                expect(vuelta.y, `${cuando}: y`).toBeCloseTo(crop.y, 2);
                expect(vuelta.w, `${cuando}: ancho`).toBeCloseTo(crop.w, 2);
                expect(vuelta.h, `${cuando}: alto`).toBeCloseTo(crop.h, 2);
            });

        test(`orientacion ${caso.valor} (${caso.que}): el server recorta lo mismo que se eligió`,
            async ({page}) => {
                /* El comentario de marcoVisible dice que el espejado de las orientaciones
                 * 2, 4, 5 y 7 no hace falta corregirlo, porque Cropper muestra la foto ya
                 * espejada y exif_transpose la guarda igual. Esto lo comprueba con
                 * pixeles en vez de creerle: recorta la foto cruda como la va a recortar
                 * el server y la compara con lo que Cropper dice que se eligió.
                 *
                 * El recorte va pegado a un borde a propósito. Con el cuadrado centrado
                 * un error de espejado no se vería: el recorte sería el mismo. */

                const crop = cuadradoEn(marco, 0.05, 0.05, 0.4);

                await prepararYAbrir(page, {...foto, crop});

                // hay que capturarlo antes: guardar cierra el diálogo y destruye el cropper
                await page.evaluate((lado) => {
                    window.__elegido = document.querySelector(".catus-crop-stage img")
                        .cropper.getCroppedCanvas({width: lado, height: lado});
                }, MUESTRA);

                const guardado = await guardar(page);
                afirmarFraccionesValidas(guardado, `contenido orientacion ${caso.valor}`);

                const dif = await compararContenido(page, BASE, caso.valor, guardado);

                // control: que la muestra sea asimétrica, si no la comparación no prueba nada
                expect(dif.contraEspejado,
                    `orientacion ${caso.valor}: el recorte elegido es simétrico, este test no prueba nada`)
                    .toBeGreaterThan(20);

                expect(dif.contraServidor,
                    `orientacion ${caso.valor}${caso.espeja ? " (espejada)" : ""}: el server `
                    + "va a publicar una parte distinta de la que se eligió")
                    .toBeLessThan(8);
            });
    }
});


test.describe("formas extremas", () => {

    for (const forma of FORMAS) {

        const foto = {width: forma.width, height: forma.height, orientacion: 1};
        const marco = {width: forma.width, height: forma.height};

        test(`foto ${forma.nombre} ${forma.width}x${forma.height}: ${forma.por}`, async ({page}) => {

            await prepararYAbrir(page, foto);

            const pantalla = await medirEnPantalla(page);
            const preview = await medirPreview(page);
            const crop = await guardar(page);
            const cuando = `foto ${forma.nombre}`;

            afirmarFraccionesValidas(crop, cuando);
            afirmarCuadradoEnPixeles(crop, marco, cuando);
            afirmarCoincideConPantalla(crop, pantalla, cuando);

            const esperado = cuadradoCentrado(marco);
            expect(crop.w, `${cuando}: ancho`).toBeCloseTo(esperado.w, 2);
            expect(crop.h, `${cuando}: alto`).toBeCloseTo(esperado.h, 2);

            // la vista previa del posteo tiene que seguir siendo un cuadrado con la foto
            // adentro: es lo único que mira la persona antes de apretar guardar
            expect(preview.post.width, `${cuando}: la preview no tiene ancho`).toBeGreaterThan(50);
            expect(preview.post.height / preview.post.width, `${cuando}: la preview no es cuadrada`)
                .toBeCloseTo(1, 1);
            expect(preview.caja.width, `${cuando}: el hueco de la foto no tiene ancho`).toBeGreaterThan(10);
            expect(preview.caja.height / preview.caja.width, `${cuando}: el hueco de la foto no es cuadrado`)
                .toBeCloseTo(1, 1);

            expect(preview.img, `${cuando}: la preview se quedó sin foto`).not.toBeNull();
            expect(preview.img.width, `${cuando}: la foto de la preview no tiene ancho`).toBeGreaterThan(0);
            expect(preview.img.height, `${cuando}: la foto de la preview no tiene alto`).toBeGreaterThan(0);

            // la foto se muestra con la proporción real, no estirada para llenar el hueco
            expect(preview.img.width / preview.img.height, `${cuando}: la preview estira la foto`)
                .toBeCloseTo(marco.width / marco.height, 1);

            // y el recorte cuadrado tapa el hueco entero: si no, el posteo se ve con
            // franjas grises que en el Instagram de verdad no van a estar
            expect(preview.img.width, `${cuando}: queda franja gris al costado`)
                .toBeGreaterThanOrEqual(preview.caja.width - 1);
            expect(preview.img.height, `${cuando}: queda franja gris arriba o abajo`)
                .toBeGreaterThanOrEqual(preview.caja.height - 1);

            expect(preview.desborde.scroll, `${cuando}: el diálogo scrollea de costado`)
                .toBeLessThanOrEqual(preview.desborde.visible + 1);
        });

        test(`foto ${forma.nombre} ${forma.width}x${forma.height}: ida y vuelta sin tocar nada`,
            async ({page}) => {

                const crop = cuadradoEn(marco, 0.1, 0.1, 0.5);

                await prepararYAbrir(page, {...foto, crop});
                const vuelta = await guardar(page);

                const cuando = `ida y vuelta ${forma.nombre}`;
                afirmarFraccionesValidas(vuelta, cuando);
                afirmarCuadradoEnPixeles(vuelta, marco, cuando);

                expect(vuelta.x, `${cuando}: x`).toBeCloseTo(crop.x, 2);
                expect(vuelta.y, `${cuando}: y`).toBeCloseTo(crop.y, 2);
                expect(vuelta.w, `${cuando}: ancho`).toBeCloseTo(crop.w, 2);
                expect(vuelta.h, `${cuando}: alto`).toBeCloseTo(crop.h, 2);
            });
    }
});


test.describe("un recorte guardado que ya no entra en la foto", () => {

    /* Pasa de verdad: la foto se reemplaza por otra de otra forma y los crop_x/y/w/h
     * viejos siguen en la fila de AnimalImage, o alguien manda el POST a mano. Abrir eso
     * no puede tirar un error ni guardar fracciones que se salgan de la foto: el server
     * las aplica sin preguntar y el posteo sale con una franja gris. */

    const casos = [
        {nombre: "foto derecha", foto: {...BASE, orientacion: 1}, rota: false},
        {nombre: "foto rotada 90", foto: {...BASE, orientacion: 6}, rota: true},
    ];

    for (const caso of casos) {

        test(`${caso.nombre}: se acomoda solo y lo que se guarda sigue siendo válido`,
            async ({page}) => {

                const marco = marcoVisible(BASE, caso.rota);

                // arranca a 9/10 del ancho y pide medio ancho más: se pasa por los dos lados
                await prepararYAbrir(page, {...caso.foto, crop: {x: 0.9, y: 0.9, w: 0.5, h: 0.75}});

                const pantalla = await medirEnPantalla(page);
                const crop = await guardar(page);
                const cuando = `${caso.nombre} fuera de rango`;

                afirmarFraccionesValidas(crop, cuando);
                afirmarCuadradoEnPixeles(crop, marco, cuando);
                afirmarCoincideConPantalla(crop, pantalla, cuando);

                // se acomoda contra el borde de abajo a la derecha, no se descarta
                expect(crop.x + crop.w, `${cuando}: no llegó al borde derecho`)
                    .toBeGreaterThan(1 - TOLERANCIA);
                expect(crop.y + crop.h, `${cuando}: no llegó al borde de abajo`)
                    .toBeGreaterThan(1 - TOLERANCIA);
            });
    }

    test("un recorte de ancho cero vuelve al automático en vez de guardar un cuadro vacío",
        async ({page}) => {
            /* Con w = 0 Cropper esconde el cuadro y no queda nada seleccionado. El guard
             * `if (w <= 0 || h <= 0) return null` de toFractions es el que cubre eso, y
             * null quiere decir "recorte automático", que es lo que corresponde.
             *
             * Del lado del server clean_crop ya descarta w <= 0, asi que esto no llega
             * desde la base: llega de un input pisado a mano o de una foto que se
             * reemplazó. Lo que importa es que el diálogo no explote y que no se guarde
             * un recorte de cero pixeles, que crop_to_square no sabe recortar. */

            await prepararYAbrir(page, {...BASE, orientacion: 1, crop: {x: 1, y: 1, w: 0, h: 0}}, false);

            const crop = await guardar(page);

            if (crop !== null) {
                afirmarFraccionesValidas(crop, "recorte de ancho cero");
                afirmarCuadradoEnPixeles(crop, marcoVisible(BASE, false), "recorte de ancho cero");
            }

            // se llamó a onSave una sola vez, con null o con un recorte usable
            expect(await page.evaluate(() => window.harness.guardados.length)).toBe(1);
        });
});
