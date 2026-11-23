// Test de fumée du frontend SANS navigateur : mini-DOM + faux fetch + faux Chart.js, alimentés par de vrais
// payloads du backend (tests/fixtures, générés par tests/make_fixtures.py).
//   node tests/frontend_smoke.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const fixture = (n) => JSON.parse(readFileSync(join(here, 'fixtures', n), 'utf-8'));

// ============================================================ mini-DOM (juste ce qu'utilise l'application)
class Node {}
class Text extends Node {
  constructor(t) { super(); this.nodeType = 3; this._t = String(t); this.parentNode = null; }
  get textContent() { return this._t; }
}
const PROPS = ['checked', 'disabled', 'required', 'placeholder', 'min', 'max', 'step', 'maxLength', 'title', 'href',
  'download', 'inputMode', 'name', 'autocomplete', 'type', 'selected'];

class Element extends Node {
  constructor(tag) {
    super();
    this.tagName = tag.toUpperCase(); this.nodeType = 1; this.children = []; this.parentNode = null;
    this.attrs = {}; this.listeners = {}; this.className = ''; this.hidden = false; this.open = false;
    this.style = { setProperty(k, v) { this[k] = v; } };
    this._value = undefined;
    for (const p of PROPS) this[p] = p === 'checked' || p === 'selected' || p === 'disabled' || p === 'required' ? false : '';
  }
  get value() {
    if (this.tagName === 'SELECT') { const o = this.children.find((c) => c.selected) ?? this.children[0]; return o ? o.value : ''; }
    return this._value ?? (this.tagName === 'OPTION' ? this.textContent : '');
  }
  set value(v) {
    if (this.tagName === 'SELECT') {
      const hit = this.children.find((c) => String(c.value) === String(v));
      this.children.forEach((c) => { c.selected = false; });
      if (hit) hit.selected = true;
    } else this._value = String(v);
  }
  get textContent() { return this.children.map((c) => c.textContent).join(''); }
  _adopt(n) {
    if (n.isFragment) { [...n.children].forEach((c) => this._adopt(c)); n.children = []; return; }
    if (n.parentNode) n.parentNode.children = n.parentNode.children.filter((c) => c !== n);
    n.parentNode = this; this.children.push(n);
  }
  append(...ns) { ns.forEach((n) => this._adopt(n instanceof Node ? n : new Text(n))); }  // comme le vrai DOM : false -> "false"
  prepend(...ns) { const old = this.children; this.children = []; this.append(...ns); this.children.push(...old); }
  replaceChildren(...ns) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; this.append(...ns); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this); }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }
  focus() {} showModal() { this.open = true; } close() { this.open = false; }
  walk(fn) { fn(this); this.children.forEach((c) => c.walk?.(fn)); }
  all(pred) { const out = []; this.walk((n) => { if (n !== this && pred(n)) out.push(n); }); return out; }
  querySelector(sel) {
    const m = sel.match(/^(\w+)?\[(\w+)="([^"]*)"\]$/);
    return this.all((n) => (!m[1] || n.tagName === m[1].toUpperCase()) && (n[m[2]] === m[3] || n.attrs[m[2]] === m[3]))[0] ?? null;
  }
}
const frag = () => Object.assign(new Element('fragment'), { isFragment: true });
const toastBox = new Element('div');
const root = new Element('html');
root.dataset = { theme: 'light' };
globalThis.Node = Node;
globalThis.window = globalThis;
globalThis.document = {
  createElement: (t) => new Element(t), createTextNode: (t) => new Text(t), createDocumentFragment: frag,
  getElementById: () => toastBox, documentElement: root,
};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '#123456' });
const store = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)) }; };
globalThis.sessionStorage = store(); globalThis.localStorage = store();
globalThis.matchMedia = () => ({ matches: false });
globalThis.confirm = () => true;

const fire = async (el, type, extra = {}) => {
  for (const fn of el.listeners[type] || []) await fn({ type, target: el, preventDefault() {}, ...extra });
  await new Promise((r) => setTimeout(r, 0));
};
const isRow = (n) => n.className.includes('tx-row') && !n.className.includes('head');
const byText = (el, tag, text) => el.all((n) => n.tagName === tag && n.textContent.includes(text))[0];
const assertClean = (el) => assert.ok(!/\b(false|undefined|null|NaN)\b/.test(el.textContent), `valeur brute affichée : ${el.textContent.match(/.{0,30}\b(false|undefined|null|NaN)\b.{0,20}/)?.[0]}`);
const byLabel = (el, label) => el.all((n) => n.attrs['aria-label'] === label)[0];

// ============================================================ faux Chart.js + faux serveur
class FakeChart {
  static instances = [];
  static defaults = { font: {} };
  constructor(canvas, cfg) { this.cfg = cfg; FakeChart.instances.push(this); }
  destroy() { this.destroyed = true; }
}
globalThis.Chart = FakeChart;

const calls = [];
let nextId = 100;
let usersDb = [
  { id: 1, username: 'Admin', is_admin: true, has_password: true },
  { id: 2, username: 'Alice', is_admin: false, has_password: true },
];
globalThis.fetch = async (url, init = {}) => {
  const body = init.body ? JSON.parse(init.body) : undefined;
  calls.push({ method: init.method, url, body });
  const reply = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
  const balances = { balances: { 'Compte Courant': 1, 'Livret A': 2, 'Épargne': 3 }, total: 6 };
  if (url.startsWith('/api/dashboard')) return reply(fixture('dashboard.json'));
  if (url === '/api/users' && init.method === 'GET') return reply({ users: usersDb });
  if (url === '/api/users' && init.method === 'POST') {
    usersDb = [...usersDb, { id: 3, username: body.username, is_admin: body.is_admin, has_password: true }];
    return reply({ users: usersDb }, 201);
  }
  if (url.startsWith('/api/users/') && init.method === 'DELETE') {
    usersDb = usersDb.filter((u) => u.id !== +url.split('/').pop());
    return reply({ users: usersDb });
  }
  if (url.startsWith('/api/users/') && url.endsWith('/password')) return reply({ users: usersDb });
  if (url === '/api/settings/password') return reply({ password_enabled: true, has_password: body.enabled });
  if (init.method === 'POST' && url === '/api/transactions') return reply({ transaction: { id: nextId++, ...body }, ...balances }, 201);
  if (init.method === 'PUT' && url.startsWith('/api/transactions/')) return reply({ transaction: { id: +url.split('/').pop(), ...body }, ...balances });
  if (init.method === 'DELETE' && url.startsWith('/api/transactions/')) return reply(balances);
  return reply({ detail: `non géré : ${init.method} ${url}` }, 404);
};

// ============================================================ charge les VRAIS modules du frontend
const tmp = mkdtempSync(join(tmpdir(), 'front-'));
cpSync(join(here, '../app/static/js'), tmp, { recursive: true });
writeFileSync(join(tmp, 'package.json'), '{"type":"module"}');
const imp = (f) => import(join(tmp, f));
const { state, hydrate } = await imp('store.js');
const { createTransactions } = await imp('transactions.js');
const { createDashboard } = await imp('dashboard.js');
const { createSettings } = await imp('settings.js');
const { createSimulator } = await imp('simulator.js');

hydrate(fixture('bootstrap.json'));
const dialog = new Element('dialog');
const simulator = createSimulator(dialog);

// ============================================================ scénarios
test('transactions : affichage, filtres instantanés, regroupement par mois', async () => {
  const view = new Element('section');
  const tv = createTransactions(view, { simulator });
  tv.activate();

  const year = view.all((n) => n.tagName === 'SELECT' && n.children.some((o) => o.value === 'all' && o.textContent === 'Toutes'))[0];
  year.value = 'all'; await fire(year, 'change');
  assertClean(view);
  assert.equal(view.all(isRow).length, 5, '5 transactions importées');
  assert.deepEqual(view.all((n) => n.className === 'month-head').map((n) => n.textContent),
    ['📅 Février 2026', '📅 Janvier 2026', '📅 Décembre 2025']);
  assert.match(view.all((n) => n.className === 'summary')[0].textContent, /5\s*transaction/);

  const search = view.all((n) => n.type === 'search')[0];
  search.value = 'EPARGNE'; await fire(search, 'input');
  assert.equal(view.all(isRow).length, 1, 'recherche sans accents ni casse');
  assert.ok(view.textContent.includes('De : Compte Courant ➔ Vers : Livret A'));

  search.value = 'zzz'; await fire(search, 'input');
  assert.equal(view.all(isRow).length, 0);
  assert.ok(view.textContent.includes('Aucune transaction ne correspond'));
  assert.equal(calls.filter((c) => c.url.includes('transactions')).length, 0, 'aucune requête réseau pour filtrer');
  search.value = ''; await fire(search, 'input');
});

test('transactions : ajout, suppression avec « Annuler », édition inline', async () => {
  const view = new Element('section');
  createTransactions(view, { simulator }).activate();
  const year = view.all((n) => n.tagName === 'SELECT' && n.children.some((o) => o.value === 'all'))[0];
  year.value = 'all'; await fire(year, 'change');

  // ajout
  const [entryForm] = view.all((n) => n.tagName === 'FORM');
  const amount = entryForm.all((n) => n.type === 'number')[0];
  amount.value = '12.5';
  await fire(entryForm, 'submit', { submitter: { disabled: false } });
  const post = calls.filter((c) => c.method === 'POST' && c.url === '/api/transactions').pop();
  assert.equal(post.body.type, 'Sortie');
  assert.equal(post.body.amount, 12.5);
  assert.equal(post.body.target_account, null);
  assert.equal(view.all(isRow).length, 6);
  assert.equal(state.total, 6, 'soldes remplacés par la réponse du serveur');

  // suppression + annulation
  const del = byLabel(view.all(isRow)[0], 'Supprimer');
  await fire(del, 'click');
  assert.equal(view.all(isRow).length, 5);
  const undo = byText(toastBox, 'BUTTON', 'Annuler');
  assert.ok(undo, 'toast avec action Annuler');
  await fire(undo, 'click');
  assert.equal(view.all(isRow).length, 6, 'rétablie');

  // édition
  await fire(byLabel(view.all(isRow)[0], 'Modifier'), 'click');
  const editForm = view.all((n) => n.className.includes('editing'))[0];
  assert.ok(editForm, 'ligne transformée en formulaire');
  editForm.all((n) => n.type === 'number')[0].value = '99';
  await fire(editForm, 'submit');
  const put = calls.filter((c) => c.method === 'PUT').pop();
  assert.equal(put.body.amount, 99);
  assert.equal(view.all((n) => n.className.includes('editing')).length, 0);
});

test('transfert : refuse même compte de départ et d’arrivée sans appel réseau', async () => {
  const view = new Element('section');
  createTransactions(view, { simulator }).activate();
  const form = view.all((n) => n.tagName === 'FORM')[1];
  const [from, to] = form.all((n) => n.tagName === 'SELECT');
  to.value = from.value;
  const before = calls.length;
  await fire(form, 'submit', { submitter: { disabled: false } });
  assert.equal(calls.length, before);
  assert.ok(toastBox.textContent.includes('ne peuvent pas être les mêmes'));
});

test('dashboard : graphiques construits depuis la réponse réelle du backend', async () => {
  const view = new Element('section');
  FakeChart.instances.length = 0;
  const dash = createDashboard(view);
  state.dashboardDirty = true;
  dash.activate();
  await new Promise((r) => setTimeout(r, 5));
  const types = FakeChart.instances.map((c) => c.cfg.type).sort();
  assert.equal(types.filter((t) => t === 'doughnut').length, 2, 'dépenses du mois + dépenses de l’année (pas d’entrées en janvier 2026)');
  assert.equal(types.filter((t) => t === 'line').length, 1);
  assert.ok(types.filter((t) => t === 'bar').length >= 1);
  const line = FakeChart.instances.find((c) => c.cfg.type === 'line').cfg;
  assert.equal(line.data.datasets.length, 3, 'une courbe par compte');
  assert.equal(line.data.datasets[0].data.at(-1), 1740.6);
  assert.ok(view.textContent.includes('Balance de Janvier 2026'), 'carte de balance du mois');
  const donut = FakeChart.instances.find((c) => c.cfg.type === 'doughnut').cfg;
  assert.equal(donut.data.datasets[0].backgroundColor[0], '#14B8A6', 'couleur personnalisée de la catégorie');
  assert.equal(state.dashboardDirty, false);
  assertClean(view);
});

test('simulateur : solde projeté sans appel serveur', async () => {
  state.balances = { ...state.balances, 'Compte Courant': 1740.6 };  // les scénarios précédents ont écrasé les soldes via le faux serveur
  const before = calls.length;
  simulator.open();
  assert.ok(dialog.open);
  const form = dialog.all((n) => n.tagName === 'FORM')[0];
  form.all((n) => n.type === 'number')[0].value = '-650';
  await fire(form, 'submit');
  const projected = dialog.all((n) => n.className === 'v')[0].textContent.replace(/\s/g, ' ');
  assert.match(projected, /1\s?090,60/, `solde projeté attendu 1 090,60 € (reçu : ${projected})`);
  assert.equal(calls.length, before, 'le brouillon ne quitte jamais le navigateur');
  assertClean(dialog);
  assert.ok(dialog.textContent.includes('Opération simulée'), 'opération listée');
});

test('paramètres : comptes, catégories, sécurité (utilisateur seul)', async () => {
  const view = new Element('section');
  createSettings(view, { simulator, onAuthChanged() {} }).activate();       // rendu synchrone, avant le chargement des utilisateurs
  for (const name of ['Compte Courant', 'Livret A', 'Épargne']) assert.ok(byLabel(view, `Solde initial de ${name}`), name);
  assert.ok(byLabel(view, 'Couleur de Loisirs'));
  assert.equal(byLabel(view, 'Couleur de Virement interne'), undefined, 'catégorie système masquée');
  assert.ok(view.textContent.includes('Activer la protection par mot de passe'), 'un seul utilisateur : case à cocher classique');
  assert.ok(view.all((n) => n.tagName === 'A' && n.href === '/api/export.csv').length === 1, 'lien export CSV');
  assertClean(view);
});

test('paramètres : indicateur de chiffrement de la base (selon /api/bootstrap)', () => {
  assert.equal(state.dbEncrypted, true, 'le payload réel du backend (db_encrypted) est pris en compte');
  const view = new Element('section');
  createSettings(view, { simulator, onAuthChanged() {} }).activate();
  assert.ok(view.textContent.includes('🔐 Base de données chiffrée'));
  assert.ok(!view.textContent.includes('non chiffrée'));
  assertClean(view);

  state.dbEncrypted = false;
  try {
    const plain = new Element('section');
    createSettings(plain, { simulator, onAuthChanged() {} }).activate();
    assert.ok(plain.textContent.includes('🔓 Base de données non chiffrée'));
    assert.ok(plain.textContent.includes('README'), 'indique comment l’activer');
    assertClean(plain);
  } finally { state.dbEncrypted = true; }
});

test('paramètres : avertissement si l’ancien banque_data.json reste en clair à côté de la base chiffrée', () => {
  assert.equal(state.legacyJsonInClear, false);
  const clean = new Element('section');
  createSettings(clean, { simulator, onAuthChanged() {} }).activate();
  assert.ok(!clean.textContent.includes('banque_data.json'));

  state.legacyJsonInClear = true;
  try {
    const view = new Element('section');
    createSettings(view, { simulator, onAuthChanged() {} }).activate();
    const warn = view.all((n) => n.attrs?.role === 'alert');
    assert.equal(warn.length, 1);
    assert.ok(warn[0].textContent.includes('banque_data.json') && warn[0].textContent.includes('supprimez-le'));
    assertClean(view);
  } finally { state.legacyJsonInClear = false; }
});

test('utilisateurs : liste, création, réinitialisation, suppression (administrateur)', async () => {
  const view = new Element('section');
  const changes = [];
  createSettings(view, { simulator, onAuthChanged: () => changes.push(state.usersCount) }).activate();
  await new Promise((r) => setTimeout(r, 5));                                // liste chargée via GET /api/users

  assert.ok(view.textContent.includes('👥 Utilisateurs'));
  assert.ok(view.textContent.includes('Alice'));
  assert.equal(state.usersCount, 2);
  assert.ok(view.textContent.includes('Mon mot de passe'), 'plusieurs utilisateurs : plus de case « désactiver la protection »');
  assert.ok(!view.textContent.includes('Désactiver la protection'));
  const rows = view.all((n) => n.className === 'user-row');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].all((n) => n.tagName === 'BUTTON').length, 0, 'aucune action sur sa propre ligne (pas d’auto-suppression)');
  assert.ok(rows[0].textContent.includes('vous'));

  // création
  const addForm = view.all((n) => n.tagName === 'FORM').find((f) => f.all((n) => n.attrs['aria-label'] === 'Identifiant du nouvel utilisateur').length);
  const [name, pwd] = addForm.all((n) => n.tagName === 'INPUT');
  name.value = 'Bob'; pwd.value = 'secret';
  await fire(addForm, 'submit');
  const post = calls.filter((c) => c.method === 'POST' && c.url === '/api/users').pop();
  assert.deepEqual(post.body, { username: 'Bob', password: 'secret', is_admin: false });
  assert.ok(view.textContent.includes('Bob'));
  assert.equal(state.usersCount, 3);
  assert.equal(changes.at(-1), 3, 'onAuthChanged notifié');

  // réinitialisation du mot de passe d'un autre utilisateur
  await fire(view.all((n) => n.tagName === 'BUTTON' && n.textContent.includes('🔑 Mot de passe'))[0], 'click');
  const resetForm = view.all((n) => n.className === 'reset-form')[0];
  assert.ok(resetForm, 'formulaire inline');
  resetForm.all((n) => n.tagName === 'INPUT')[0].value = 'nouveau';
  await fire(resetForm, 'submit');
  const put = calls.filter((c) => c.method === 'PUT' && /\/api\/users\/\d+\/password/.test(c.url)).pop();
  assert.equal(put.body.password, 'nouveau');

  // suppression
  const del = view.all((n) => n.tagName === 'BUTTON' && n.textContent.includes('Supprimer'))[0];
  await fire(del, 'click');
  assert.ok(calls.some((c) => c.method === 'DELETE' && c.url.startsWith('/api/users/')));
  assert.equal(state.usersCount, 2);
  assertClean(view);
});

test('utilisateurs : un non-administrateur ne voit ni ne charge la gestion des utilisateurs', async () => {
  const saved = state.user;
  state.user = { ...saved, id: 2, username: 'Alice', is_admin: false };
  const before = calls.filter((c) => c.url === '/api/users').length;
  const view = new Element('section');
  createSettings(view, { simulator, onAuthChanged() {} }).activate();
  await new Promise((r) => setTimeout(r, 5));
  assert.ok(!view.textContent.includes('👥 Utilisateurs'));
  assert.equal(calls.filter((c) => c.url === '/api/users').length, before, 'aucun appel à /api/users');
  assert.ok(view.textContent.includes('Mon mot de passe'), 'peut changer SON mot de passe');
  assertClean(view);
  state.user = saved;
});

test('admin sans mot de passe : création d’utilisateur proposée seulement une fois le mot de passe défini', async () => {
  const saved = state.user;
  state.user = { ...saved, has_password: false };
  state.usersCount = 1; usersDb = usersDb.slice(0, 1);
  const view = new Element('section');
  createSettings(view, { simulator, onAuthChanged() {} }).activate();
  await new Promise((r) => setTimeout(r, 5));
  assert.ok(view.textContent.includes('Définissez d’abord votre mot de passe'));
  assert.equal(view.all((n) => n.attrs['aria-label'] === 'Identifiant du nouvel utilisateur').length, 0);
  state.user = saved;
});

test('simulateur : le brouillon est isolé par utilisateur', async () => {
  const keys = (id) => sessionStorage.getItem(`banque-simulation:${id}`);
  state.user = { ...state.user, id: 7 };
  const dlg = new Element('dialog');
  const sim7 = createSimulator(dlg);
  sim7.open();
  const form = dlg.all((n) => n.tagName === 'FORM')[0];
  form.all((n) => n.type === 'number')[0].value = '-5';
  await fire(form, 'submit');
  assert.ok(keys(7)?.includes('-5'), 'brouillon enregistré sous l’identifiant 7');
  state.user = { ...state.user, id: 8 };
  assert.equal(keys(8), null, 'un autre utilisateur ne le voit pas');
});
