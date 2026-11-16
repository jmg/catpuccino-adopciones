/*
 * Las librerías de base.html andan juntas: jQuery 3.7.1, Bootstrap 4.6.2 (sin el bundle,
 * o sea sin Popper) y los plugins que el sitio carga encima.
 *
 * Se subieron desde jQuery 3.4.1 y Bootstrap 4.3.1. Bootstrap no trae Popper en este
 * archivo: el único desplegable del sitio está en la barra de navegación, donde Bootstrap no
 * lo usa, y el panel carga el Popper 2 de tippy después, que no le sirve a Bootstrap 4. Si
 * algún día aparece un desplegable fuera de la barra, o un tooltip de Bootstrap, falla acá.
 *
 *   cd jstests && npx playwright test vendor.spec.js
 */
const {test, expect} = require("@playwright/test");

test.beforeEach(async ({page}) => {
    const errores = [];
    page.on("pageerror", (error) => errores.push(String(error)));
    page.errores = errores;
    await page.goto("/harness-vendor.html");
});

test.afterEach(async ({page}) => {
    expect(page.errores, "errores de JS en la página").toEqual([]);
});

test("cargan las versiones que se vendorizaron", async ({page}) => {

    const versiones = await page.evaluate(() => ({
        jquery: window.jQuery.fn.jquery,
        bootstrap: window.jQuery.fn.collapse.Constructor.VERSION,
    }));

    expect(versiones).toEqual({jquery: "3.7.1", bootstrap: "4.6.2"});
});

test("el menú de la barra se abre y el desplegable de formularios también", async ({page}) => {

    const toggler = page.locator(".navbar-toggler");
    if (await toggler.isVisible()) {
        await toggler.click();
        await expect(page.locator("#navbarResponsive")).toHaveClass(/show/);
    }

    await page.locator("#navbarDropdown").click();

    await expect(page.locator("#mainNav .dropdown-menu")).toBeVisible();
    await expect(page.locator("#navbarDropdown")).toHaveAttribute("aria-expanded", "true");
});

test("el desplegable sigue andando con el Popper 2 de tippy cargado (el panel)", async ({page}) => {

    // accounts/profile.html carga @popperjs/core 2 después de Bootstrap: deja un Popper
    // global que Bootstrap 4 no sabe usar
    await page.evaluate(() => { window.Popper = {createPopper: function () {}}; });

    const toggler = page.locator(".navbar-toggler");
    if (await toggler.isVisible()) {
        await toggler.click();
    }
    await page.locator("#navbarDropdown").click();

    await expect(page.locator("#mainNav .dropdown-menu")).toBeVisible();
});

test("las pestañas del panel cambian de sección", async ({page}) => {

    await page.locator("#forms-tab-link").click();

    await expect(page.locator("#forms-tab")).toBeVisible();
    await expect(page.locator("#animales-tab")).toBeHidden();
    await expect(page.locator("#forms-tab-link")).toHaveAttribute("aria-selected", "true");
});

test("el carrusel no pasa solo y avanza con la flecha", async ({page}) => {

    const activa = page.locator("#animalCarrousel-1 .carousel-item.active img");
    await expect(activa).toHaveAttribute("alt", "1a");

    await page.waitForTimeout(1500);
    await expect(activa).toHaveAttribute("alt", "1a");

    await page.locator("#animalCarrousel-1 .carousel-control-next").click();
    await expect(activa).toHaveAttribute("alt", "1b");
});

test("un modal abre y cierra", async ({page}) => {

    await page.locator("#abrir-modal").click();
    await expect(page.locator("#modal")).toBeVisible();

    await page.locator("#modal [data-dismiss=modal]").click();
    await expect(page.locator("#modal")).toBeHidden();
});

test("el slider de fotos del formulario arranca", async ({page}) => {

    await page.evaluate(() => { window.jQuery("#slider").lightSlider({item: 1, auto: false, loop: true}); });

    await expect(page.locator(".lSSlideOuter")).toHaveCount(1);
});

test("alertify y SweetAlert muestran sus avisos", async ({page}) => {

    await page.evaluate(() => {
        window.alertify.success("Guardado");
        window.Swal.fire({title: "¿Seguro?"});
    });

    await expect(page.locator(".ajs-message")).toContainText("Guardado");
    await expect(page.locator(".swal2-popup")).toContainText("¿Seguro?");
});
