/* Vue « Transactions ».
   Filtrage, tri, résumé et regroupement se font ENTIÈREMENT côté client (aucune requête réseau à la frappe).
   Les modifications sont envoyées en JSON ; la réponse met à jour l'état local, puis la liste est redessinée
   (un seul nœud DOM par ligne, pas de grille de widgets recréée par un serveur). */
import { api } from './api.js';
import { state, userCategories, categoryColor, applyBalances } from './store.js';
import { h, field, fillSelect, fmtMoney, fmtSigned, renderBalanceCards, toast, errorMessage, tone } from './ui.js';
import { MONTHS, SORTS, filterTransactions, sortTransactions, summarize, groupByMonth, todayISO, fmtDate } from './logic.js';

const PAGE_SIZE = 300;          // lignes rendues d'un coup ; « Afficher plus » pour la suite
const TYPES = ['Entrée', 'Sortie', 'Transfert'];
const typeColor = (t) => (t === 'Sortie' ? 'var(--red)' : t === 'Entrée' ? 'var(--green)' : 'var(--blue)');

export function createTransactions(root, { simulator }) {
  const now = new Date();
  const filters = { year: String(now.getFullYear()), query: '', category: 'all', account: 'all', type: 'all', sort: 'date_desc' };
  let editingId = null;
  let limit = PAGE_SIZE;

  const accountNames = () => state.accounts.map((a) => a.name);

  // ------------------------------------------------------------------ formulaire Entrée / Sortie
  const entry = {
    date: h('input', { type: 'date', required: true, value: todayISO() }),
    account: h('select'),
    category: h('select'),
    name: h('input', { type: 'text', placeholder: 'Ex : Courses du samedi', maxLength: 200 }),
    amount: h('input', { type: 'number', min: '0.01', step: '0.01', required: true, inputMode: 'decimal' }),
    out: h('input', { type: 'radio', name: 'tx-type', value: 'Sortie', checked: true }),
    in: h('input', { type: 'radio', name: 'tx-type', value: 'Entrée' }),
  };

  const entryForm = h('form', { class: 'grid cols-2', onSubmit: submitEntry },
    h('div', { class: 'grid' },
      h('div', { class: 'field', role: 'radiogroup', 'aria-label': 'Type de transaction' },   // div (pas label) : les radios ont leur propre <label>
        h('span', null, 'Type de transaction'),
        h('div', { class: 'radios' }, h('label', null, entry.in, 'Entrée'), h('label', null, entry.out, 'Sortie'))),
      field('Date', entry.date),
      field('Montant (€)', entry.amount)),
    h('div', { class: 'grid' },
      field('Compte', entry.account), field('Catégorie', entry.category), field('Nom / Description', entry.name)),
    h('button', { class: 'btn primary', type: 'submit' }, '💾 Enregistrer la transaction'));

  async function submitEntry(ev) {
    ev.preventDefault();
    const button = ev.submitter || entryForm.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      addTransaction(await api.createTx({
        date: entry.date.value, type: entry.in.checked ? 'Entrée' : 'Sortie', account: entry.account.value,
        target_account: null, category: entry.category.value, name: entry.name.value, amount: parseFloat(entry.amount.value),
      }));
      toast('Transaction enregistrée.');
      entry.name.value = ''; entry.amount.value = '';
      entry.name.focus();
    } catch (err) { toast(errorMessage(err), { type: 'error' }); } finally { button.disabled = false; }
  }

  // ------------------------------------------------------------------ formulaire Transfert
  const transfer = {
    date: h('input', { type: 'date', required: true, value: todayISO() }),
    from: h('select'),
    to: h('select'),
    name: h('input', { type: 'text', value: 'Virement interne', maxLength: 200 }),
    amount: h('input', { type: 'number', min: '0.01', step: '0.01', required: true, inputMode: 'decimal' }),
  };

  const transferForm = h('form', { class: 'grid cols-2', onSubmit: submitTransfer },
    h('div', { class: 'grid' },
      h('p', { class: 'muted', style: { margin: 0 } }, "Mouvement d'argent entre deux de vos comptes."),
      field('Date', transfer.date), field('Montant à transférer (€)', transfer.amount)),
    h('div', { class: 'grid' },
      field('Compte de départ', transfer.from), field("Compte d'arrivée", transfer.to), field('Nom / Description', transfer.name)),
    h('button', { class: 'btn primary', type: 'submit' }, '🔄 Effectuer le transfert'));

  async function submitTransfer(ev) {
    ev.preventDefault();
    if (transfer.from.value === transfer.to.value) {
      toast("Le compte de départ et d'arrivée ne peuvent pas être les mêmes.", { type: 'error' });
      return;
    }
    const button = ev.submitter || transferForm.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      addTransaction(await api.createTx({
        date: transfer.date.value, type: 'Transfert', account: transfer.from.value, target_account: transfer.to.value,
        category: null, name: transfer.name.value, amount: parseFloat(transfer.amount.value),
      }));
      toast('Transfert enregistré.');
      transfer.amount.value = '';
    } catch (err) { toast(errorMessage(err), { type: 'error' }); } finally { button.disabled = false; }
  }

  // ------------------------------------------------------------------ filtres
  const ctl = {
    year: h('select', { onChange: onFilter }),
    query: h('input', { type: 'search', placeholder: 'Ex : Course, Netflix…', onInput: onFilter }),
    category: h('select', { onChange: onFilter }),
    account: h('select', { onChange: onFilter }),
    type: h('select', { onChange: onFilter }, h('option', { value: 'all' }, 'Tous'), ...TYPES.map((t) => h('option', { value: t }, t))),
    sort: h('select', { onChange: onFilter }, ...SORTS.map(([v, l]) => h('option', { value: v }, l))),
  };
  ctl.year.value = filters.year;

  function onFilter() {
    Object.assign(filters, {
      year: ctl.year.value, query: ctl.query.value, category: ctl.category.value,
      account: ctl.account.value, type: ctl.type.value, sort: ctl.sort.value,
    });
    limit = PAGE_SIZE;
    renderList();
  }

  // ------------------------------------------------------------------ squelette
  const cards = h('div', { class: 'balance-strip' });
  const summary = h('div', { class: 'summary' });
  const list = h('div', { class: 'tx-list' });

  root.append(
    h('h2', null, '📝 Mes transactions'),
    cards,
    h('details', { class: 'panel' }, h('summary', null, "➕ Enregistrer une entrée ou une sortie d'argent"), h('div', { class: 'panel-body' }, entryForm)),
    h('details', { class: 'panel' }, h('summary', null, '🔄 Enregistrer un transfert entre comptes'), h('div', { class: 'panel-body' }, transferForm)),
    h('hr'),
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '.5rem', flexWrap: 'wrap', marginBottom: '.5rem' } },
      h('h3', { style: { margin: 0 } }, '🔍 Recherche & filtres'),
      h('button', { class: 'btn', type: 'button', onClick: () => simulator.open() }, '🔮 Simulateur de solde')),
    h('div', { class: 'grid cols-filters' },
      field('Année', ctl.year), field('Recherche (nom)', ctl.query), field('Catégorie', ctl.category),
      field('Compte', ctl.account), field('Type', ctl.type), field("Tri d'affichage", ctl.sort)),
    summary, list);

  /** Met à jour les listes déroulantes quand comptes / catégories / années ont changé (valeurs conservées). */
  function syncOptions() {
    const names = accountNames();
    const cats = userCategories();
    fillSelect(entry.account, names);
    fillSelect(entry.category, cats);
    fillSelect(transfer.from, names);
    fillSelect(transfer.to, names);
    if (names.length > 1 && transfer.from.value === transfer.to.value) transfer.to.value = names.find((n) => n !== transfer.from.value);
    fillSelect(ctl.year, [['all', 'Toutes'], ...state.years.map(String)], String(now.getFullYear()));
    fillSelect(ctl.category, [['all', 'Toutes'], ...state.categories.map((c) => c.name)]);
    fillSelect(ctl.account, [['all', 'Tous'], ...names]);
    onFilterSilently();
  }
  function onFilterSilently() {
    Object.assign(filters, { year: ctl.year.value, category: ctl.category.value, account: ctl.account.value });
  }

  // ------------------------------------------------------------------ mutations locales
  function addTransaction(res) {
    state.transactions.push(res.transaction);
    applyBalances(res);
    afterChange();
  }

  function afterChange() {
    renderBalanceCards(cards, state, true);
    renderList();
    simulator.refresh();
  }

  async function removeTransaction(tx) {
    try {
      applyBalances(await api.deleteTx(tx.id));
      state.transactions = state.transactions.filter((t) => t.id !== tx.id);
      if (editingId === tx.id) editingId = null;
      afterChange();
      toast('Transaction supprimée.', { actionLabel: 'Annuler', onAction: () => restore(tx), duration: 7000 });
    } catch (err) { toast(errorMessage(err), { type: 'error' }); }
  }

  async function restore(tx) {
    try {
      addTransaction(await api.createTx({
        date: tx.date, type: tx.type, account: tx.account, target_account: tx.target_account,
        category: tx.category, name: tx.name, amount: tx.amount,
      }));
      toast('Transaction rétablie.');
    } catch (err) { toast(errorMessage(err), { type: 'error' }); }
  }

  // ------------------------------------------------------------------ rendu de la liste
  const rowHead = () => h('div', { class: 'tx-row head' },
    h('div', { class: 'meta' }, h('span', null, 'Date'), h('span', null, 'Type'), h('span', null, 'Compte(s)'), h('span', null, 'Catégorie')),
    h('span', null, 'Nom'), h('span', { class: 'amount' }, 'Montant'), h('span', { class: 'actions' }, 'Action'));

  function row(tx) {
    if (editingId === tx.id) return editRow(tx);
    const sign = tx.type === 'Sortie' ? '-' : tx.type === 'Entrée' ? '+' : '';
    return h('div', { class: 'tx-row' },
      h('div', { class: 'meta' },
        h('span', { class: 'c-date num' }, fmtDate(tx.date)),
        h('span', { class: 'type', style: { color: typeColor(tx.type) } }, tx.type),
        h('span', { class: 'c-acc' }, tx.type === 'Transfert'
          ? ['De : ', h('b', null, tx.account), ' ➔ Vers : ', h('b', null, tx.target_account)] : tx.account),
        h('span', { class: 'cat', style: { color: categoryColor(tx.category) } }, tx.category)),
      h('span', { class: 'c-name' }, tx.name),
      h('span', { class: 'amount', style: { color: typeColor(tx.type) } }, `${sign}${fmtMoney(tx.amount)}`),
      h('div', { class: 'actions' },
        h('button', { class: 'btn ghost small', type: 'button', title: 'Modifier cette transaction', 'aria-label': 'Modifier', onClick: () => { editingId = tx.id; renderList(); } }, '✏️'),
        h('button', { class: 'btn ghost small', type: 'button', title: 'Supprimer cette transaction', 'aria-label': 'Supprimer', onClick: () => removeTransaction(tx) }, '🗑️')));
  }

  /** Édition « inline » : la ligne se transforme en formulaire, sans quitter la page. */
  function editRow(tx) {
    const names = accountNames();
    const cats = userCategories();
    if (tx.type !== 'Transfert' && !cats.includes(tx.category)) cats.unshift(tx.category); // catégorie supprimée depuis

    const date = h('input', { type: 'date', value: tx.date, required: true });
    const type = h('select', null, ...TYPES.map((t) => h('option', { value: t }, t)));
    const amount = h('input', { type: 'number', min: '0.01', step: '0.01', value: String(tx.amount), required: true });
    const account = h('select', null, ...names.map((n) => h('option', { value: n }, n)));
    const target = h('select', null, ...names.map((n) => h('option', { value: n }, n)));
    const category = h('select', null, ...cats.map((c) => h('option', { value: c }, c)));
    const name = h('input', { type: 'text', value: tx.name, maxLength: 200 });
    type.value = tx.type;
    if (names.includes(tx.account)) account.value = tx.account;
    if (names.includes(tx.target_account)) target.value = tx.target_account;
    if (cats.includes(tx.category)) category.value = tx.category;

    const targetField = field("Compte d'arrivée", target);
    const categoryField = field('Catégorie', category);
    const syncType = () => { const t = type.value === 'Transfert'; targetField.hidden = !t; categoryField.hidden = t; };
    type.addEventListener('change', syncType);
    syncType();

    const cancel = () => { editingId = null; renderList(); };
    return h('form', {
      class: 'tx-row editing',
      onKeydown: (e) => { if (e.key === 'Escape') cancel(); },
      onSubmit: async (e) => {
        e.preventDefault();
        const isTransfer = type.value === 'Transfert';
        try {
          const res = await api.updateTx(tx.id, {
            date: date.value, type: type.value, account: account.value, amount: parseFloat(amount.value),
            target_account: isTransfer ? target.value : null, category: isTransfer ? null : category.value, name: name.value,
          });
          state.transactions = state.transactions.map((t) => (t.id === tx.id ? res.transaction : t));
          applyBalances(res);
          editingId = null;
          afterChange();
          toast('Transaction modifiée.');
        } catch (err) { toast(errorMessage(err), { type: 'error' }); }
      },
    },
      h('div', { class: 'edit-grid' },
        field('Date', date), field('Type', type), field('Montant (€)', amount),
        field('Compte', account), targetField, categoryField, field('Nom', name)),
      h('div', { class: 'edit-actions' },
        h('button', { class: 'btn primary', type: 'submit' }, '✅ Enregistrer'),
        h('button', { class: 'btn', type: 'button', onClick: cancel }, '❌ Annuler')));
  }

  function renderSummary(items) {
    const s = summarize(items);
    summary.replaceChildren(
      h('div', null,
        h('b', null, '📊 Résumé de la sélection : '),
        h('span', { class: 'pos', style: { fontWeight: 600 } }, `➕ Entrées : ${fmtMoney(s.entrees)}`), ' | ',
        h('span', { class: 'neg', style: { fontWeight: 600 } }, `➖ Dépenses : ${fmtMoney(s.sorties)}`), ' | ',
        h('b', { style: { color: tone(s.net) } }, `⚖️ Net : ${fmtSigned(s.net)}`)),
      h('div', { class: 'muted' }, h('b', null, s.count), ' transaction(s) trouvée(s)'));
  }

  function renderList() {
    const items = sortTransactions(filterTransactions(state.transactions, filters), filters.sort);
    renderSummary(items);
    if (!items.length) {
      list.replaceChildren(h('div', { class: 'empty' }, 'Aucune transaction ne correspond aux critères de recherche actuels.'));
      return;
    }
    const visible = items.slice(0, limit);
    const frag = document.createDocumentFragment();
    if (filters.sort.startsWith('date')) {            // tri par date : groupes « Mois Année »
      for (const g of groupByMonth(visible)) {
        frag.append(h('h3', { class: 'month-head' }, `📅 ${MONTHS[g.month - 1]} ${g.year}`), rowHead(), ...g.items.map(row));
      }
    } else {                                          // autres tris : liste continue (un en-tête de mois n'aurait pas de sens)
      frag.append(rowHead(), ...visible.map(row));
    }
    if (items.length > limit) {
      frag.append(h('button', { class: 'btn more', type: 'button', onClick: () => { limit += PAGE_SIZE; renderList(); } },
        `Afficher plus (${items.length - limit} restantes)`));
    }
    list.replaceChildren(frag);
  }

  return {
    activate() {
      syncOptions();
      renderBalanceCards(cards, state, true);
      renderList();
    },
  };
}
