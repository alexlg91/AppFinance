/* Simulateur de solde : opérations « brouillon » purement locales (jamais envoyées au serveur).
   Mémorisées en sessionStorage pour survivre à un rechargement de page, effacées à la fermeture de l'onglet. */
import { state } from './store.js';
import { h, fillSelect, fmtMoney, fmtSigned, tone } from './ui.js';
import { simulate } from './logic.js';

const key = () => `banque-simulation:${state.user.id}`;   // un brouillon par utilisateur : jamais partagé entre profils

function load() {
  try {
    const raw = JSON.parse(sessionStorage.getItem(key()) || '[]');
    return Array.isArray(raw) ? raw.filter((m) => m && typeof m.amount === 'number') : [];
  } catch { return []; }
}

export function createSimulator(dialog) {
  let moves = load();
  let account = null;

  const save = () => { try { sessionStorage.setItem(key(), JSON.stringify(moves)); } catch { /* stockage indisponible */ } };

  dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); }); // clic sur le fond

  function render() {
    const names = state.accounts.map((a) => a.name);
    if (!names.includes(account)) account = names[0];
    const real = state.balances[account] ?? 0;
    const sim = simulate(moves, account, real);

    const accountSel = h('select', { onChange: (e) => { account = e.target.value; render(); } });
    fillSelect(accountSel, names, account);
    accountSel.value = account;

    const desc = h('input', { type: 'text', name: 'desc', placeholder: 'Ex : Loyer, facture…', maxLength: 80 });
    const amount = h('input', { type: 'number', name: 'amount', step: '0.01', placeholder: '-650 pour une dépense', required: true });

    const onAdd = (e) => {
      e.preventDefault();
      const value = parseFloat(amount.value);
      if (!Number.isFinite(value) || value === 0) return;
      moves.push({ account, desc: desc.value.trim() || 'Opération simulée', amount: value });
      save(); render();
      dialog.querySelector('input[name="desc"]')?.focus();
    };

    // .filter(Boolean) : replaceChildren() natif transformerait `false` en texte « false »
    dialog.replaceChildren(...[
      h('div', { class: 'simu-head' },
        h('div', null, h('h3', { style: { margin: 0 } }, '🔮 Simulateur de solde'),
          h('p', { class: 'muted', style: { margin: '.2rem 0 0', fontSize: '.85rem' } },
            "Brouillon d'anticipation : n'impacte pas vos vraies données.")),
        h('button', { class: 'btn ghost', type: 'button', 'aria-label': 'Fermer', onClick: () => dialog.close() }, '✕')),
      h('label', { class: 'field' }, h('span', null, 'Compte à simuler'), accountSel),
      h('p', null, 'Solde actuel : ', h('b', { class: 'num' }, fmtMoney(real))),
      h('form', { class: 'grid', onSubmit: onAdd },
        h('label', { class: 'field' }, h('span', null, 'Description'), desc),
        h('label', { class: 'field' }, h('span', null, 'Montant (€) — négatif pour une dépense'), amount),
        h('button', { class: 'btn primary', type: 'submit' }, '➕ Ajouter')),
      sim.moves.length > 0 && h('div', null,
        h('p', { style: { margin: '.8rem 0 0', fontWeight: 600 } }, 'Opérations en attente'),
        h('ul', null, ...sim.moves.map((m) => h('li', null,
          h('span', null, h('b', { style: { color: tone(m.amount) } }, fmtSigned(m.amount)), ` — ${m.desc}`),
          h('button', {
            class: 'btn ghost small', type: 'button', 'aria-label': `Retirer ${m.desc}`,
            onClick: () => { moves = moves.filter((x) => x !== m); save(); render(); },
          }, '✕'))))),
      h('div', { class: 'projected', style: { '--tone': tone(sim.projected) } },
        h('div', { class: 't' }, 'Solde projeté'),
        h('div', { class: 'v' }, fmtMoney(sim.projected))),
      h('button', {
        class: 'btn', type: 'button', style: { width: '100%' },
        onClick: () => { moves = []; save(); render(); },
      }, '🗑️ Réinitialiser'),
    ].filter(Boolean));
  }

  return {
    open() { render(); dialog.showModal(); },
    /** À appeler quand les soldes changent pendant que le simulateur est ouvert. */
    refresh() { if (dialog.open) render(); },
  };
}
