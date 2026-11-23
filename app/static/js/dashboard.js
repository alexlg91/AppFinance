/* Vue « Tableau de bord ». Le serveur agrège (SQL) ; ici on ne fait que dessiner. */
import { api } from './api.js';
import { state, categoryColor } from './store.js';
import { h, field, fmtMoney, fmtNumber, fillSelect, renderBalanceCards, cssVar, tone, toast, errorMessage } from './ui.js';
import { MONTHS, accountColor, shade, fmtDate, sum } from './logic.js';

/** Affiche la valeur au bout de chaque barre horizontale (équivalent de text_auto de Plotly). */
const valueLabels = {
  id: 'valueLabels',
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    ctx.save();
    ctx.fillStyle = cssVar('--text');
    ctx.font = `12px ${cssVar('--font')}`;
    ctx.textBaseline = 'middle';
    chart.getDatasetMeta(0).data.forEach((bar, i) => ctx.fillText(fmtNumber(chart.data.datasets[0].data[i]), bar.x + 6, bar.y));
    ctx.restore();
  },
};

export function createDashboard(root) {
  const now = new Date();
  let charts = [];
  let seq = 0;                 // ignore les réponses obsolètes si l'on change vite de filtre
  let toDraw = [];             // dessins différés : un canvas doit être dans le DOM avant new Chart()

  const yearSel = h('select', { onChange: () => load() });
  const monthSel = h('select', { onChange: () => load() }, ...MONTHS.map((m, i) => h('option', { value: i + 1 }, m)));
  monthSel.value = String(now.getMonth() + 1);
  const cards = h('div', { class: 'balance-strip' });
  const content = h('div');

  root.append(
    h('h2', null, 'Tableau de bord'),
    h('div', { class: 'grid cols-2', style: { marginBottom: '.8rem' } },
      field('Année du Dashboard', yearSel), field('Mois à analyser', monthSel)),
    cards, h('hr'), content);

  function chartDefaults() {
    const C = window.Chart;
    C.defaults.color = cssVar('--text');
    C.defaults.borderColor = cssVar('--border');
    C.defaults.font.family = cssVar('--font');
    C.defaults.animation = matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 250 };
  }

  function destroyCharts() {
    charts.forEach((c) => c.destroy());
    charts = [];
    toDraw = [];
  }

  const draw = (canvas, config, plugins = []) => toDraw.push(() => charts.push(new window.Chart(canvas, { ...config, plugins })));
  const canvasFor = (label) => h('canvas', { role: 'img', 'aria-label': label });

  // ---------------------------------------------------------------- blocs
  function flowCard(title, flow) {
    return h('div', { class: 'flow-card', style: { '--tone': tone(flow.net) } },
      h('div', { class: 't' }, title),
      h('div', { class: 'v' }, fmtMoney(flow.net)),
      h('div', { class: 's' }, `➕ ${fmtMoney(flow.entrees)} | ➖ ${fmtMoney(flow.sorties)}`));
  }

  function donut(title, items, emptyText) {
    if (!items.length) return h('div', null, h('h3', null, title), h('div', { class: 'empty' }, emptyText));
    const total = sum(items.map((i) => i.amount));
    const canvas = canvasFor(title);
    draw(canvas, {
      type: 'doughnut',
      data: {
        labels: items.map((i) => i.category),
        datasets: [{ data: items.map((i) => i.amount), backgroundColor: items.map((i) => categoryColor(i.category)), borderColor: cssVar('--card'), borderWidth: 2 }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '58%',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => ` ${c.label} : ${fmtMoney(c.parsed)} (${(c.parsed / total * 100).toFixed(1)} %)` } },
        },
      },
    });
    return h('div', null,
      h('h3', null, `${title} — ${fmtMoney(total)}`),
      h('div', { class: 'donut-wrap' },
        h('div', { class: 'chart-box' }, canvas),
        h('ul', { class: 'legend' }, ...items.map((i) => h('li', null,
          h('span', { class: 'dot', style: { background: categoryColor(i.category) } }),
          h('span', null, i.category),
          h('span', null, h('span', { class: 'amt' }, fmtMoney(i.amount)), ' ',
            h('span', { class: 'pct' }, `${(i.amount / total * 100).toFixed(0)} %`)))))));
  }

  function evolution(year, ev) {
    const title = h('h3', { class: 'section-title' }, `📈 Évolution des soldes en ${year}`);
    if (!ev.dates.length) return h('div', null, title, h('div', { class: 'empty' }, `Aucune donnée disponible pour l'année ${year}.`));
    const canvas = canvasFor(`Évolution des soldes en ${year}`);
    draw(canvas, {
      type: 'line',
      data: {
        labels: ev.dates.map((d) => fmtDate(d).slice(0, 5)),
        datasets: ev.series.map((s) => ({
          label: s.account, data: s.values, borderColor: accountColor(s.account), backgroundColor: accountColor(s.account),
          pointRadius: 3, borderWidth: 2, tension: 0.15,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: { tooltip: { callbacks: {
          title: (items) => fmtDate(ev.dates[items[0].dataIndex]),
          label: (c) => ` ${c.dataset.label} : ${fmtMoney(c.parsed.y)}`,
        } } },
        scales: { y: { ticks: { callback: (v) => fmtMoney(v) } } },
      },
    });
    return h('div', null, title, h('div', { class: 'chart-box', style: { height: '290px' } }, canvas));
  }

  function averages(title, data, color, emptyText) {
    if (!data.items.length) return h('div', null, h('h3', { class: 'section-title' }, title), h('div', { class: 'empty' }, emptyText));
    const max = Math.max(...data.items.map((i) => i.average));
    const canvas = canvasFor(title);
    draw(canvas, {
      type: 'bar',
      data: {
        labels: data.items.map((i) => i.category),
        datasets: [{ data: data.items.map((i) => i.average), backgroundColor: data.items.map((i) => shade(i.average, max, color)), borderRadius: 3 }],
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false, layout: { padding: { right: 72 } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => [
          ` Moyenne : ${fmtMoney(c.parsed.x)} / mois`, ` Total annuel : ${fmtMoney(data.items[c.dataIndex].total)}`] } } },
        scales: { x: { beginAtZero: true, ticks: { callback: (v) => fmtMoney(v) } } },
      },
    }, [valueLabels]);
    return h('div', null,
      h('h3', { class: 'section-title' }, title),
      h('p', { class: 'muted', style: { margin: '0 0 .3rem' } }, `Moyenne mensuelle, calculée sur ${data.months} mois comportant des mouvements.`),
      h('div', { class: 'chart-box', style: { height: `${Math.max(170, data.items.length * 34 + 50)}px` } }, canvas));
  }

  // ---------------------------------------------------------------- rendu
  function render(d) {
    destroyCharts();
    if (!d.has_data) {
      content.replaceChildren(h('div', { class: 'empty' }, "Aucune transaction enregistrée. Rendez-vous dans l'onglet « Transactions » pour commencer."));
      return;
    }
    if (!window.Chart) {
      content.replaceChildren(h('div', { class: 'empty' }, 'Chart.js est introuvable (static/vendor/chart.umd.js). Lancez « python scripts/fetch_vendor.py » ou reconstruisez l’image Docker.'));
      return;
    }
    chartDefaults();
    const mois = `${MONTHS[d.month - 1]} ${d.year}`;
    content.replaceChildren(
      h('div', { class: 'grid cols-2' },
        h('div', null,
          h('h3', { class: 'section-title', style: { marginTop: 0 } }, `📅 Analyse mensuelle (${mois})`),
          flowCard(`Balance de ${mois}`, d.month_flow),
          donut('Dépenses du mois', d.month_expenses, `Aucune dépense en ${mois}.`),
          h('div', { style: { height: '.8rem' } }),
          donut('Entrées du mois', d.month_income, `Aucune entrée en ${mois}.`)),
        h('div', null,
          h('h3', { class: 'section-title', style: { marginTop: 0 } }, `🗓️ Analyse annuelle (${d.year})`),
          flowCard(`Balance annuelle (${d.year})`, d.year_flow),
          donut("Dépenses de l'année", d.year_expenses, `Aucune dépense en ${d.year}.`),
          h('div', { style: { height: '.8rem' } }),
          donut("Entrées de l'année", d.year_income, `Aucune entrée en ${d.year}.`))),
      evolution(d.year, d.evolution),
      h('div', { class: 'grid cols-2' },
        averages(`🔻 Moyenne des dépenses (${d.year})`, d.avg_expenses, 'red', `Aucune dépense enregistrée en ${d.year}.`),
        averages(`🍏 Moyenne des entrées (${d.year})`, d.avg_income, 'green', `Aucune entrée d'argent enregistrée en ${d.year}.`)));
    toDraw.forEach((fn) => fn());   // les canvas sont maintenant dans le DOM
    toDraw = [];
  }

  async function load() {
    const mine = ++seq;
    try {
      const data = await api.dashboard(+yearSel.value, +monthSel.value);
      if (mine !== seq) return;
      state.dashboardDirty = false;
      render(data);
    } catch (err) {
      if (err.status !== 401) toast(errorMessage(err), { type: 'error' });
    }
  }

  return {
    /** Appelé à chaque affichage de l'onglet : ne recharge que si les données ont changé. */
    activate() {
      fillSelect(yearSel, state.years, now.getFullYear());
      renderBalanceCards(cards, state);
      if (state.dashboardDirty) load();
    },
    invalidate() { state.dashboardDirty = true; },
  };
}
