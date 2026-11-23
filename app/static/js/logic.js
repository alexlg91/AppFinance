/* Fonctions pures (aucun accès au DOM) : testées sous Node, voir tests/logic.test.mjs. */

export const MONTHS = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet',
  'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'];

export const SORTS = [
  ['date_desc', 'Date (Décroissant)'],
  ['date_asc', 'Date (Croissant)'],
  ['amount_asc', 'Montant (Croissant)'],
  ['amount_desc', 'Montant (Décroissant)'],
  ['category', 'Par Catégorie'],
];

/** Somme exacte en centimes (évite 0.1 + 0.2 = 0.30000000000000004). */
export const sum = (nums) => Math.round(nums.reduce((a, n) => a + Math.round(n * 100), 0)) / 100;

/** Minuscules sans accents : « Café » trouve « cafe ». */
export const normalize = (s) => String(s ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

export const monthOf = (tx) => ({ year: +tx.date.slice(0, 4), month: +tx.date.slice(5, 7), day: +tx.date.slice(8, 10) });

/** Filtres instantanés : f = {year:'all'|'2026', query, category, account, type}. */
export function filterTransactions(txs, f) {
  const q = normalize(f.query).trim();
  return txs.filter((t) => {
    if (f.year !== 'all' && t.date.slice(0, 4) !== String(f.year)) return false;
    if (q && !normalize(t.name).includes(q)) return false;
    if (f.category !== 'all' && t.category !== f.category) return false;
    if (f.account !== 'all' && t.account !== f.account && t.target_account !== f.account) return false;
    if (f.type !== 'all' && t.type !== f.type) return false;
    return true;
  });
}

/** Mêmes critères de tri que l'application d'origine (ID en départage). */
export function sortTransactions(txs, sort) {
  const byDate = (a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id);
  const cmp = {
    date_desc: (a, b) => -byDate(a, b),
    date_asc: byDate,
    amount_asc: (a, b) => a.amount - b.amount || a.id - b.id,
    amount_desc: (a, b) => b.amount - a.amount || b.id - a.id,
    category: (a, b) => a.category.localeCompare(b.category, 'fr') || b.amount - a.amount,
  }[sort] || byDate;
  return [...txs].sort(cmp);
}

/** Bandeau de résumé : les transferts ne sont ni des entrées ni des dépenses. */
export function summarize(txs) {
  const entrees = sum(txs.filter((t) => t.type === 'Entrée').map((t) => t.amount));
  const sorties = sum(txs.filter((t) => t.type === 'Sortie').map((t) => t.amount));
  return { entrees, sorties, net: sum([entrees, -sorties]), count: txs.length };
}

/** Regroupe en conservant l'ordre : un groupe par (année, mois) rencontré consécutivement. */
export function groupByMonth(txs) {
  const groups = [];
  for (const t of txs) {
    const { year, month } = monthOf(t);
    const key = `${year}-${month}`;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(t);
    else groups.push({ key, year, month, items: [t] });
  }
  return groups;
}

/** Simulateur : opérations du compte choisi + solde projeté (n'écrit jamais en base). */
export function simulate(moves, account, realBalance) {
  const mine = moves.filter((m) => m.account === account);
  const delta = sum(mine.map((m) => m.amount));
  return { moves: mine, delta, projected: sum([realBalance, delta]) };
}

/** Couleur d'un compte (mêmes règles que l'ancienne appli). */
export function accountColor(name) {
  const n = name.toLowerCase();
  if (n.includes('livret a')) return '#3B82F6';
  if (n.includes('courant') || n.includes('compte')) return '#EF4444';
  if (n.includes('livret')) return '#F59E0B';
  return '#10B981';
}

/** Dégradé « intensité » pour les barres de moyennes (équivalent des échelles Reds / Greens). */
export function shade(value, max, base) {
  const t = max > 0 ? Math.max(0.25, Math.min(1, value / max)) : 1;
  const [r, g, b] = base === 'green' ? [22, 163, 74] : [220, 38, 38];
  return `rgba(${r}, ${g}, ${b}, ${t.toFixed(2)})`;
}

export function todayISO(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 'AAAA-MM-JJ' -> 'JJ/MM/AAAA' */
export const fmtDate = (iso) => iso.split('-').reverse().join('/');
