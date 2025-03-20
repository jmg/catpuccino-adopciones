// Efectos modernos para Catpuccino Adopciones

document.addEventListener('DOMContentLoaded', function() {
  // Reemplazar la función showMore existente
  window.showMore = function(element) {
    const textElement = element.parentElement.previousElementSibling;
    if (textElement.classList.contains('expanded')) {
      textElement.classList.remove('expanded');
      element.textContent = 'Mostrar más...';

      // Scroll hacia arriba hasta la tarjeta
      const card = element.closest('.post-preview');
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      textElement.classList.add('expanded');
      element.textContent = 'Mostrar menos';
    }
  };

  // Efectos para las tarjetas de animales
  const animalCards = document.querySelectorAll('.animal-card');

  // Agregar efecto de elevación al pasar el mouse
  animalCards.forEach(card => {
    // Añadir clases para animar entrada
    setTimeout(() => {
      card.style.opacity = '1';
    }, 100);

    // Efecto de inclinación 3D al mover el mouse (Tilt effect)
    card.addEventListener('mousemove', function(e) {
      const cardRect = this.getBoundingClientRect();
      const cardWidth = cardRect.width;
      const cardHeight = cardRect.height;

      // Calcular posición relativa del mouse dentro de la tarjeta
      const mouseX = e.clientX - cardRect.left;
      const mouseY = e.clientY - cardRect.top;

      // Calcular rotación basada en la posición del mouse
      const rotateY = ((mouseX / cardWidth) - 0.5) * 8; // Máximo 8 grados de rotación
      const rotateX = ((mouseY / cardHeight) - 0.5) * -8;

      // Aplicar transformación
      this.querySelector('.post-preview').style.transform =
        `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-5px)`;

      // Efecto de iluminación (shine effect)
      const shine = this.querySelector('.post-preview');
      const shineLeftPos = (mouseX / cardWidth) * 100;
      const shineTopPos = (mouseY / cardHeight) * 100;
      shine.style.background =
        `radial-gradient(circle at ${shineLeftPos}% ${shineTopPos}%, rgba(255,255,255,0.03), transparent 40%),
         white`;
    });

    // Restaurar estado original al salir del elemento
    card.addEventListener('mouseleave', function() {
      const previewCard = this.querySelector('.post-preview');
      previewCard.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) translateY(0)';
      previewCard.style.background = 'white';
    });
  });

  // Efecto de zoom al hacer hover en las imágenes
  const carouselImages = document.querySelectorAll('.carousel-image');
  carouselImages.forEach(imageContainer => {
    imageContainer.addEventListener('mouseenter', function() {
      const image = this.querySelector('img');
      if (image) {
        image.style.transform = 'scale(1.05)';
      }
    });

    imageContainer.addEventListener('mouseleave', function() {
      const image = this.querySelector('img');
      if (image) {
        image.style.transform = 'scale(1)';
      }
    });
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

  // Acción de volver arriba
  backToTopButton.addEventListener('click', function() {
    window.scrollTo({
      top: 0,
      behavior: 'smooth'
    });
  });
});