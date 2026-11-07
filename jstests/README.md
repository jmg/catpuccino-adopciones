# Tests de navegador del selector de recorte

Prueban en un Chromium de verdad las dos mitades del selector con el que se elige qué
parte de la foto sale en el posteo de Instagram:

- `catus/static/js/crop-widget.js`, el selector en sí (`crop.spec.js`,
  `crop-orientaciones.spec.js`);
- el bloque `<script>` de `catus/templates/animal/edit.html`, que es el que lo cablea al
  formset de fotos (`crop-formset.spec.js`).

Los dos con dos perfiles:

- **desktop**: 1280×800, mouse.
- **mobile**: iPhone 13 (390×844), touch de verdad por CDP.

Los dos perfiles corren los mismos 58 tests. No es redundante: el caso que motivó todo
esto —la foto vertical sacada con el celular— sólo aparece en mobile, y el tamaño de
letra de la vista previa y el desborde horizontal sólo se notan con la pantalla angosta.

## Correr

```bash
cd jstests
npm install                 # una sola vez
npx playwright install chromium   # una sola vez, baja el navegador
npm test                    # los dos perfiles
npm run test:mobile         # sólo el celular
npx playwright test --ui    # modo interactivo, para mirar qué pasa
```

Nada de esto toca el sitio: `jstests/` está fuera de `catus/static/`, así que
`collectstatic` no lo copia, y `deploy.sh` (que es un `git pull` sin instalar nada) lo
ignora. `node_modules/` está en `.gitignore`.

## Cómo está armado

- **`server.js`** sirve los estáticos en las **mismas rutas que producción**
  (`/static/js/crop-widget.js`, `/static/vendor/cropper/…`). Los tests cargan el archivo
  de verdad, no una copia que se puede desincronizar. Sin dependencias: `http` y `fs`.
- **`fixtures/harness.html`** monta el widget copiando el cableado de
  `catus/templates/tools/generarimagen.html`: cuatro inputs con el recorte, un botón que
  abre el selector, y un `onSave` que escribe las fracciones en los inputs. **Si ese
  template cambia cómo llama a `CatusCrop.open()`, hay que actualizar el harness**, o los
  tests van a seguir en verde probando un cableado que ya no existe.
- **`fixtures/harness-formset.html`** es el otro lugar donde se usa el selector: el
  formset de fotos de `animal/edit.html`, con N filas, índices armados a mano y filas que
  se agregan después de cargar la página. Acá el JS **no se copia**: ver
  [El JS del formset sale del template, no de una copia](#el-js-del-formset-sale-del-template-no-de-una-copia).
- **`fixtures/jpeg.js`** arma las fotos en el navegador con canvas y les inserta a mano
  un segmento EXIF APP1 con el `Orientation` que se pida. Así no hay que versionar
  binarios ni depender de Pillow. Van como `data:` URL, que es el camino en el que Cropper
  lee el base64 directo sin XHR: los tests no dependen de la red ni de CORS.

## El JS del formset sale del template, no de una copia

`fixtures/harness-formset.html` **tenía pegado** el bloque `<script>` de
`catus/templates/animal/edit.html`. Se revirtió a mano el arreglo de `updateRemoveAdded`
en el template, se corrió `npx playwright test` y pasaron los 116. Estaban probando el
copy/paste, que nadie había revertido: un test que no se pone en rojo cuando el código se
rompe no está probando ese código.

Ahora el harness pide el JS con un `<script src="/template-js/animal-edit.js">` y quien lo
sirve es `crop-formset.spec.js`, con un `page.route()` que:

1. lee `catus/templates/animal/edit.html` del disco,
2. recorta su único `<script>` sin atributos (los demás son `<script src=…>`),
3. reemplaza la sintaxis de Django que hay adentro, y
4. lo devuelve como `text/javascript`.

**Lo único que se sustituye hoy es `{{ csrf_token }}`**, por el string `csrf-de-prueba`.
Es el token que el template manda en el POST de `/animal/validatename/`, que en el harness
no se llama nunca. La lista vive en `RESUELTO_POR_DJANGO`, en `crop-formset.spec.js`, y si
aparece otra expresión el extractor **corta con un error** en vez de servir JS mal armado:
un `{{ … }}` suelto es un `SyntaxError` que dejaría la página sin enganchar nada y los
tests en rojo sin decir por qué. Si agregás una, agregala también acá para que se sepa qué
se está sustituyendo.

Lo que el harness sí sigue teniendo copiado es el **HTML** alrededor: los ids del formset,
el molde `#empty_form` y dónde cuelga el `<img>` de la foto ya cargada. Si `edit.html`
cambia eso, hay que actualizar el harness. Y como el JS del template arranca llamando a
`tinymce.init()` —tinymce se sirve de `/static/js/tinymce/`, que no está en el repo—, el
harness le deja un doble vacío; sin eso el `ReferenceError` corta el `$(document).ready()`
antes de llegar al formset.

Efecto lateral esperable: abrir `fixtures/harness-formset.html` a mano en el navegador da
una pantalla muerta, sin botones de recorte. El JS lo pone el test.

> **Pendiente, prolijo:** esto le corresponde más a `server.js`, que ya sirve archivos del
> repo. Sería una rama más en `resolver()`: `/template-js/animal-edit.js` → recortar el
> `<script>` de `catus/templates/animal/edit.html`, sustituir `{{ csrf_token }}`, servirlo
> como `.js`. Está del lado del test porque `server.js` lo estaba tocando otro cambio al
> mismo tiempo. Si se muda, **el harness no se entera**: sigue pidiendo la misma URL, y lo
> que se saca de `crop-formset.spec.js` son `jsDelTemplate()` y el `page.route()`.

## Por qué hace falta EXIF de verdad

El bug que estos tests cuidan sólo aparece con una foto rotada. Cropper corre con
`checkOrientation` (default), y entonces:

1. lee el EXIF por su cuenta,
2. le pone `image-orientation: 0deg !important` al clon para que el navegador **no**
   auto-oriente, y
3. aplica la rotación él, guardándola en `imageData.rotate`.

Resultado: `getData()` devuelve el cuadro medido en el marco **rotado** (el que ve la
persona) mientras que `naturalWidth`/`naturalHeight` siguen siendo los del archivo crudo.
Dividir por el lado equivocado hacía que el rescatista eligiera la cara del gato y se
publicara otra parte. Una foto de 4032×3024 con `Orientation=6` se ve como 3024×4032.

## Lo que cubre, comprobado por mutación

Cada arreglo se revirtió a mano y se confirmó que algún test lo agarra:

| Se rompe esto en `crop-widget.js` | Lo detecta |
|---|---|
| `marcoVisible` ignora la rotación EXIF | 4 tests (los dos perfiles × 2 casos) |
| se saca el `disabled` inicial de "Guardar recorte" | 2 |
| el `font-size` de la vista previa vuelve a ir en `%` | 4 |
| se saca el guard `if (!cropper) return` | 2 |

Y lo mismo con el JS del formset, que hasta que dejó de ser copia no se podía comprobar:

| Se rompe esto en `animal/edit.html` | Lo detecta |
|---|---|
| `updateRemoveAdded` vuelve a las dos `.prev().remove()` | 4 (los dos perfiles × 2 tests de "borrar una fila recién agregada") |
| `field(index, name)` ignora el índice y apunta siempre a la fila 0 | los 20 |

## Lo que NO cubre

El clamp de `toFractions` (encerrar el cuadro dentro de la foto) **no tiene test**, y no
es un descuido: con `viewMode: 1` Cropper llama a `limitCropBox` y ya mantiene el cuadro
adentro, así que desde la interfaz no hay forma de llegar a ese caso. Es código
defensivo. Si algún día se cambia `viewMode`, ese clamp pasa a ser alcanzable y conviene
escribirle un test.

Tampoco se prueba acá el `{% localize off %}` de los templates: eso es del lado de Django
—es el valor que el server **escribe** en el input— y vive en la suite de Python. Lo que
sí se prueba acá es la otra mitad: que el JS escriba las fracciones con punto y no con
coma.
