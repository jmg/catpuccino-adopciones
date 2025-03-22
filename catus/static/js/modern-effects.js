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

  // Verificar qué elementos de texto necesitan el botón "Mostrar más"
  document.querySelectorAll('.show-more-text').forEach(textElement => {
    const showMoreLink = textElement.nextElementSibling.querySelector('.show-more-a');

    // Comprobar si el texto está truncado (si el contenido desborda)
    const isOverflowing = textElement.scrollHeight > textElement.clientHeight;

    if (!isOverflowing) {
      // Si no hay desbordamiento, ocultar el enlace "Mostrar más"
      if (showMoreLink) {
        showMoreLink.parentElement.style.display = 'none';
      }
    }
  });

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

  // Añadir botón flotante "Volver arriba"
  const backToTopButton = document.createElement('button');
  backToTopButton.innerHTML = '<i class="fa fa-arrow-up"></i>';
  backToTopButton.className = 'back-to-top-btn';
  document.body.appendChild(backToTopButton);

  // Mostrar/ocultar el botón según el scroll
  window.addEventListener('scroll', function() {
    if (window.pageYOffset > 300) {
      backToTopButton.classList.add('show');
    } else {
      backToTopButton.classList.remove('show');
    }
  });

  // Acción del botón "Volver arriba"
  backToTopButton.addEventListener('click', function() {
    window.scrollTo({
      top: 0,
      behavior: 'smooth'
    });
  });
});