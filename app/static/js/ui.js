/* Briques d'interface partagées. Tout le DOM est construit via h() + textContent :
   les noms de transactions/comptes/catégories ne sont JAMAIS interprétés comme du HTML (pas de XSS). */

const EUR = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' });
const NUM = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const fmtMoney = (n) => EUR.format(n ?? 0);
export const fmtNumber = (n) => NUM.format(n ?? 0);
export const fmtSigned = (n) => (n > 0 ? '+' : '') + fmtMoney(n);

/** h('div', {class:'x', onClick: fn, style:{color:'red'}}, 'texte', autreNoeud, [liste]) */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style' && typeof value === 'object') {
      for (const [prop, v] of Object.entries(value)) {
        if (prop.startsWith('--')) el.style.setProperty(prop, v); else el.style[prop] = v;
      }
    } else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key in el && key !== 'list') el[key] = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  append(el, children);
  return el;
}

function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const tone = (value) => (value >= 0 ? 'var(--green)' : 'var(--red)');

/** Remplit un <select> en conservant la valeur courante si elle existe encore. options: [valeur | [valeur, libellé]] */
export function fillSelect(select, options, fallback) {
  const previous = select.value;
  select.replaceChildren(...options.map((o) => {
    const [value, label] = Array.isArray(o) ? o : [o, o];
    return h('option', { value }, label);
  }));
  const values = options.map((o) => String(Array.isArray(o) ? o[0] : o));
  if (values.includes(previous)) select.value = previous;
  else if (fallback !== undefined && values.includes(String(fallback))) select.value = String(fallback);
}

/** Champ étiqueté : field('Montant', input) */
export const field = (label, control, extra = '') => h('label', { class: `field ${extra}` }, h('span', null, label), control);

/** Bande de soldes (Total général + 1 carte par compte). */
export function renderBalanceCards(container, state, compact = false) {
  const card = (label, value, extra = '') => h('div', { class: `bcard ${extra} ${compact ? 'compact' : ''}`, style: { '--tone': tone(value) } },
    h('div', { class: 'bcard-label' }, label),
    h('div', { class: 'bcard-value' }, fmtMoney(value)));
  container.replaceChildren(
    card('🌐 Total général', state.total, 'total'),
    ...state.accounts.map((a) => card(a.name, state.balances[a.name] ?? 0)),
  );
}

/** Notification temporaire, avec action facultative (ex. « Annuler »). */
export function toast(message, { type = 'ok', actionLabel, onAction, duration = 4500 } = {}) {
  const box = document.getElementById('toasts');
  const close = () => el.remove();
  const el = h('div', { class: `toast ${type === 'error' ? 'error' : ''}`, role: type === 'error' ? 'alert' : 'status' },
    h('span', null, message),
    actionLabel && h('button', { type: 'button', onClick: () => { close(); onAction?.(); } }, actionLabel));
  box.append(el);
  setTimeout(close, type === 'error' ? 8000 : duration);
}

export const errorMessage = (err) => (err && err.message) || 'Une erreur est survenue.';
