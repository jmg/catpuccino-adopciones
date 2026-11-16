// Efectos modernos para Catpuccino Adopciones

document.addEventListener('DOMContentLoaded', function() {
  // Reemplazar la función showMore existente
  window.showMore = function(element) {
    const textElement = element.parentElement.previousElementSibling;
    if (textElement.classList.contains('expanded')) {
      textElement.classList.remove('expanded');
      element.textContent = 'Mostrar más';

      // Scroll hacia arriba hasta la tarjeta
      const card = element.closest('.post-preview');
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      textElement.classList.add('expanded');
      element.textContent = 'Mostrar menos';
    }
  };

  // Qué descripciones necesitan "Mostrar más" lo decide index.js (revisarMostrarMas), que
  // las mide cuando se ven. Acá se medían todas una sola vez, al cargar, y a las tarjetas
  // ocultas por la paginación —que miden 0— se les sacaba el link para siempre.
  if (window.revisarMostrarMas) {
    window.revisarMostrarMas();
  }

  // Efecto de la navbar al hacer scroll
  const navbar = document.getElementById('mainNav');
  const logoElement = document.querySelector('.main-logo');

  // Función para actualizar la navegación basada en el scroll
  function updateNavigation() {
    // Añadir clase scrolled al hacer scroll
    if (window.scrollY > 30) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }

    // Detectar qué sección está activa basada en el scroll
    const scrollPosition = window.scrollY + 100;

    // Obtener todos los enlaces de navegación
    const navLinks = document.querySelectorAll('.nav-link:not(.dropdown-toggle):not(.highlight)');

    // Verificar si algún enlace debe estar activo
    let activeFound = false;

    navLinks.forEach(link => {
      // Solo procesar enlaces que apuntan a secciones en la misma página
      const href = link.getAttribute('href');
      if (href && href.startsWith('#')) {
        const section = document.querySelector(href);
        if (section) {
          const sectionTop = section.offsetTop;
          const sectionHeight = section.offsetHeight;

          if (scrollPosition >= sectionTop && scrollPosition < sectionTop + sectionHeight) {
            link.classList.add('active');
            activeFound = true;
          } else {
            link.classList.remove('active');
          }
        }
      }
    });

    // Si no se encontró sección activa, activar el enlace de inicio
    if (!activeFound && navLinks.length > 0) {
      // Si estamos en la página principal, activar el primer enlace
      if (window.location.pathname === '/' || window.location.pathname === '/index.html') {
        navLinks[0].classList.add('active');
      }
    }
  }

  // Añadir el event listener para scroll
  window.addEventListener('scroll', updateNavigation);

  // Ejecutar una vez al cargar para establecer el estado inicial
  updateNavigation();

  // Efectos para las tarjetas de animales
  const animalCards = document.querySelectorAll('.animal-card');

  // Agregar efecto de elevación al pasar el mouse
  animalCards.forEach(card => {
    // Añadir clases para animar entrada
    setTimeout(() => {
      card.style.opacity = '1';
    }, 100);

    // Efecto de elevación suave al hacer hover - DESHABILITADO
    /*
    card.addEventListener('mouseenter', function() {
      const previewCard = this.querySelector('.post-preview');
      previewCard.style.transform = 'translateY(-5px)';
      previewCard.style.boxShadow = '0 12px 20px rgba(0,0,0,0.1)';
    });

    // Restaurar estado original al salir del elemento
    card.addEventListener('mouseleave', function() {
      const previewCard = this.querySelector('.post-preview');
      previewCard.style.transform = 'translateY(0)';
      previewCard.style.boxShadow = '0 10px 20px rgba(0,0,0,0.1)';
    });
    */
  });

  // Efecto de zoom al hacer hover en las imágenes - DESHABILITADO
  /*
  const carouselImages = document.querySelectorAll('.carousel-image');
  carouselImages.forEach(imageContainer => {
    imageContainer.addEventListener('mouseenter', function() {
      const image = this.querySelector('img');
      if (image) {
        image.style.transform = 'scale(1.03)';
      }
    });

    imageContainer.addEventListener('mouseleave', function() {
      const image = this.querySelector('img');
      if (image) {
        image.style.transform = 'scale(1)';
      }
    });
  });
  */

  // Eliminar cualquier efecto brillante que pueda estar causando problemas
  document.querySelectorAll('.carousel-image img, .post-image').forEach(img => {
    img.style.filter = 'none';
    img.style.webkitFilter = 'none';
    img.style.transform = 'none';
    img.style.boxShadow = 'none';
    img.style.transition = 'none';
  });

  // El menú del celular: Escape lo cierra, y el botón dice lo que va a hacer
  const menu = document.getElementById('navbarResponsive');
  const botonMenu = document.querySelector('#mainNav .navbar-toggler');
  if (menu && botonMenu && window.jQuery) {
    jQuery(menu)
      .on('shown.bs.collapse', function() { botonMenu.setAttribute('aria-label', 'Cerrar el menú'); })
      .on('hidden.bs.collapse', function() { botonMenu.setAttribute('aria-label', 'Abrir el menú'); });

    document.addEventListener('keydown', function(e) {
      if ((e.key === 'Escape' || e.key === 'Esc') && menu.classList.contains('show')) {
        jQuery(menu).collapse('hide');
        botonMenu.focus();
      }
    });
  }

  // "Volver arriba": solo donde hay una lista larga de animales (en los formularios y en
  // el panel tapaba campos y botones), y recién cuando la persona empieza a subir: al
  // bajar leyendo quedaba encima de las flechas de las fotos.
  if (!document.getElementById('animal-list')) {
    return;
  }

  const backToTopButton = document.createElement('button');
  backToTopButton.type = 'button';
  backToTopButton.innerHTML = '<i class="fa fa-arrow-up" aria-hidden="true"></i>';
  backToTopButton.className = 'back-to-top-btn';
  backToTopButton.setAttribute('aria-label', 'Volver arriba');
  document.body.appendChild(backToTopButton);

  let ultimoScroll = window.pageYOffset;
  window.addEventListener('scroll', function() {
    const ahora = window.pageYOffset;
    if (ahora < 600) {
      backToTopButton.classList.remove('show');
    } else if (ahora < ultimoScroll - 4) {
      backToTopButton.classList.add('show');
    } else if (ahora > ultimoScroll + 4) {
      backToTopButton.classList.remove('show');
    }
    ultimoScroll = ahora;
  }, { passive: true });

  backToTopButton.addEventListener('click', function() {
    window.scrollTo({ top: 0 });
    backToTopButton.classList.remove('show');
  });
});
