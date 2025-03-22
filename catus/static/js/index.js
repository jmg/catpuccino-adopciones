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

  sliders.map(function(slider) {
    slider.dispose()
  })

  sliders = []

  $('.carousel').each(function(idx, el) {

    var slider = new bootstrap.Carousel(el, {interval: 3000 })
    sliders.push(slider)
  })

  makeImageFullSize();
}

function showMore(el) {
  var link = $(el)
  link.parent().prev().toggleClass("show-more-text")

  if (link.text() == "Mostrar más") {
    link.text("Mostrar menos")
  } else {
    link.text("Mostrar más")
  }
}

function mobileCheck() {
  var check = false;
  (function(a){if(/(android|bb\d+|meego).+mobile|avantgo|bada\/|blackberry|blazer|compal|elaine|fennec|hiptop|iemobile|ip(hone|od)|iris|kindle|lge |maemo|midp|mmp|mobile.+firefox|netfront|opera m(ob|in)i|palm( os)?|phone|p(ixi|re)\/|plucker|pocket|psp|series(4|6)0|symbian|treo|up\.(browser|link)|vodafone|wap|windows ce|xda|xiino/i.test(a)||/1207|6310|6590|3gso|4thp|50[1-6]i|770s|802s|a wa|abac|ac(er|oo|s\-)|ai(ko|rn)|al(av|ca|co)|amoi|an(ex|ny|yw)|aptu|ar(ch|go)|as(te|us)|attw|au(di|\-m|r |s )|avan|be(ck|ll|nq)|bi(lb|rd)|bl(ac|az)|br(e|v)w|bumb|bw\-(n|u)|c55\/|capi|ccwa|cdm\-|cell|chtm|cldc|cmd\-|co(mp|nd)|craw|da(it|ll|ng)|dbte|dc\-s|devi|dica|dmob|do(c|p)o|ds(12|\-d)|el(49|ai)|em(l2|ul)|er(ic|k0)|esl8|ez([4-7]0|os|wa|ze)|fetc|fly(\-|_)|g1 u|g560|gene|gf\-5|g\-mo|go(\.w|od)|gr(ad|un)|haie|hcit|hd\-(m|p|t)|hei\-|hi(pt|ta)|hp( i|ip)|hs\-c|ht(c(\-| |_|a|g|p|s|t)|tp)|hu(aw|tc)|i\-(20|go|ma)|i230|iac( |\-|\/)|ibro|idea|ig01|ikom|im1k|inno|ipaq|iris|ja(t|v)a|jbro|jemu|jigs|kddi|keji|kgt( |\/)|klon|kpt |kwc\-|kyo(c|k)|le(no|xi)|lg( g|\/(k|l|u)|50|54|\-[a-w])|libw|lynx|m1\-w|m3ga|m50\/|ma(te|ui|xo)|mc(01|21|ca)|m\-cr|me(rc|ri)|mi(o8|oa|ts)|mmef|mo(01|02|bi|de|do|t(\-| |o|v)|zz)|mt(50|p1|v )|mwbp|mywa|n10[0-2]|n20[2-3]|n30(0|2)|n50(0|2|5)|n7(0(0|1)|10)|ne((c|m)\-|on|tf|wf|wg|wt)|nok(6|i)|nzph|o2im|op(ti|wv)|oran|owg1|p800|pan(a|d|t)|pdxg|pg(13|\-([1-8]|c))|phil|pire|pl(ay|uc)|pn\-2|po(ck|rt|se)|prox|psio|pt\-g|qa\-a|qc(07|12|21|32|60|\-[2-7]|i\-)|qtek|r380|r600|raks|rim9|ro(ve|zo)|s55\/|sa(ge|ma|mm|ms|ny|va)|sc(01|h\-|oo|p\-)|sdk\/|se(c(\-|0|1)|47|mc|nd|ri)|sgh\-|shar|sie(\-|m)|sk\-0|sl(45|id)|sm(al|ar|b3|it|t5)|so(ft|ny)|sp(01|h\-|v\-|v )|sy(01|mb)|t2(18|50)|t6(00|10|18)|ta(gt|lk)|tcl\-|tdg\-|tel(i|m)|tim\-|t\-mo|to(pl|sh)|ts(70|m\-|m3|m5)|tx\-9|up(\.b|g1|si)|utst|v400|v750|veri|vi(rg|te)|vk(40|5[0-3]|\-v)|vm40|voda|vulc|vx(52|53|60|61|70|80|81|83|85|98)|w3c(\-| )|webc|whit|wi(g |nc|nw)|wmlb|wonu|x700|yas\-|your|zeto|zte\-/i.test(a.substr(0,4))) check = true;})(navigator.userAgent||navigator.vendor||window.opera);
  return check;
};

function makeImageFullSize() {

    var classes = "img[data-enlargable]";
    if (mobileCheck() === false) {
      classes += ",img[data-enlargable-if-not-mobile]";
    }

    $(classes).addClass('img-enlargable').click(function() {

      var src = $(this).attr('src');
      $('<div>').css({
          background: 'RGBA(0,0,0,.5) url('+src+') no-repeat center',
          backgroundSize: 'contain',
          width:'100%', height:'100%',
          position:'fixed',
          zIndex:'10000',
          top:'0', left:'0',
          cursor: 'zoom-out'
      }).click(function() {

          $(this).remove();
          resetZoom();

      }).appendTo('body');
    });
}

function resetZoom() {
    $('meta[name=viewport]').remove();
    $('head').append('<meta name="viewport" content="width=device-width, maximum-scale=1.0, user-scalable=0">');

    $('meta[name=viewport]').remove();
    $('head').append('<meta name="viewport" content="width=device-width, initial-scale=yes">');
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

function _filter(zone, type) {

  zone = zone.toLowerCase()

  $(".post-preview").each(function() {

    var filterZone = $(this).data("zone").toLowerCase().indexOf(zone) !== -1 || $(this).data("name").toLowerCase().indexOf(zone) !== -1
    var filterType = $(this).data("type") == type || type == "all"

    if (filterZone && filterType) {
      $(this).parent().show();
    } else {
      $(this).parent().hide();
    }
  })
}

function filterAnimals() {

  var zone = $("#filter-zone").val();
  var type = $("#filter-type").val();

  _filter(zone, type)

  var sort = $("#filter-sort").val();
  if (!!sort) {
    sortAnimals(sort);
    initializeImages();
  }
}

function sortAnimals(option) {
  var cards = Array.from(document.querySelectorAll('.animal-card'));
  var sortedCards = cards.sort(function(a,b) {
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

$(document).ready(function() {

    initializeImages()

    $("#filter-zone").on("keyup", function() {
      filterAnimals()
    })
    $("#filter-type").on("change", function() {
      filterAnimals()
    })
    $("#filter-sort").on("change", function() {
      filterAnimals()
    })

    $("#main-button-action").on("click", function() {
      scrollToAnimals()
    })

    var zonesData = $("#filter-zone").data("zones")
    if (!!zonesData) {
      var zones = zonesData.split("||").map(function(zone) {
        return { value: zone }
      })

      $("#filter-zone").autocomplete({
        lookup: zones,
        minChars: 0,
        onSelect: function (suggestion) {
          filterAnimals()
        }
      })
    }
});