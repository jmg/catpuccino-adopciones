(function(d){

  d.alert= function(message, title, source) {
      alertify.set('notifier','position', 'top-right');
      alertify.error(message);
  };

  d.warning= function(message, title, source){
      alertify.set('notifier','position', 'top-right');
      alertify.warning(message);
  };

  d.info= function(message, title, source){
      alertify.set('notifier','position', 'top-right');
      alertify.success(message);
  };

  var picker = [];
  var currentYear = new Date().getFullYear();

  $('.date-picker').each(function(idx) {
      picker[idx] = new Pikaday({
        field: $(this)[0],
        yearRange: [1920, currentYear+1],
        format: 'DD/MM/YYYY',
      });
  });

  $('input').not('.form-input').removeAttr('placeholder');
  $('textarea').removeAttr('placeholder');

})(jQuery);

var setCookie = function(name, value, days) {

    var expires = "";
    if (days) {
        var date = new Date();
        date.setTime(date.getTime() + (days*24*60*60*1000));
        expires = "; expires=" + date.toUTCString();
    }
    document.cookie = name + "=" + (value || "")  + expires + "; path=/";
}

var getCookie = function(name) {

    var nameEQ = name + "=";
    var ca = document.cookie.split(';');
    for(var i=0;i < ca.length;i++) {
        var c = ca[i];
        while (c.charAt(0)==' ') c = c.substring(1,c.length);
        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length,c.length);
    }
    return null;
}

var sliders = [];

function initializeImages() {

  //dispose() de Bootstrap 4 no frena los temporizadores del carrusel: deja corriendo el
  //setInterval que arranca al pasarle el mouse y el cycle() que programa un toque para
  //3,5 s después. Al reordenar la portada esos temporizadores le caían a un carrusel ya
  //liberado (ADOPCIONES-3WS40: "Cannot read properties of null (reading 'interval')").
  sliders.map(function(slider) {
    slider.pause()
    clearTimeout(slider.touchTimeout)
    slider.dispose()
  })

  sliders = []

  $('.carousel').each(function(idx, el) {

    //con una sola foto no hay nada que pasar
    if ($(el).find('.carousel-item').length < 2) {
      return
    }

    //interval false: las fotos pasan cuando la persona toca la flecha o desliza. Antes
    //pasaban solas cada 3 segundos, todas las fichas a la vez: no había cómo frenarlas
    //y en un minuto el celular bajaba 25 fotos que nadie había pedido.
    var slider = new bootstrap.Carousel(el, {interval: false })
    sliders.push(slider)
  })

  makeImageFullSize();
}

// "2 / 7" sobre la foto: cuál se está viendo
$(document).on("slid.bs.carousel", ".animalCarrousel", function(e) {
  var cuenta = $(this).find(".fotos-cuenta")
  if (cuenta.length && typeof e.to === "number") {
    cuenta.text((e.to + 1) + " / " + $(this).find(".carousel-item").length)
  }
})

// La foto de la tarjeta es un link a la ficha: deslizarla para pasar a la siguiente no es
// tocarla. Si entre que se apoyó y se soltó el dedo (o el mouse) se movió, no se abre.
var inicioSobreLaFoto = null;

$(document).on("pointerdown", ".animalCarrousel", function(e) {
  inicioSobreLaFoto = {x: e.clientX, y: e.clientY}
})

$(document).on("click", ".animalCarrousel a.foto-ficha", function(e) {
  var inicio = inicioSobreLaFoto
  inicioSobreLaFoto = null
  if (inicio && typeof e.clientX === "number" && Math.abs(e.clientX - inicio.x) > 10) {
    e.preventDefault()
  }
})

// Las flechas del carrusel y el desplegable del menú son <a role="button">: un botón se
// activa también con la barra espaciadora, que en un link solo baja la página.
$(document).on("keydown", "a[role=button]", function(e) {
  if (e.key === " " || e.key === "Spacebar") {
    e.preventDefault()
    this.click()
  }
})

// modern-effects.js la reemplaza por una que además vuelve a la tarjeta al cerrar; las dos
// abren con .expanded, que es lo que mira revisarUnMostrarMas()
function showMore(el) {
  var link = $(el)
  var abierta = link.parent().prev().toggleClass("expanded").hasClass("expanded")
  link.text(abierta ? "Mostrar menos" : "Mostrar más")
}

function mobileCheck() {
  var check = false;
  (function(a){if(/(android|bb\d+|meego).+mobile|avantgo|bada\/|blackberry|blazer|compal|elaine|fennec|hiptop|iemobile|ip(hone|od)|iris|kindle|lge |maemo|midp|mmp|mobile.+firefox|netfront|opera m(ob|in)i|palm( os)?|phone|p(ixi|re)\/|plucker|pocket|psp|series(4|6)0|symbian|treo|up\.(browser|link)|vodafone|wap|windows ce|xda|xiino/i.test(a)||/1207|6310|6590|3gso|4thp|50[1-6]i|770s|802s|a wa|abac|ac(er|oo|s\-)|ai(ko|rn)|al(av|ca|co)|amoi|an(ex|ny|yw)|aptu|ar(ch|go)|as(te|us)|attw|au(di|\-m|r |s )|avan|be(ck|ll|nq)|bi(lb|rd)|bl(ac|az)|br(e|v)w|bumb|bw\-(n|u)|c55\/|capi|ccwa|cdm\-|cell|chtm|cldc|cmd\-|co(mp|nd)|craw|da(it|ll|ng)|dbte|dc\-s|devi|dica|dmob|do(c|p)o|ds(12|\-d)|el(49|ai)|em(l2|ul)|er(ic|k0)|esl8|ez([4-7]0|os|wa|ze)|fetc|fly(\-|_)|g1 u|g560|gene|gf\-5|g\-mo|go(\.w|od)|gr(ad|un)|haie|hcit|hd\-(m|p|t)|hei\-|hi(pt|ta)|hp( i|ip)|hs\-c|ht(c(\-| |_|a|g|p|s|t)|tp)|hu(aw|tc)|i\-(20|go|ma)|i230|iac( |\-|\/)|ibro|idea|ig01|ikom|im1k|inno|ipaq|iris|ja(t|v)a|jbro|jemu|jigs|kddi|keji|kgt( |\/)|klon|kpt |kwc\-|kyo(c|k)|le(no|xi)|lg( g|\/(k|l|u)|50|54|\-[a-w])|libw|lynx|m1\-w|m3ga|m50\/|ma(te|ui|xo)|mc(01|21|ca)|m\-cr|me(rc|ri)|mi(o8|oa|ts)|mmef|mo(01|02|bi|de|do|t(\-| |o|v)|zz)|mt(50|p1|v )|mwbp|mywa|n10[0-2]|n20[2-3]|n30(0|2)|n50(0|2|5)|n7(0(0|1)|10)|ne((c|m)\-|on|tf|wf|wg|wt)|nok(6|i)|nzph|o2im|op(ti|wv)|oran|owg1|p800|pan(a|d|t)|pdxg|pg(13|\-([1-8]|c))|phil|pire|pl(ay|uc)|pn\-2|po(ck|rt|se)|prox|psio|pt\-g|qa\-a|qc(07|12|21|32|60|\-[2-7]|i\-)|qtek|r380|r600|raks|rim9|ro(ve|zo)|s55\/|sa(ge|ma|mm|ms|ny|va)|sc(01|h\-|oo|p\-)|sdk\/|se(c(\-|0|1)|47|mc|nd|ri)|sgh\-|shar|sie(\-|m)|sk\-0|sl(45|id)|sm(al|ar|b3|it|t5)|so(ft|ny)|sp(01|h\-|v\-|v )|sy(01|mb)|t2(18|50)|t6(00|10|18)|ta(gt|lk)|tcl\-|tdg\-|tel(i|m)|tim\-|t\-mo|to(pl|sh)|ts(70|m\-|m3|m5)|tx\-9|up(\.b|g1|si)|utst|v400|v750|veri|vi(rg|te)|vk(40|5[0-3]|\-v)|vm40|voda|vulc|vx(52|53|60|61|70|80|81|83|85|98)|w3c(\-| )|webc|whit|wi(g |nc|nw)|wmlb|wonu|x700|yas\-|your|zeto|zte\-/i.test(a.substr(0,4))) check = true;})(navigator.userAgent||navigator.vendor||window.opera);
  return check;
};

// Qué fotos se pueden ampliar. El clic se escucha una sola vez, en el documento: la
// portada vuelve a llamar a esta función cada vez que se reordena.
function makeImageFullSize() {

    var classes = "img[data-enlargable]";
    if (mobileCheck() === false) {
      classes += ",img[data-enlargable-if-not-mobile]";
    }

    $(classes).addClass('img-enlargable');
}

function cerrarFotoAmpliada() {

    var visor = $("#foto-ampliada");
    if (!visor.length) {
      return;
    }

    var volverA = visor.data("volverA");
    visor.remove();
    $(document).off("keydown.fotoAmpliada");
    resetZoom();

    if (volverA && volverA.focus) {
      volverA.focus();
    }
}

$(document).on("click", "img.img-enlargable", function() {

    cerrarFotoAmpliada();

    var visor = $('<div id="foto-ampliada" class="foto-ampliada" role="dialog" aria-modal="true"></div>')
      .attr("aria-label", this.alt ? "Foto de " + this.alt : "Foto ampliada");

    $("<img>").attr({src: this.src, alt: this.alt || ""}).appendTo(visor);
    var cerrar = $('<button type="button" class="foto-ampliada-cerrar" aria-label="Cerrar la foto"><i class="fa fa-times" aria-hidden="true"></i></button>').appendTo(visor);

    //se cierra tocando en cualquier lado, con la × o con Escape
    visor.data("volverA", document.activeElement).on("click", cerrarFotoAmpliada).appendTo("body");
    $(document).on("keydown.fotoAmpliada", function(e) {
      if (e.key === "Escape" || e.key === "Esc") {
        cerrarFotoAmpliada();
      }
    });

    cerrar.focus();
});

// Si la persona agrandó la foto con los dedos, al cerrarla la página vuelve a su tamaño.
function resetZoom() {
    $('meta[name=viewport]').remove();
    $('head').append('<meta name="viewport" content="width=device-width, maximum-scale=1.0, user-scalable=0">');

    $('meta[name=viewport]').remove();
    $('head').append('<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=yes">');
}

var setCookie = function(name, value, days) {

    var expires = "";
    if (days) {
        var date = new Date();
        date.setTime(date.getTime() + (days*24*60*60*1000));
        expires = "; expires=" + date.toUTCString();
    }
    document.cookie = name + "=" + (value || "")  + expires + "; path=/";
}

var getCookie = function(name) {

    var nameEQ = name + "=";
    var ca = document.cookie.split(';');
    for(var i=0;i < ca.length;i++) {
        var c = ca[i];
        while (c.charAt(0)==' ') c = c.substring(1,c.length);
        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length,c.length);
    }
    return null;
}

var animalId = null;
var animalType = "G";

function goToForm() {

  if (animalType == "P") {
    location.href = "/pre-adopcion/perros/?id=" + animalId;
  } else {
    location.href = "/pre-adopcion/?id=" + animalId;
  }
}

function showReservadoModal(_animalId, _animalType) {
  animalId = _animalId;
  animalType = _animalType;

  if (_animalType == "P") {
    var animal = "Perro";
  } else {
    var animal = "Gato";
  }

  $("#reservado-modal-header").html("Este " + animal + " se encuentra reservado");
  $("#reservado-modal-body").html("Podés completar el formulario de pre-adopción de todas formas pero si se concreta la adopción con el principal candidato no tendrás la opción de adoptarlo. Te recomendamos completar el formulario para otro " + animal + " de <b>Catpuccino Adopciones</b>")

  $("#reservado-modal").modal("show");
}

function scrollToAnimals() {
  $([document.documentElement, document.body]).animate({
    scrollTop: $("#gatitos-en-adopcion").offset().top
  }, 250);
}

function textoDelAtributo(el, nombre) {

  var valor = el ? el.getAttribute(nombre) : null
  return valor == null ? "" : String(valor)
}

function escaparHtml(texto) {

  return String(texto)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
}

// Las sugerencias del buscador son las zonas que escribieron los rescatistas. El plugin
// (jquery.autocomplete 1.4.11) las mete con .html() y, con la caja vacía, sin escapar:
// una zona con <img onerror=…> corría en el navegador de cualquiera que tocara "Buscar",
// el equipo incluido. Acá se escapa siempre, y lo que coincide se resalta sobre el texto
// ya escapado.
function sugerenciaEscapada(suggestion, currentValue) {

  var valor = String(suggestion.value)
  var buscado = String(currentValue || "")
  //sin tildes, como el buscador: "lanus" resalta "Lanús". Sacarle la tilde a una letra
  //escrita junta deja el mismo largo; si el texto no tiene ese largo, se busca como antes
  var sinTildes = normalizarTexto(valor)
  var desde = !buscado ? -1 : sinTildes.length === valor.length
    ? sinTildes.indexOf(normalizarTexto(buscado))
    : valor.toLowerCase().indexOf(buscado.toLowerCase())

  if (desde === -1) {
    return escaparHtml(valor)
  }

  var hasta = desde + buscado.length
  return escaparHtml(valor.slice(0, desde)) + "<strong>" + escaparHtml(valor.slice(desde, hasta)) + "</strong>" + escaparHtml(valor.slice(hasta))
}

// "Lanús", "LANUS" y "lanus" son lo mismo para el buscador: en minúscula y sin tildes.
// Antes "Lanus" no encontraba "Lanús", y desde el celular casi nadie escribe la tilde.
function normalizarTexto(texto) {

  texto = String(texto == null ? "" : texto).toLowerCase()
  if (texto.normalize) {
    texto = texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  }
  return texto
}

// Cachorros: menos de 12 meses. La edad en meses la estima el server del texto que
// escribió el rescatista (services/edad.py); si no se pudo, data-meses viene vacío y el
// animal aparece solo con los filtros de edad apagados.
var MESES_DE_ADULTO = 12;

function mesesDeLaTarjeta(el) {

  var meses = parseInt(textoDelAtributo(el, "data-meses"), 10)
  return isNaN(meses) ? null : meses
}

var PALABRAS_DEL_SEXO = {M: "macho", H: "hembra", A: "macho y hembra"};

// Dónde se busca: nombre, zona, sexo y edad (y "cachorro"/"adulto", para quien lo escribe
// en vez de tocar el botón). Una línea por dato: una palabra no se arma con dos.
function textoBuscable(el) {

  var meses = mesesDeLaTarjeta(el)
  return [
    textoDelAtributo(el, "data-name"),
    textoDelAtributo(el, "data-zone"),
    PALABRAS_DEL_SEXO[textoDelAtributo(el, "data-sexo")] || "",
    textoDelAtributo(el, "data-edad"),
    meses === null ? "" : (meses < MESES_DE_ADULTO ? "cachorro" : "adulto"),
  ].map(normalizarTexto).join("\n")
}

// Cada palabra buscada tiene que estar en algún lado: "macho lanus" encuentra a los machos
// de Lanús. Con una sola palabra es lo mismo que antes, buscar un pedazo del nombre o la zona.
function coincideLaBusqueda(el, palabras) {

  var texto = textoBuscable(el)
  return palabras.every(function(palabra) {
    return texto.indexOf(palabra) !== -1
  })
}

// "Macho y Hembra" es una camada: entra en los dos
function coincideElSexo(el, sexo) {

  if (!sexo) {
    return true
  }
  var propio = textoDelAtributo(el, "data-sexo")
  return propio === sexo || propio === "A"
}

function coincideLaEdad(el, edad) {

  if (!edad) {
    return true
  }
  var meses = mesesDeLaTarjeta(el)
  if (meses === null) {
    return false
  }
  return edad === "cachorro" ? meses < MESES_DE_ADULTO : meses >= MESES_DE_ADULTO
}

function _filter(zone, type, sexo, edad) {

  var palabras = normalizarTexto(zone).split(/\s+/).filter(Boolean)

  $(".post-preview").each(function() {

    //attr y no data(): data() convierte "1636" en número y "null" en null, y ahí
    //toLowerCase() tiraba un TypeError que dejaba sin andar el buscador y el filtro
    var coincide = coincideLaBusqueda(this, palabras)
      && (textoDelAtributo(this, "data-type") == type || type == "all")
      && coincideElSexo(this, sexo)
      && coincideLaEdad(this, edad)

    //qué se muestra lo decide paginar(): acá solo se marca si la tarjeta coincide
    $(this).parent().toggleClass("no-coincide", !coincide);
  })
}

// Sexo y edad: dos botones cada uno, que se prenden y se apagan. Ninguno prendido es "todos".
function filtroElegido(atributo) {

  var elegido = $(".filtro-opciones button[" + atributo + "][aria-pressed=true]").attr(atributo)
  return elegido || ""
}

function elegirFiltro(atributo, valor) {

  $(".filtro-opciones button[" + atributo + "]").each(function() {
    var activo = !!valor && this.getAttribute(atributo) === valor
    $(this).toggleClass("activo", activo).attr("aria-pressed", activo ? "true" : "false")
  })
}

// La portada muestra de a 5 filas y un "Cargar más": con la lista entera nadie llegaba
// nunca al pie. Se pagina sobre lo que dejan los filtros, así que buscar sigue
// encontrando entre todos los animales y no solo entre los que ya se ven.
// En el celular va una ficha por fila, y de a 5 había que tocar "Cargar más" a cada
// rato: ahí van de a 10.
var FILAS_POR_PAGINA = 5;
var TARJETAS_POR_PAGINA_EN_CELULAR = 10;
var paginasMostradas = 1;

function tarjetasPorFila() {
  //col-md-{{cols}}: en celular va una por fila
  var cols = parseInt($("#animal-list").data("cols"), 10) || 12;
  if (!window.matchMedia("(min-width: 768px)").matches) {
    return 1;
  }
  var porFila = Math.max(1, Math.floor(12 / cols));
  //de a tres pasan a ser de a cuatro en las pantallas anchas (col-xl-3 en index.html)
  if (porFila === 3 && window.matchMedia("(min-width: 1200px)").matches) {
    return 4;
  }
  return porFila;
}

function tarjetasPorPagina() {
  var porFila = tarjetasPorFila();
  return porFila === 1 ? TARJETAS_POR_PAGINA_EN_CELULAR : FILAS_POR_PAGINA * porFila;
}

function paginar() {

  var lista = $("#animal-list");
  if (!lista.length) {
    return;
  }

  var limite = paginasMostradas * tarjetasPorPagina();
  var coinciden = 0;

  lista.children(".animal-card").each(function() {
    var tarjeta = $(this);
    if (tarjeta.hasClass("no-coincide")) {
      tarjeta.hide();
      return;
    }
    coinciden++;
    tarjeta.toggle(coinciden <= limite);
  });

  //desde acá manda el JS, ya no el recorte inicial del CSS
  lista.removeClass("paginada-inicial");

  var mostrados = Math.min(coinciden, limite);
  $("#cargar-mas-container").toggle(coinciden > limite);
  $("#cargar-mas-cuenta").text("Mostrando " + mostrados + " de " + coinciden);

  //arriba de la lista, cuántos hay; y si la búsqueda no encontró nada, que se diga:
  //antes quedaba la página en blanco
  var total = lista.children(".animal-card").length;
  $("#resultados-cuenta").text((coinciden == total ? total : coinciden + " de " + total) + " en adopción");
  $("#sin-resultados").toggle(coinciden === 0);

  //las tarjetas que recién aparecen se miden ahora que se ven
  revisarMostrarMas();
}

// "Mostrar más" va solo donde la descripción no entra en sus tres renglones, y eso se
// puede medir recién cuando la tarjeta se ve. Antes se decidía una sola vez, al cargar,
// cuando de la tarjeta 11 en adelante estaban ocultas y medían 0: esas quedaban sin el
// link, y después de "Cargar más" o de buscar un nombre aparecían cortadas y sin forma de
// abrirlas. Una tarjeta oculta se saltea: la mide paginar() al mostrarla, o el
// ResizeObserver cuando cambia de tamaño (al aparecer, al cargar la letra, al girar el
// celular).
function revisarUnMostrarMas(texto) {

  var vecino = texto.nextElementSibling
  var link = vecino ? vecino.querySelector(".show-more-a") : null
  if (!link || !texto.getClientRects().length) {
    return
  }

  //abierta mide lo que mide el texto entero: el link tiene que quedar para cerrarla
  var hayMas = texto.classList.contains("expanded") || texto.scrollHeight > texto.clientHeight + 1
  link.parentElement.style.display = hayMas ? "" : "none"
}

function revisarMostrarMas() {

  var textos = document.querySelectorAll(".show-more-text")
  for (var i = 0; i < textos.length; i++) {
    revisarUnMostrarMas(textos[i])
  }
}

var observadorDeDescripciones = null;

function observarDescripciones() {

  if (!window.ResizeObserver || observadorDeDescripciones) {
    return;
  }

  observadorDeDescripciones = new ResizeObserver(function(entradas) {
    entradas.forEach(function(entrada) {
      revisarUnMostrarMas(entrada.target)
    })
  })

  $(".show-more-text").each(function() {
    observadorDeDescripciones.observe(this)
  })
}

// Todos / Gatos / Perros: los botones de la portada manejan el <select> #filter-type,
// que es el que lee filterAnimals()
function elegirTipo(tipo) {
  $(".filtro-tipo button").each(function() {
    var activo = $(this).data("tipo") == tipo;
    $(this).toggleClass("activo", activo).attr("aria-pressed", activo ? "true" : "false");
  });
  $("#filter-type").val(tipo).trigger("change");
}

// "Limpiar la búsqueda": el texto, el tipo, el sexo y la edad
function verTodos() {
  $("#filter-zone").val("");
  elegirFiltro("data-sexo", "");
  elegirFiltro("data-edad", "");
  elegirTipo("all");
}

function cargarMas() {
  paginasMostradas++;
  paginar();
}

function filterAnimals() {

  var zone = $("#filter-zone").val() || "";
  var type = $("#filter-type").val();

  _filter(zone, type, filtroElegido("data-sexo"), filtroElegido("data-edad"))

  //solo cuando cambia el orden: reordenar vuelve a armar todos los carruseles
  var sort = $("#filter-sort").val() || "";
  if (sort !== ordenAplicado) {
    sortAnimals(sort);
    initializeImages();
    ordenAplicado = sort;
  }

  //otra búsqueda arranca de nuevo por las primeras filas
  paginasMostradas = 1;
  paginar();
  reflejarEnLaUrl();
}

// La búsqueda queda en la URL (?buscar=, ?tipo=, ?sexo=, ?edad=): copiada y mandada por
// WhatsApp, abre la portada ya filtrada. Con replaceState, que no suma una entrada al
// historial por cada letra. Los demás parámetros (el fbclid que agrega Instagram) quedan.
var EN_LA_URL = {
  tipo: {G: "gatos", P: "perros"},
  sexo: {M: "machos", H: "hembras"},
  edad: {cachorro: "cachorros", adulto: "adultos"},
};

// lo que se acepta al leerla: también en singular, y sin importar mayúsculas
function desdeLaUrl(filtro, valor) {

  valor = normalizarTexto(valor).replace(/s$/, "")
  var opciones = EN_LA_URL[filtro]
  for (var clave in opciones) {
    if (opciones[clave].replace(/s$/, "") === valor) {
      return clave
    }
  }
  return ""
}

var esperaDeLaUrl = null;

function reflejarEnLaUrl() {

  if (!$("#filter-zone").length || !window.URLSearchParams || !window.history || !history.replaceState) {
    return
  }

  //una vez que se deja de escribir: Safari corta replaceState después de 100 en 30 segundos
  clearTimeout(esperaDeLaUrl)
  esperaDeLaUrl = setTimeout(function() {

    var parametros = new URLSearchParams(location.search)
    var valores = {
      buscar: $.trim($("#filter-zone").val() || ""),
      tipo: EN_LA_URL.tipo[$("#filter-type").val()] || "",
      sexo: EN_LA_URL.sexo[filtroElegido("data-sexo")] || "",
      edad: EN_LA_URL.edad[filtroElegido("data-edad")] || "",
    }

    Object.keys(valores).forEach(function(nombre) {
      if (valores[nombre]) {
        parametros.set(nombre, valores[nombre])
      } else {
        parametros.delete(nombre)
      }
    })

    var query = parametros.toString()
    var url = location.pathname + (query ? "?" + query : "") + location.hash
    if (url !== location.pathname + location.search + location.hash) {
      try {
        history.replaceState(history.state, "", url)
      } catch (e) {
        //sin URL actualizada la búsqueda igual anda
      }
    }
  }, 300)
}

// Al abrir un link con la búsqueda, se aplica antes de mostrar nada
function aplicarLaUrl() {

  if (!$("#filter-zone").length || !window.URLSearchParams) {
    return false
  }

  var parametros = new URLSearchParams(location.search)
  var buscar = parametros.get("buscar") || ""
  var tipo = desdeLaUrl("tipo", parametros.get("tipo") || "")
  var sexo = desdeLaUrl("sexo", parametros.get("sexo") || "")
  var edad = desdeLaUrl("edad", parametros.get("edad") || "")

  if (!buscar && !tipo && !sexo && !edad) {
    return false
  }

  $("#filter-zone").val(buscar)
  elegirFiltro("data-sexo", sexo)
  elegirFiltro("data-edad", edad)
  $(".filtro-tipo button").each(function() {
    var activo = $(this).data("tipo") == (tipo || "all");
    $(this).toggleClass("activo", activo).attr("aria-pressed", activo ? "true" : "false");
  });
  $("#filter-type").val(tipo || "all")
  filterAnimals()
  return true
}

// "" es el orden en que llegó la página (los publicados o republicados más recientes
// primero): elegirlo de nuevo tiene que volver ahí, y antes no hacía nada.
var ordenAplicado = "";

function sortAnimals(option) {
  var cards = Array.from(document.querySelectorAll('.animal-card'));
  var sortedCards = cards.sort(function(a,b) {
    if (!option) {
      return parseInt(a.getAttribute("data-orden"), 10) > parseInt(b.getAttribute("data-orden"), 10) ? 1 : -1;
    }
    var aId = $(a).data('id');
    var bId = $(b).data('id');
    if (option == "asc") {
      return aId > bId ? 1 : -1;
    } else {
      return aId < bId ? 1 : -1;
    }
  })
  $("#animal-list").html(sortedCards)
}

// Las zonas las escribe cada rescatista: "Belgrano", "BELGRANO" y "belgrano " son la
// misma, igual que "Lanús" y "Lanus", y "....." no es ninguna. Queda una por zona, la
// primera forma que aparece.
function zonasParaSugerir(zonesData) {
  var vistas = {};
  var zonas = [];
  zonesData.split("||").forEach(function(zona) {
    var limpia = $.trim(zona).replace(/\s+/g, " ");
    var clave = normalizarTexto(limpia);
    if (!/[a-z0-9áéíóúüñ]/i.test(limpia) || vistas[clave]) {
      return;
    }
    vistas[clave] = true;
    zonas.push({ value: limpia });
  });
  return zonas;
}

$(document).ready(function() {

    //el orden en que llegó la página, para poder volver a él (sortAnimals). En un
    //atributo: .html() le borra los datos de jQuery a las tarjetas que reordena.
    $("#animal-list > .animal-card").each(function(i) {
      this.setAttribute("data-orden", i)
    })

    initializeImages()

    observarDescripciones()
    //con un link que trae la búsqueda (?buscar=…) ya se arranca filtrado; filterAnimals pagina
    if (!aplicarLaUrl()) {
      paginar()
    }
    //donde no hay lista paginada (/adopciones/) paginar() no hace nada: se miden igual
    revisarMostrarMas()
    $("#cargar-mas").on("click", cargarMas);
    //cuántas tarjetas entran por fila cambia solo al cruzar los 768px o los 1200px
    //(rotar una tablet); un resize común se dispara con cada scroll en el celular
    var cortes = ["(min-width: 768px)", "(min-width: 1200px)"];
    cortes.forEach(function(consulta) {
      var ancho = window.matchMedia(consulta);
      if (ancho.addListener) {
        ancho.addListener(paginar)
      }
    })

    //input y search además de keyup: pegar un texto, o la × que le pone el navegador a la
    //caja de búsqueda, no sueltan ninguna tecla
    $("#filter-zone").on("keyup input search", function() {
      filterAnimals()
    })
    $(".filtro-tipo button").on("click", function() {
      elegirTipo($(this).data("tipo"))
    })
    //tocar el que está prendido lo apaga: vuelve a "todos"
    $(".filtro-opciones button").on("click", function() {
      var atributo = this.hasAttribute("data-sexo") ? "data-sexo" : "data-edad"
      var valor = this.getAttribute(atributo)
      elegirFiltro(atributo, filtroElegido(atributo) === valor ? "" : valor)
      filterAnimals()
    })
    $("#ver-todos").on("click", verTodos)
    $("#filter-type").on("change", function() {
      filterAnimals()
    })
    $("#filter-sort").on("change", function() {
      filterAnimals()
    })

    $("#main-button-action").on("click", function() {
      scrollToAnimals()
    })

    var zonesData = textoDelAtributo($("#filter-zone")[0], "data-zones")
    if (!!zonesData) {
      //minChars 1 y hasta 6: con la caja vacía se abría la lista entera de zonas, que en
      //el celular tapaba los filtros y los animales
      $("#filter-zone").autocomplete({
        lookup: zonasParaSugerir(zonesData),
        minChars: 1,
        lookupLimit: 6,
        //sin tildes ni mayúsculas, como el buscador: "lanus" sugiere "Lanús"
        lookupFilter: function(suggestion, query) {
          return normalizarTexto(suggestion.value).indexOf(normalizarTexto(query)) !== -1
        },
        formatResult: sugerenciaEscapada,
        onSelect: function (suggestion) {
          filterAnimals()
        }
      })
    }
});