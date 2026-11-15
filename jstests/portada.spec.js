/*
 * Reordenar la portada no puede dejar temporizadores de carruseles ya liberados.
 *
 * "Ordenar" (#filter-sort) vuelve a armar los carruseles: initializeImages() hace dispose()
 * de los viejos y crea nuevos. Pero dispose() de Bootstrap 4 no frena sus temporizadores:
 * ni el setInterval que arranca al pasarle el mouse a un carrusel, ni el cycle() que un
 * toque programa para 3,5 s después. Esos temporizadores le caían después a un carrusel con
 * todo en null, y el navegador tiraba un TypeError (ADOPCIONES-3WS40, 2026-11-11, un
 * celular Android que tocó un carrusel y después cambió el orden).
 *
 * El JS es el de verdad (catus/static/js/index.js con jQuery y Bootstrap del sitio), sobre
 * fixtures/harness-portada.html.
 *
 *   cd jstests && npx playwright test portada.spec.js
 */
const {test, expect} = require("@playwright/test");

// Lo que tardaban en dispararse los temporizadores del carrusel viejo: los 3000 ms del
// intervalo que tenía initializeImages más los 500 ms que Bootstrap espera después de un
// toque, con margen. Los carruseles ya no pasan solos (interval: false), pero el toque
// sigue programando su cycle(): la espera es la misma.
const ESPERA_MS = 4500;

test.beforeEach(async ({page}) => {
    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;
    await page.goto("/harness-portada.html");
    await expect(page.locator("#animalCarrousel-1 .carousel-item.active")).toBeVisible();
});

test("después de tocar un carrusel, reordenar no deja errores", async ({page}, testInfo) => {

    // En la compu el intervalo que queda vivo llama a nextWhenVisible(), que con el elemento
    // en null no hace nada: se pierde el temporizador pero no hay error que mirar. El error
    // que llega a Jentry es el del toque, y ese sólo existe con pantalla táctil.
    test.skip(!testInfo.project.use.hasTouch, "el error del temporizador del toque sólo existe con touch");

    // un toque, como el del usuario de 3WS40
    await page.locator("#animalCarrousel-1 .carousel-inner").tap();

    await page.selectOption("#filter-sort", "desc");
    await expect(page.locator("#animal-list .animal-card").first()).toHaveAttribute("data-id", "2");

    await page.waitForTimeout(ESPERA_MS);

    expect(page.errores, "quedaron temporizadores del carrusel viejo").toEqual([]);
});

test("los carruseles nuevos siguen andando después de reordenar", async ({page}) => {

    await page.selectOption("#filter-sort", "asc");
    await page.selectOption("#filter-sort", "desc");

    await page.locator("#animalCarrousel-2 .carousel-control-next").click();
    await expect(page.locator("#animalCarrousel-2 .carousel-item.active img")).toHaveAttribute("alt", "2b");

    expect(page.errores).toEqual([]);
});

test("las fotos no pasan solas", async ({page}) => {

    // Pasaban cada 3 segundos, todas las fichas a la vez y sin forma de frenarlas, y en un
    // minuto el celular bajaba 25 fotos que nadie había pedido.
    await page.waitForTimeout(ESPERA_MS);

    await expect(page.locator("#animalCarrousel-1 .carousel-item.active img")).toHaveAttribute("alt", "1a");
    await expect(page.locator("#animalCarrousel-2 .carousel-item.active img")).toHaveAttribute("alt", "2a");
    expect(page.errores).toEqual([]);
});

test("el contador dice qué foto se está viendo", async ({page}) => {

    await expect(page.locator("#animalCarrousel-1 .fotos-cuenta")).toHaveText("1 / 2");

    await page.locator("#animalCarrousel-1 .carousel-control-next").click();

    await expect(page.locator("#animalCarrousel-1 .fotos-cuenta")).toHaveText("2 / 2");
    await expect(page.locator("#animalCarrousel-2 .fotos-cuenta")).toHaveText("1 / 2");
});

test("elegir de nuevo el primer orden vuelve al orden en que llegó la página", async ({page}) => {

    // antes la primera opción del desplegable no hacía nada: después de reordenar no había
    // cómo volver
    await page.selectOption("#filter-sort", "desc");
    await expect(page.locator("#animal-list .animal-card").first()).toHaveAttribute("data-id", "2");

    await page.selectOption("#filter-sort", "");
    await expect(page.locator("#animal-list .animal-card").first()).toHaveAttribute("data-id", "1");

    expect(page.errores).toEqual([]);
});
