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

// el intervalo de initializeImages (3000 ms) más los 500 ms que Bootstrap espera después
// de un toque, con margen
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
