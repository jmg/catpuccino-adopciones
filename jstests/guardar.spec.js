/*
 * "Guardar Cambios" de catus/templates/animal/edit.html se apaga en cuanto sale el
 * formulario.
 *
 * Un doble clic mandaba dos POST y cargaba dos veces el mismo animal. Contra eso protege
 * este JS, no el server: el server busca el duplicado y después guarda, sin lock, así que
 * frena al segundo envío sólo si llega después de que el primero se guardó
 * (catus/tests/test_duplicados.py), y los dos POST de un doble clic llegan casi juntos.
 * Acá se prueba:
 *
 *   - que el segundo POST ni salga, ni por un segundo clic ni por dos envíos pegados;
 *   - que si algo frena el envío (un campo obligatorio vacío, otra validación) no quede
 *     ningún botón apagado, porque la persona tiene que poder corregir y guardar;
 *   - que volver atrás con el navegador los vuelva a prender: la página vuelve tal como
 *     quedó, con los botones apagados, y sin esto no se podía guardar de nuevo;
 *   - que si la navegación se corta sin cambiar de página (Detener, Esc, un corte de red)
 *     se vuelvan a prender solos a los 90 segundos.
 *
 * El JS es el del template de verdad (template-js.js), sobre fixtures/harness-guardar.html.
 *
 *   cd jstests && npx playwright test guardar.spec.js
 */
const {test, expect} = require("@playwright/test");
const {RUTA_JS, jsDelTemplate} = require("./template-js");

const JS_DEL_TEMPLATE = jsDelTemplate();

const BOTONES = ["#send-form-button", "#send-form-button-bottom"];

test.beforeEach(async ({page}) => {

    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;

    /* Los POST del formulario se anotan y se contestan con 204: con eso el navegador no
     * navega y la página queda como estaba al enviar, con los botones apagados. Es lo que
     * ve la persona mientras sube un POST lento. Dejarlo colgado sería más parecido, pero
     * con una navegación pendiente Playwright no deja ni evaluar la página. Un test puede
     * cambiar la respuesta con page.contestarPost. */
    page.posts = [];
    page.contestarPost = (route) => route.fulfill({status: 204});
    await page.route("**/guardar-de-prueba/", (route) => {
        page.posts.push(route.request());
        return page.contestarPost(route);
    });

    // el template valida el nombre por AJAX cuando cambia; acá siempre está libre
    await page.route("**/animal/validatename/", (route) => route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({valid: true}),
    }));

    await page.route("**" + RUTA_JS, (route) => route.fulfill({
        status: 200,
        contentType: "text/javascript; charset=utf-8",
        body: JS_DEL_TEMPLATE,
    }));

    await page.goto("/harness-guardar.html");

    page.htmlOriginal = await Promise.all(BOTONES.map((boton) => page.locator(boton).innerHTML()));
});

test.afterEach(async ({page}) => {
    // un TypeError adentro del handler de submit deja la página sin guarda y no se nota
    expect(page.errores, "la página no tiene que tirar errores de JS").toEqual([]);
});

async function guardar(page, boton) {

    await page.locator(boton || BOTONES[0]).click({noWaitAfter: true});
}

async function esperarPosts(page, cantidad) {

    await expect.poll(() => page.posts.length, {timeout: 5000}).toBe(cantidad);
}

async function apagados(page) {

    for (const boton of BOTONES) {
        await expect(page.locator(boton)).toBeDisabled();
        await expect(page.locator(boton)).toContainText("Guardando");
    }
}

async function prendidos(page) {

    for (const [indice, boton] of BOTONES.entries()) {
        await expect(page.locator(boton)).toBeEnabled();
        expect(await page.locator(boton).innerHTML(), "el botón no recuperó su texto").toBe(page.htmlOriginal[indice]);
    }
}

test.describe("el segundo envío no sale", () => {

    test("un doble clic manda un solo POST", async ({page}) => {

        await page.fill("#id_nombre", "Rocco");

        await guardar(page);
        await esperarPosts(page, 1);
        await apagados(page);

        // el segundo clic, con el mouse de verdad, en cualquiera de los dos botones
        await page.locator(BOTONES[0]).click({force: true, noWaitAfter: true});
        await page.locator(BOTONES[1]).click({force: true, noWaitAfter: true});
        await page.waitForTimeout(300);

        expect(page.posts.length, "salió un segundo POST: el doble clic carga dos veces el animal").toBe(1);
    });

    test("dos envíos pegados, antes de que se apaguen los botones: el segundo se frena", async ({page}) => {
        /* Los botones se apagan un instante después del envío; lo que frena a un segundo
         * envío que llega antes es la marca que se pone en el momento. */

        await page.fill("#id_nombre", "Rocco");

        const frenados = await page.evaluate(() => {

            const vistos = [];

            // window escucha después que document: ve lo que decidió la guarda
            window.addEventListener("submit", (event) => vistos.push(event.defaultPrevented));

            const form = document.getElementById("adoption-form");
            const boton = document.getElementById("send-form-button");

            form.requestSubmit(boton);
            form.requestSubmit(boton);

            return vistos;
        });

        expect(frenados).toEqual([false, true]);
        await esperarPosts(page, 1);
    });
});

test.describe("si algo frena el envío, se puede volver a guardar", () => {

    test("con un campo obligatorio vacío no se apaga nada", async ({page}) => {
        /* La validación del navegador frena el envío antes del submit: los botones tienen
         * que seguir andando para guardar después de completar. */

        await guardar(page);
        await page.waitForTimeout(200);

        expect(page.posts.length).toBe(0);
        await prendidos(page);

        await page.fill("#id_nombre", "Rocco");
        await guardar(page);

        await esperarPosts(page, 1);
    });

    test("si otro código frena el envío, los botones siguen andando", async ({page}) => {
        /* Lo que se engancha después de la guarda corre después que ella: la guarda ya
         * puso la marca y tiene que levantarla si el envío no salió. */

        await page.fill("#id_nombre", "Rocco");
        await page.evaluate(() => {
            window.frenar = (event) => event.preventDefault();
            document.addEventListener("submit", window.frenar);
        });

        await guardar(page);
        await page.waitForTimeout(200);

        expect(page.posts.length).toBe(0);
        await prendidos(page);

        await page.evaluate(() => document.removeEventListener("submit", window.frenar));
        await guardar(page);

        await esperarPosts(page, 1);
    });
});

test("volver atrás con el navegador los vuelve a prender", async ({page}) => {
    /* La página vuelve del bfcache tal como quedó, y el navegador le manda pageshow.
     * Playwright no deja a Chromium usar el bfcache, así que el evento se manda a mano. */

    await page.fill("#id_nombre", "Rocco");
    await guardar(page);
    await esperarPosts(page, 1);
    await apagados(page);

    await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pageshow", {persisted: true})));

    await prendidos(page);

    await guardar(page, BOTONES[1]);
    await esperarPosts(page, 2);
});

test("si la navegación se corta, a los 90 segundos se puede volver a guardar", async ({page}) => {
    /* Detener o Esc durante la subida, o un corte de red: el navegador se queda en la
     * página sin navegar y no llega pageshow. Antes los botones quedaban apagados y la
     * única salida era recargar, perdiendo lo cargado con las fotos.
     *
     * route.abort("aborted") es el net::ERR_ABORTED de Detener: Chromium no muestra su
     * página de error y deja la que estaba. El reloj es el de Playwright, así el test no
     * espera 90 segundos de verdad; se instala antes de cargar la página, para que el
     * setTimeout del template sea el suyo. */

    await page.clock.install();
    await page.goto("/harness-guardar.html");

    page.contestarPost = (route) => route.abort("aborted");

    await page.fill("#id_nombre", "Rocco");
    await guardar(page);
    await esperarPosts(page, 1);
    await apagados(page);

    // al minuto todavía no: desde el celular, subir 4 a 6 fotos de varios MB suele pasar los 20
    // segundos, y un botón que vuelve a su estado normal se lee como que terminó o falló
    await page.clock.runFor(60000);
    await apagados(page);
    await page.locator(BOTONES[0]).click({force: true, noWaitAfter: true});
    await page.waitForTimeout(300);
    expect(page.posts.length, "salió otro POST antes de tiempo").toBe(1);

    await page.clock.runFor(30000);
    await prendidos(page);

    await guardar(page, BOTONES[1]);
    await esperarPosts(page, 2);
});
