/* Point d'entrée : authentification, navigation par onglets (#dashboard, #transactions, #settings), thème. */
import { api, setUnauthorizedHandler } from './api.js';
import { state, hydrate } from './store.js';
import { h, errorMessage } from './ui.js';
import { createDashboard } from './dashboard.js';
import { createTransactions } from './transactions.js';
import { createSettings } from './settings.js';
import { createSimulator } from './simulator.js';

const $ = (selector) => document.querySelector(selector);
const TABS = ['dashboard', 'transactions', 'settings'];

let views = null;      // construites une seule fois, au premier affichage
let current = 'dashboard';

// ---------------------------------------------------------------- écran de connexion
const LAST_USER = 'banque-last-user';   // dernier identifiant utilisé (confort : pas un secret)
const EXPIRED = 'banque-expired';       // drapeau posé avant le rechargement qui suit une session expirée

function showLogin(message) {
  $('#app').hidden = true;
  $('#login').hidden = false;
  const error = $('#login-error');
  error.hidden = !message;
  error.textContent = message || '';
  const user = $('#login-form [name="username"]');
  const password = $('#login-form [name="password"]');
  try { user.value = localStorage.getItem(LAST_USER) || ''; } catch { /* stockage indisponible */ }
  password.value = '';
  (user.value ? password : user).focus();
}

$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const error = $('#login-error');
  error.hidden = true;
  const username = $('#login-form [name="username"]').value.trim();
  try {
    await api.login(username, $('#login-form [name="password"]').value);
    try { localStorage.setItem(LAST_USER, username); } catch { /* stockage indisponible */ }
    // Rechargement systématique : aucune donnée d'un utilisateur précédent ne peut subsister en mémoire.
    location.reload();
  } catch (err) {
    error.textContent = errorMessage(err);
    error.hidden = false;
  }
});

// Session expirée/révoquée : on recharge (efface toutes les données affichées) puis on affiche l'écran de connexion.
setUnauthorizedHandler(() => {
  try { sessionStorage.setItem(EXPIRED, '1'); } catch { /* stockage indisponible */ }
  location.reload();
});

// ---------------------------------------------------------------- onglets
function switchTab(name) {
  current = TABS.includes(name) ? name : 'dashboard';
  for (const tab of TABS) {
    $(`#view-${tab}`).hidden = tab !== current;
    $(`[data-tab="${tab}"]`).setAttribute('aria-selected', String(tab === current));
  }
  views[current].activate();   // redessine seulement ce qui a changé depuis la dernière visite
}

const tabFromHash = () => location.hash.replace('#', '');

// ---------------------------------------------------------------- démarrage
/** Bouton de déconnexion et nom de l'utilisateur : visibles dès que la connexion est obligatoire. */
function updateIdentity() {
  $('#btn-lock').hidden = !state.protected;
  const who = $('#whoami');
  who.hidden = !state.protected;
  who.textContent = `👤 ${state.user.username}`;
}

function buildViews() {
  const simulator = createSimulator($('#dlg-simu'));
  views = {
    dashboard: createDashboard($('#view-dashboard')),
    transactions: createTransactions($('#view-transactions'), { simulator }),
    settings: createSettings($('#view-settings'), { simulator, onAuthChanged: updateIdentity }),
  };

  for (const tab of TABS) $(`[data-tab="${tab}"]`).addEventListener('click', () => { location.hash = tab; });
  window.addEventListener('hashchange', () => switchTab(tabFromHash()));

  $('#btn-lock').addEventListener('click', async () => {
    try { await api.logout(); } finally { location.reload(); }   // recharger efface toutes les données de la mémoire
  
  });
  $('#btn-theme').addEventListener('click', () => {
    const dark = document.documentElement.dataset.theme !== 'dark';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    try { localStorage.setItem('banque-theme', dark ? 'dark' : 'light'); } catch { /* stockage indisponible */ }
    views.dashboard.invalidate();   // les graphiques lisent les couleurs du thème au moment du dessin
    if (current === 'dashboard') views.dashboard.activate();
  });
}

async function start() {
  hydrate(await api.bootstrap());
  $('#login').hidden = true;
  $('#app').hidden = false;
  if (!views) buildViews();
  updateIdentity();
  state.dashboardDirty = true;
  switchTab(tabFromHash());
}

(async function boot() {
  try {
    const status = await api.status();
    let expired = false;
    try { expired = sessionStorage.getItem(EXPIRED) === '1'; sessionStorage.removeItem(EXPIRED); } catch { /* stockage indisponible */ }
    if (status.password_enabled && !status.authenticated) showLogin(expired ? 'Session expirée : reconnectez-vous.' : '');
    else await start();
  } catch (err) {
    document.body.prepend(h('p', { class: 'form-error', style: { padding: '1rem' } }, errorMessage(err)));
  }
})();
