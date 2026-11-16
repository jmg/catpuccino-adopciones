/*
 * El buscador y los filtros de la portada (index.js: _filter, filterAnimals y vecinos).
 *
 * Lo que tienen que hacer, y por qué:
 *
 *  - Encontrar sin importar tildes ni mayúsculas: "Lanus" no encontraba "Lanús", y desde el
 *    celular casi nadie escribe la tilde.
 *  - Buscar también en el sexo y la edad, no solo en el nombre y la zona.
 *  - Filtrar por sexo (una camada, "Macho y Hembra", entra en los dos) y por edad, con la
 *    edad en meses que estima el server: Cachorros, menos de 12; Adultos, 12 o más. Los de
 *    edad desconocida solo aparecen con los filtros de edad apagados.
 *  - Dejar la búsqueda en la URL para poder compartirla, y aplicarla al abrir ese link.
 *  - Sin resultados, decir que puede que ya esté reservado o adoptado, y dejar limpiar todo.
 *
 * El JS es el de verdad, sobre fixtures/harness-filtros.html.
 *
 *   cd jstests && npx playwright test filtros.spec.js
 */
const {test, expect} = require("@playwright/test");

async function abrir(page, query) {
    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;
    await page.goto("/harness-filtros.html" + (query || ""));
}

// los ids de las tarjetas que se ven, en orden
function visibles(page) {
    return page.locator("#animal-list > .animal-card").evaluateAll((tarjetas) =>
        tarjetas.filter((t) => t.getClientRects().length > 0).map((t) => t.getAttribute("data-id")));
}

async function veo(page, ids) {
    await expect.poll(() => visibles(page)).toEqual(ids);
}

function boton(page, selector) {
    return page.locator(".search-container " + selector);
}

test("encuentra sin importar tildes ni mayúsculas", async ({page}) => {

    await abrir(page);

    await page.locator("#filter-zone").fill("lanus");
    await veo(page, ["1", "2", "4"]);

    await page.locator("#filter-zone").fill("LANÚS");
    await veo(page, ["1", "2", "4"]);

    await page.locator("#filter-zone").fill("nono");
    await veo(page, ["6"]);

    expect(page.errores).toEqual([]);
});

test("las zonas se sugieren sin importar la tilde, una sola vez", async ({page}) => {

    await abrir(page);

    // "Lanús" y "LANUS" son la misma zona: queda la primera forma
    const zonas = await page.evaluate(() => zonasParaSugerir("Lanús||LANUS||Lanus||Morón").map((z) => z.value));
    expect(zonas).toEqual(["Lanús", "Morón"]);

    await page.locator("#filter-zone").pressSequentially("moron");

    const sugerencias = page.locator(".autocomplete-suggestion");
    await expect(sugerencias).toHaveCount(1);
    expect(await sugerencias.first().innerHTML()).toBe("<strong>Morón</strong>");
    await veo(page, ["6"]);

    expect(page.errores).toEqual([]);
});

test("busca también en el sexo y en la edad", async ({page}) => {

    await abrir(page);

    // "Macho y Hembra" es una camada: es hembra también
    await page.locator("#filter-zone").fill("hembra");
    await veo(page, ["1", "3", "5"]);

    await page.locator("#filter-zone").fill("dias");
    await veo(page, ["3"]);

    // cada palabra en algún lado: los machos de Lanús
    await page.locator("#filter-zone").fill("macho lanus");
    await veo(page, ["2", "4"]);

    await page.locator("#filter-zone").fill("cachorro");
    await veo(page, ["1", "3"]);

    expect(page.errores).toEqual([]);
});

test("Machos y Hembras: una camada entra en los dos, y tocar el prendido lo apaga", async ({page}) => {

    await abrir(page);
    const machos = boton(page, "button[data-sexo=M]");
    const hembras = boton(page, "button[data-sexo=H]");

    await machos.click();
    await veo(page, ["2", "3", "4"]);
    await expect(machos).toHaveAttribute("aria-pressed", "true");

    await hembras.click();
    await veo(page, ["1", "3", "5"]);
    await expect(machos).toHaveAttribute("aria-pressed", "false");
    await expect(hembras).toHaveAttribute("aria-pressed", "true");

    await hembras.click();
    await veo(page, ["1", "2", "3", "4", "5", "6"]);
    await expect(hembras).toHaveAttribute("aria-pressed", "false");

    expect(page.errores).toEqual([]);
});

test("Cachorros y Adultos: 12 meses ya es adulto, y la edad desconocida no entra en ninguno", async ({page}) => {

    await abrir(page);

    await boton(page, "button[data-edad=cachorro]").click();
    await veo(page, ["1", "3"]);

    await boton(page, "button[data-edad=adulto]").click();
    await veo(page, ["2", "4"]);
    await expect(boton(page, "button[data-edad=cachorro]")).toHaveAttribute("aria-pressed", "false");

    await boton(page, "button[data-edad=adulto]").click();
    await veo(page, ["1", "2", "3", "4", "5", "6"]);

    expect(page.errores).toEqual([]);
});

test("se combinan con el tipo y el contador dice cuántos quedan", async ({page}) => {

    await abrir(page);

    await boton(page, "button[data-tipo=P]").click();
    await boton(page, "button[data-sexo=H]").click();

    await veo(page, ["5"]);
    await expect(page.locator("#resultados-cuenta")).toHaveText("1 de 6 en adopción");
    await expect(page.locator("#resultados-cuenta")).toHaveAttribute("aria-live", "polite");

    expect(page.errores).toEqual([]);
});

test("sin resultados lo dice, y «Limpiar la búsqueda» vuelve a mostrar todos", async ({page}) => {

    await abrir(page);
    await boton(page, "button[data-tipo=P]").click();
    await boton(page, "button[data-sexo=M]").click();
    await page.locator("#filter-zone").fill("zzz");

    await veo(page, []);
    await expect(page.locator("#sin-resultados")).toBeVisible();
    await expect(page.locator("#sin-resultados")).toContainText("reservado o adoptado");

    await page.locator("#ver-todos").click();

    await veo(page, ["1", "2", "3", "4", "5", "6"]);
    await expect(page.locator("#sin-resultados")).toBeHidden();
    await expect(page.locator("#filter-zone")).toHaveValue("");
    await expect(boton(page, "button[data-sexo=M]")).toHaveAttribute("aria-pressed", "false");
    await expect(boton(page, "button[data-tipo=all]")).toHaveAttribute("aria-pressed", "true");
    await expect(page).toHaveURL(/\/harness-filtros\.html$/);

    expect(page.errores).toEqual([]);
});

test("la búsqueda queda en la URL, sin sumar entradas al historial ni perder lo demás", async ({page}) => {

    await abrir(page, "?fbclid=abc");
    const historial = await page.evaluate(() => history.length);

    // un nombre y no una zona: la lista de zonas sugeridas taparía los botones en el celular
    await page.locator("#filter-zone").fill("luna llena");
    await boton(page, "button[data-tipo=P]").click();
    await boton(page, "button[data-sexo=H]").click();
    await boton(page, "button[data-edad=cachorro]").click();

    await expect(page).toHaveURL(/[?&]buscar=luna\+llena(&|$)/);
    await expect(page).toHaveURL(/[?&]tipo=perros(&|$)/);
    await expect(page).toHaveURL(/[?&]sexo=hembras(&|$)/);
    await expect(page).toHaveURL(/[?&]edad=cachorros(&|$)/);
    await expect(page).toHaveURL(/[?&]fbclid=abc(&|$)/);
    expect(await page.evaluate(() => history.length)).toBe(historial);

    // apagar un filtro lo saca de la URL
    await boton(page, "button[data-edad=cachorro]").click();
    await expect(page).not.toHaveURL(/edad=/);

    expect(page.errores).toEqual([]);
});

test("un link con la búsqueda abre la portada ya filtrada", async ({page}) => {

    await abrir(page, "?buscar=Lan%C3%BAs&tipo=perros&edad=adultos");

    await expect(page.locator("#filter-zone")).toHaveValue("Lanús");
    await expect(boton(page, "button[data-tipo=P]")).toHaveAttribute("aria-pressed", "true");
    await expect(boton(page, "button[data-tipo=all]")).toHaveAttribute("aria-pressed", "false");
    await expect(boton(page, "button[data-edad=adulto]")).toHaveAttribute("aria-pressed", "true");
    await veo(page, ["4"]);

    expect(page.errores).toEqual([]);
});

test("el link acepta singular y mayúsculas, e ignora lo que no conoce", async ({page}) => {

    await abrir(page, "?tipo=Gato&sexo=macho");
    await veo(page, ["2", "3"]);

    await abrir(page, "?tipo=loros&edad=viejos");
    await veo(page, ["1", "2", "3", "4", "5", "6"]);
    await expect(boton(page, "button[data-tipo=all]")).toHaveAttribute("aria-pressed", "true");

    expect(page.errores).toEqual([]);
});
