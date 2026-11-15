/*
 * El buscador "Por zona o nombre" de la portada no puede ejecutar lo que un rescatista
 * escribió como zona, ni romperse con una zona o un nombre que parecen números.
 *
 * Las sugerencias son las zonas de los animales publicados. jquery.autocomplete 1.4.11 las
 * mete con .html() y, con la caja vacía (minChars: 0), sin escapar: una zona
 * `<img src=x onerror=…>` corría en el navegador de cualquiera que tocara la caja, el equipo
 * logueado incluido (revisión de la semana del 2026-11-12). Desde la pasada de diseño la
 * lista ya no se abre con la caja vacía (minChars: 1): en el celular tapaba los filtros y
 * los animales. Si alguien vuelve a minChars: 0, el primer test avisa. Y jQuery .data() convierte
 * "1636" en número y "null" en null, con lo que toLowerCase() tiraba un TypeError y el
 * buscador y el filtro de gatos/perros dejaban de hacer nada.
 *
 * El JS es el de verdad (catus/static/js/index.js y el plugin del sitio), sobre
 * fixtures/harness-buscador.html.
 *
 *   cd jstests && npx playwright test buscador.spec.js
 */
const {test, expect} = require("@playwright/test");

test.beforeEach(async ({page}) => {
    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;
    await page.goto("/harness-buscador.html");
});

test("con la caja vacía no se abre la lista de zonas", async ({page}) => {

    await page.locator("#filter-zone").click();

    await page.waitForTimeout(300);
    await expect(page.locator(".autocomplete-suggestion")).toHaveCount(0);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
    expect(page.errores).toEqual([]);
});

test("una zona con HTML se muestra como texto y no corre", async ({page}) => {

    await page.locator("#filter-zone").pressSequentially("<");

    const sugerencias = page.locator(".autocomplete-suggestion");
    await expect(sugerencias).toHaveCount(1);
    await expect(page.locator(".autocomplete-suggestions img")).toHaveCount(0);
    await expect(sugerencias.filter({hasText: "<img src=x onerror="})).toHaveCount(1);

    await page.waitForTimeout(300);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
    expect(page.errores).toEqual([]);
});

test("la misma zona escrita de varias formas se sugiere una sola vez", async ({page}) => {

    // las zonas las escribe cada rescatista: en producción había "BELGRANO" y "Belgrano",
    // y una que era "....."
    const zonas = await page.evaluate(() => zonasParaSugerir("Belgrano||BELGRANO|| belgrano ||.....||Lanús||San  Isidro").map((z) => z.value));

    expect(zonas).toEqual(["Belgrano", "Lanús", "San Isidro"]);
});

test("escribiendo, la coincidencia se resalta y lo demás sigue escapado", async ({page}) => {

    await page.locator("#filter-zone").pressSequentially("im");

    const html = await page.locator(".autocomplete-suggestions").innerHTML();
    expect(html).toContain("&lt;<strong>im</strong>g src=x onerror=");
    await expect(page.locator(".autocomplete-suggestions img")).toHaveCount(0);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
    expect(page.errores).toEqual([]);
});

test("zonas y nombres que parecen números no rompen el buscador ni el filtro", async ({page}) => {

    await page.locator("#filter-zone").pressSequentially("163");
    await expect(page.locator('.animal-card[data-id="1"]')).not.toHaveClass(/no-coincide/);
    await expect(page.locator('.animal-card[data-id="2"]')).toHaveClass(/no-coincide/);

    await page.locator("#filter-zone").fill("");
    await page.selectOption("#filter-type", "P");
    await expect(page.locator('.animal-card[data-id="2"]')).not.toHaveClass(/no-coincide/);
    await expect(page.locator('.animal-card[data-id="1"]')).toHaveClass(/no-coincide/);

    expect(page.errores).toEqual([]);
});
