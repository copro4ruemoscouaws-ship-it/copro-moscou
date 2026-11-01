/* Espace copropriété : petits comportements de l'interface.
   - bouton « Nouveau dossier » qui affiche le formulaire
   - barre « Déplacer la sélection »
   - visionneuse de photos plein écran (clavier, flèches, glisser du doigt) */
(function () {
  'use strict';

  /* ---------- Afficher / masquer un formulaire ---------- */
  document.querySelectorAll('[data-toggle]').forEach(function (btn) {
    var target = document.getElementById(btn.getAttribute('data-toggle'));
    if (!target) return;
    btn.setAttribute('aria-expanded', 'false');
    btn.addEventListener('click', function () {
      var open = target.hasAttribute('hidden');
      if (open) target.removeAttribute('hidden'); else target.setAttribute('hidden', '');
      btn.setAttribute('aria-expanded', String(open));
      if (open) { var f = target.querySelector('input[type=text]'); if (f) f.focus(); }
    });
  });

  /* ---------- Barre de déplacement ---------- */
  var bar = document.querySelector('[data-movebar]');
  if (bar) {
    var count = bar.querySelector('[data-movecount]');
    var boxes = document.querySelectorAll('input[name=doc_ids][form=move-form]');
    var refresh = function () {
      var n = 0;
      boxes.forEach(function (b) {
        if (b.checked) n++;
        var holder = b.closest('.photo, .item');
        if (holder) holder.classList.toggle('picked', b.checked);
      });
      bar.classList.toggle('active', n > 0);
      count.textContent = n ? n + ' sélectionné' + (n > 1 ? 's' : '') + ' → déplacer vers' : 'Cochez des documents pour les déplacer';
    };
    boxes.forEach(function (b) { b.addEventListener('change', refresh); });
    bar.addEventListener('submit', function (e) {
      if (!bar.classList.contains('active')) { e.preventDefault(); }
    });
    refresh();
  }

  /* ---------- Visionneuse de photos ---------- */
  var viewer = null, items = [], index = 0, lastFocus = null, touchX = null;

  function build() {
    viewer = document.createElement('div');
    viewer.className = 'viewer';
    viewer.setAttribute('role', 'dialog');
    viewer.setAttribute('aria-modal', 'true');
    viewer.setAttribute('aria-label', 'Photo en grand');
    viewer.innerHTML =
      '<div class="viewer-top"><span class="viewer-title"></span><span class="viewer-count"></span>' +
      '<a class="viewer-link" href="#">Fiche</a><button class="viewer-close" type="button" aria-label="Fermer">×</button></div>' +
      '<button class="viewer-nav prev" type="button" aria-label="Photo précédente">‹</button>' +
      '<figure class="viewer-stage"><img alt=""></figure>' +
      '<button class="viewer-nav next" type="button" aria-label="Photo suivante">›</button>';
    document.body.appendChild(viewer);
    viewer.querySelector('.viewer-close').addEventListener('click', close);
    viewer.querySelector('.prev').addEventListener('click', function () { go(-1); });
    viewer.querySelector('.next').addEventListener('click', function () { go(1); });
    viewer.addEventListener('click', function (e) { if (e.target === viewer || e.target.classList.contains('viewer-stage')) close(); });
    viewer.addEventListener('touchstart', function (e) { touchX = e.touches[0].clientX; }, { passive: true });
    viewer.addEventListener('touchend', function (e) {
      if (touchX === null) return;
      var dx = e.changedTouches[0].clientX - touchX;
      if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1);
      touchX = null;
    });
  }

  function show() {
    var a = items[index];
    var img = viewer.querySelector('img');
    viewer.classList.add('loading');
    img.onload = function () { viewer.classList.remove('loading'); };
    img.src = a.getAttribute('data-full');
    img.alt = a.getAttribute('data-title') || '';
    viewer.querySelector('.viewer-title').textContent = a.getAttribute('data-title') || '';
    viewer.querySelector('.viewer-count').textContent = items.length > 1 ? (index + 1) + ' / ' + items.length : '';
    var link = viewer.querySelector('.viewer-link');
    var detail = a.getAttribute('data-detail');
    link.hidden = !detail;
    if (detail) link.href = detail;
    var multi = items.length > 1;
    viewer.querySelector('.prev').hidden = !multi;
    viewer.querySelector('.next').hidden = !multi;
  }

  function go(step) { index = (index + step + items.length) % items.length; show(); }

  function open(list, i) {
    if (!viewer) build();
    items = list; index = i; lastFocus = document.activeElement;
    show();
    viewer.classList.add('open');
    document.documentElement.classList.add('no-scroll');
    viewer.querySelector('.viewer-close').focus();
  }

  function close() {
    viewer.classList.remove('open');
    document.documentElement.classList.remove('no-scroll');
    viewer.querySelector('img').removeAttribute('src');
    if (lastFocus) lastFocus.focus();
  }

  document.addEventListener('keydown', function (e) {
    if (!viewer || !viewer.classList.contains('open')) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowRight') go(1);
    else if (e.key === 'ArrowLeft') go(-1);
  });

  document.querySelectorAll('[data-gallery]').forEach(function (gallery) {
    var links = Array.prototype.slice.call(gallery.querySelectorAll('a.thumb[data-full]'));
    links.forEach(function (a, i) {
      a.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;  // ouvrir dans un nouvel onglet reste possible
        e.preventDefault();
        open(links, i);
      });
    });
  });
})();
