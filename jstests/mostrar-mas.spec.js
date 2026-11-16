/*
 * "Mostrar más" tiene que estar en toda descripción que no entra en sus tres renglones,
 * también en las tarjetas que aparecen después de cargar la página.
 *
 * modern-effects.js decidía al cargar, una sola vez, a qué tarjetas ponerles el link,
 * midiendo si el texto desbordaba. Pero de la 11 en adelante la portada las tiene ocultas
 * (modern.css, #animal-list.paginada-inicial; después paginar(), en index.js), y una
 * tarjeta oculta mide 0: no desborda, y se le sacaba el link para siempre. Después de
 * "Cargar más", o de buscar un nombre que estaba más abajo, aparecían con la descripción
 * cortada y sin forma de abrirla. Ahora se mide cuando la tarjeta se ve
 * (revisarMostrarMas, en index.js).
 *
 * El JS y el CSS son los de verdad, sobre fixtures/harness-mostrar-mas.html.
 *
 *   cd jstests && npx playwright test mostrar-mas.spec.js
 */
const {test, expect} = require("@playwright/test");

test.beforeEach(async ({page}) => {
    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;
    await page.goto("/harness-mostrar-mas.html");
    await expect(page.locator('.animal-card[data-id="1"]')).toBeVisible();
});

function tarjeta(page, id) {
    return page.locator('.animal-card[data-id="' + id + '"]');
}

function mostrarMas(page, id) {
    return tarjeta(page, id).locator(".show-more-a");
}

test("al cargar, la descripción larga tiene el link y la corta no", async ({page}) => {

    await expect(mostrarMas(page, 1)).toBeVisible();
    await expect(mostrarMas(page, 2)).toBeHidden();
    await expect(tarjeta(page, 17)).toBeHidden();
    expect(page.errores).toEqual([]);
});

test("después de «Cargar más», las tarjetas que aparecen tienen su «Mostrar más»", async ({page}) => {

    await page.locator("#cargar-mas").click();

    await expect(tarjeta(page, 17)).toBeVisible();
    await expect(mostrarMas(page, 17)).toBeVisible();
    // la corta, que entra entera, sigue sin link
    await expect(mostrarMas(page, 18)).toBeHidden();
    expect(page.errores).toEqual([]);
});

test("el link de una tarjeta que apareció después abre y cierra la descripción", async ({page}) => {

    await page.locator("#cargar-mas").click();
    const texto = tarjeta(page, 17).locator(".show-more-text");
    const recortada = () => texto.evaluate((el) => el.scrollHeight > el.clientHeight + 1);
    expect(await recortada()).toBe(true);

    await mostrarMas(page, 17).click();

    await expect(mostrarMas(page, 17)).toHaveText("Mostrar menos");
    expect(await recortada()).toBe(false);

    await mostrarMas(page, 17).click();

    // cerrada vuelve a estar recortada, y el link sigue para abrirla de nuevo
    await expect(mostrarMas(page, 17)).toHaveText("Mostrar más");
    await expect(mostrarMas(page, 17)).toBeVisible();
    expect(await recortada()).toBe(true);
    expect(page.errores).toEqual([]);
});

test("buscando un nombre que estaba más abajo, su tarjeta tiene el link", async ({page}) => {

    await page.locator("#filter-zone").fill("Diecisiete");

    await expect(tarjeta(page, 17)).toBeVisible();
    await expect(tarjeta(page, 1)).toBeHidden();
    await expect(mostrarMas(page, 17)).toBeVisible();
    expect(page.errores).toEqual([]);
});
