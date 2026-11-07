const {defineConfig, devices} = require("@playwright/test");

const PORT = Number(process.env.PORT) || 4173;

/*
 * Dos proyectos porque el recorte se rompe distinto en cada uno:
 *
 *  - desktop: pantalla ancha, mouse. La vista previa entra al lado de la foto.
 *  - mobile:  pantalla angosta y touch. Es donde vive el caso que motivó todo esto,
 *             la foto vertical de celular con EXIF Orientation=6, y donde el CSS
 *             manda la vista previa abajo (@media max-width:640px).
 *
 * Los mismos tests corren en los dos: el bug de la rotación se ve igual en ambos, pero
 * el del tamaño de letra y el del desborde horizontal sólo se notan con el ancho chico.
 */
module.exports = defineConfig({
    testDir: __dirname,
    testMatch: "**/*.spec.js",
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: 0,
    reporter: process.env.CI ? [["list"], ["html", {open: "never"}]] : [["list"]],

    use: {
        baseURL: "http://127.0.0.1:" + PORT,
        trace: "retain-on-failure",
        screenshot: "only-on-failure",
    },

    projects: [
        {
            name: "desktop",
            use: {...devices["Desktop Chrome"], viewport: {width: 1280, height: 800}},
        },
        {
            // iPhone 13: 390x844, touch, sin mouse. El caso real del rescatista que carga
            // el animal desde el celular con la foto que acaba de sacar.
            name: "mobile",
            use: {...devices["iPhone 13"], browserName: "chromium"},
        },
    ],

    webServer: {
        command: "node server.js",
        url: "http://127.0.0.1:" + PORT + "/",
        cwd: __dirname,
        reuseExistingServer: !process.env.CI,
        stdout: "ignore",
        stderr: "pipe",
    },
});
