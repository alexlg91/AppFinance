/* Thème clair/sombre : préférence mémorisée, sinon celle du système. Chargé avant le rendu. */
(function () {
  var saved = null;
  try { saved = localStorage.getItem('banque-theme'); } catch (e) { /* stockage indisponible */ }
  var dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
