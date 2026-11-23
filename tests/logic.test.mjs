// Lancer : node --test tests/    (Node ≥ 18, aucune dépendance)
import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// logic.js est servi comme module ES par le navigateur ; Node exige l'extension .mjs → copie temporaire.
const here = dirname(fileURLToPath(import.meta.url));
const tmp = mkdtempSync(join(tmpdir(), 'logic-'));
copyFileSync(join(here, '../app/static/js/logic.js'), join(tmp, 'logic.mjs'));
const L = await import(join(tmp, 'logic.mjs'));

const T = [
  { id: 1, date: '2026-01-05', type: 'Sortie', account: 'Courant', target_account: null, category: 'Course', name: 'Café Lidl', amount: 59.9 },
  { id: 2, date: '2026-01-10', type: 'Transfert', account: 'Courant', target_account: 'Livret A', category: 'Virement interne', name: 'Épargne', amount: 300 },
  { id: 3, date: '2025-12-30', type: 'Entrée', account: 'Courant', target_account: null, category: 'Salaire', name: 'Paie', amount: 2000 },
  { id: 4, date: '2026-02-02', type: 'Sortie', account: 'Livret A', target_account: null, category: 'Loisirs', name: '', amount: 0.1 },
  { id: 5, date: '2026-02-02', type: 'Sortie', account: 'Livret A', target_account: null, category: 'Loisirs', name: 'x', amount: 0.2 },
];
const F = { year: 'all', query: '', category: 'all', account: 'all', type: 'all' };

test('sum évite la dérive flottante', () => {
  assert.equal(L.sum([0.1, 0.2]), 0.3);
  assert.equal(L.sum([]), 0);
});

test('filtre par année, texte (sans accents ni casse), catégorie, type', () => {
  assert.deepEqual(L.filterTransactions(T, { ...F, year: '2026' }).map((t) => t.id), [1, 2, 4, 5]);
  assert.deepEqual(L.filterTransactions(T, { ...F, query: 'CAFE' }).map((t) => t.id), [1]);
  assert.deepEqual(L.filterTransactions(T, { ...F, query: 'epargne' }).map((t) => t.id), [2]);
  assert.deepEqual(L.filterTransactions(T, { ...F, category: 'Loisirs' }).map((t) => t.id), [4, 5]);
  assert.deepEqual(L.filterTransactions(T, { ...F, type: 'Entrée' }).map((t) => t.id), [3]);
});

test('le filtre compte inclut les transferts reçus (compte cible), comme l’original', () => {
  assert.deepEqual(L.filterTransactions(T, { ...F, account: 'Livret A' }).map((t) => t.id), [2, 4, 5]);
});

test('les 5 tris', () => {
  const ids = (s) => L.sortTransactions(T, s).map((t) => t.id);
  assert.deepEqual(ids('date_desc'), [5, 4, 2, 1, 3]);   // même date → ID décroissant
  assert.deepEqual(ids('date_asc'), [3, 1, 2, 4, 5]);
  assert.deepEqual(ids('amount_asc'), [4, 5, 1, 2, 3]);
  assert.deepEqual(ids('amount_desc'), [3, 2, 1, 5, 4]);
  assert.deepEqual(L.sortTransactions(T, 'category').map((t) => t.category),
    ['Course', 'Loisirs', 'Loisirs', 'Salaire', 'Virement interne']);
  assert.equal(T[0].id, 1, 'le tableau source n’est pas muté');
});

test('résumé : transferts exclus, net exact', () => {
  assert.deepEqual(L.summarize(T), { entrees: 2000, sorties: 60.2, net: 1939.8, count: 5 });
  assert.deepEqual(L.summarize([]), { entrees: 0, sorties: 0, net: 0, count: 0 });
});

test('regroupement par mois, ordre conservé', () => {
  const g = L.groupByMonth(L.sortTransactions(T, 'date_desc'));
  assert.deepEqual(g.map((x) => [x.year, x.month, x.items.length]), [[2026, 2, 2], [2026, 1, 2], [2025, 12, 1]]);
});

test('simulateur : solde projeté par compte, sans toucher au solde réel', () => {
  const moves = [
    { account: 'Courant', desc: 'Loyer', amount: -650 },
    { account: 'Courant', desc: 'Prime', amount: 100.1 },
    { account: 'Livret A', desc: 'autre', amount: 5 },
  ];
  const r = L.simulate(moves, 'Courant', 1740.6);
  assert.equal(r.moves.length, 2);
  assert.equal(r.delta, -549.9);
  assert.equal(r.projected, 1190.7);
  assert.equal(L.simulate([], 'Courant', 10).projected, 10);
});

test('couleurs de compte (règles d’origine) et dates', () => {
  assert.equal(L.accountColor('Livret A'), '#3B82F6');
  assert.equal(L.accountColor('Compte Courant'), '#EF4444');
  assert.equal(L.accountColor('Livret B'), '#F59E0B');
  assert.equal(L.accountColor('PEA'), '#10B981');
  assert.equal(L.fmtDate('2026-03-07'), '07/03/2026');
  assert.equal(L.todayISO(new Date(2026, 10, 21)), '2026-11-21');
  assert.match(L.shade(5, 10, 'red'), /^rgba\(220, 38, 38, 0\.50\)$/);
});
