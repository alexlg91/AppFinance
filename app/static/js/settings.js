/* Vue « Paramètres » : mon mot de passe, utilisateurs (admin), comptes, catégories, export CSV, réinitialisation.
   Comptes, catégories et données sont ceux de l'utilisateur connecté (chaque utilisateur a les siens). */
import { api } from './api.js';
import { state, applySnapshot, applyBalances } from './store.js';
import { h, toast, errorMessage } from './ui.js';

export function createSettings(root, { simulator, onAuthChanged }) {
  let wantsPassword = null;   // état de la case à cocher tant qu'elle n'est pas enregistrée
  let users = null;           // liste des utilisateurs (administrateur uniquement), chargée à l'ouverture
  let resettingId = null;     // utilisateur dont on est en train de réinitialiser le mot de passe

  /** Applique la réponse de PUT /settings/password à l'état local. */
  function applyPasswordResult(res) {
    state.user.has_password = res.has_password;
    state.protected = res.password_enabled;
    wantsPassword = null;
    onAuthChanged();
    render();
  }

  function applyUsers(res) {
    users = res.users;
    state.usersCount = users.length;
    onAuthChanged();
  }

  /** Exécute une action API, affiche le succès ou l'erreur, puis redessine la page. */
  async function run(action, successMessage) {
    try {
      const result = await action();
      if (successMessage) toast(successMessage);
      return result ?? true;
    } catch (err) {
      toast(errorMessage(err), { type: 'error' });
      return null;
    }
  }

  // ------------------------------------------------------------------ sécurité (MON mot de passe)
  function securitySection() {
    const pwd = h('input', { type: 'password', autocomplete: 'new-password', placeholder: 'Nouveau mot de passe' });
    const save = (label, okMessage) => h('form', {
      class: 'inline', style: { marginTop: '.7rem' },
      onSubmit: async (e) => {
        e.preventDefault();
        if (!pwd.value.trim()) { toast('Le mot de passe ne peut pas être vide.', { type: 'error' }); return; }
        const res = await run(() => api.setPassword(true, pwd.value), okMessage);
        if (res) applyPasswordResult(res);
      },
    }, pwd, h('button', { class: 'btn primary', type: 'submit' }, label));

    // Plusieurs utilisateurs : la connexion est obligatoire, on peut seulement changer son mot de passe.
    if (state.usersCount > 1) {
      return h('section', { class: 'panel' },
        h('h3', null, '🔒 Mon mot de passe'),
        h('p', { class: 'muted', style: { margin: 0 } }, `Connecté en tant que « ${state.user.username} ». Changer le mot de passe vous déconnecte de vos autres appareils.`),
        save('💾 Changer mon mot de passe', 'Mot de passe mis à jour (haché en SHA-256).'));
    }

    const has = state.user.has_password;
    const checked = wantsPassword ?? has;
    const box = h('input', { type: 'checkbox', checked, onChange: (e) => { wantsPassword = e.target.checked; render(); } });
    return h('section', { class: 'panel' },
      h('h3', null, '🔒 Sécurité & mot de passe'),
      h('label', { class: 'inline' }, box, 'Activer la protection par mot de passe au lancement'),
      checked && save('💾 Enregistrer le mot de passe', 'Mot de passe mis à jour (haché en SHA-256).'),
      !checked && has && h('div', { style: { marginTop: '.7rem' } },
        h('button', {
          class: 'btn', type: 'button',
          onClick: async () => {
            const res = await run(() => api.setPassword(false), "Protection désactivée : l'application est en accès libre.");
            if (res) applyPasswordResult(res);
          },
        }, '🔓 Désactiver la protection')),
      !has && !checked && h('p', { class: 'muted', style: { margin: '.6rem 0 0', fontSize: '.85rem' } },
        "Sans mot de passe, l'application est en accès libre. Activez-le pour pouvoir ajouter d'autres utilisateurs."));
  }

  // ------------------------------------------------------------------ utilisateurs (administrateurs)
  async function refreshUsers() {
    try { applyUsers(await api.users()); render(); } catch (err) { if (err.status !== 401) toast(errorMessage(err), { type: 'error' }); }
  }

  function usersSection() {
    const name = h('input', { type: 'text', placeholder: 'Identifiant', maxLength: 40, autocomplete: 'off', 'aria-label': 'Identifiant du nouvel utilisateur' });
    const pwd = h('input', { type: 'password', placeholder: 'Mot de passe', autocomplete: 'new-password', 'aria-label': 'Mot de passe du nouvel utilisateur' });
    const admin = h('input', { type: 'checkbox' });

    const row = (u) => {
      const me = u.id === state.user.id;
      const newPwd = h('input', { type: 'password', placeholder: `Nouveau mot de passe pour ${u.username}`, autocomplete: 'new-password' });
      return [
        h('div', { class: 'user-row' },
          h('span', { class: 'cat-name' }, u.username,
            u.is_admin && h('span', { class: 'badge admin' }, 'admin'), me && h('span', { class: 'badge' }, 'vous')),
          !me && h('div', { class: 'user-actions' },
            h('button', { class: 'btn small', type: 'button', onClick: () => { resettingId = resettingId === u.id ? null : u.id; render(); } }, '🔑 Mot de passe'),
            h('button', {
              class: 'btn small danger', type: 'button',
              onClick: async () => {
                if (!confirm(`Supprimer l'utilisateur « ${u.username} » ET toutes ses données (comptes, catégories, transactions) ?\nCette action est irréversible.`)) return;
                const res = await run(() => api.deleteUser(u.id), `Utilisateur « ${u.username} » supprimé.`);
                if (res) { applyUsers(res); render(); }
              },
            }, '🗑️ Supprimer'))),
        !me && resettingId === u.id && h('form', {
          class: 'reset-form',
          onSubmit: async (e) => {
            e.preventDefault();
            const res = await run(() => api.resetUserPassword(u.id, newPwd.value), `Mot de passe de « ${u.username} » modifié ; il est déconnecté.`);
            if (res) { applyUsers(res); resettingId = null; render(); }
          },
        }, newPwd, h('button', { class: 'btn primary', type: 'submit' }, 'Enregistrer')),
      ];
    };

    return h('section', { class: 'panel' },
      h('h3', null, '👥 Utilisateurs'),
      h('p', { class: 'muted', style: { margin: '0 0 .5rem', fontSize: '.85rem' } },
        'Chaque utilisateur a ses propres comptes, catégories et transactions : rien n’est partagé.'),
      users === null ? h('p', { class: 'muted' }, 'Chargement…') : users.map(row),
      h('hr'),
      state.user.has_password
        ? [h('p', { style: { margin: '0 0 .4rem', fontWeight: 600 } }, 'Ajouter un utilisateur'),
          h('form', {
            class: 'inline',
            onSubmit: async (e) => {
              e.preventDefault();
              const res = await run(() => api.createUser(name.value, pwd.value, admin.checked), `Utilisateur « ${name.value.trim()} » créé.`);
              if (res) { applyUsers(res); render(); }
            },
          }, name, pwd, h('label', { class: 'inline' }, admin, 'Administrateur'),
          h('button', { class: 'btn', type: 'submit' }, '➕ Créer l’utilisateur'))]
        : h('p', { class: 'empty' }, 'Définissez d’abord votre mot de passe (section « Sécurité ») pour pouvoir ajouter des utilisateurs : sinon n’importe qui pourrait se connecter à votre place.'));
  }

  // ------------------------------------------------------------------ comptes
  function accountsSection() {
    const newName = h('input', { type: 'text', placeholder: 'Ex : Livret Jeune', maxLength: 120 });
    const toDelete = h('select', null, ...state.accounts.map((a) => h('option', { value: a.name }, a.name)));

    return h('section', { class: 'panel' },
      h('h3', null, '💳 Gestion des comptes'),
      h('p', { style: { margin: '0 0 .4rem', fontWeight: 600 } }, 'Soldes de départ'),
      ...state.accounts.map((a) => {
        const input = h('input', {
          type: 'number', step: 'any', value: String(a.initial_balance), 'aria-label': `Solde initial de ${a.name}`,
          onChange: async () => {
            const value = parseFloat(input.value);
            if (!Number.isFinite(value)) { input.value = String(a.initial_balance); return; }
            const snap = await run(() => api.setInitialBalance(a.name, value), 'Soldes de départ mis à jour.');
            if (snap) { applySnapshot(snap); simulator.refresh(); } else input.value = String(a.initial_balance);
          },
        });
        return h('div', { class: 'setting-row' }, h('span', { class: 'cat-name' }, `Solde initial — ${a.name}`), input);
      }),
      h('hr'),
      h('form', {
        class: 'inline',
        onSubmit: async (e) => {
          e.preventDefault();
          const snap = await run(() => api.addAccount(newName.value), `Compte « ${newName.value.trim()} » créé.`);
          if (snap) { applySnapshot(snap); render(); }
        },
      }, newName, h('button', { class: 'btn', type: 'submit' }, '➕ Créer le compte')),
      h('hr'),
      h('div', { class: 'inline' }, toDelete,
        h('button', {
          class: 'btn danger', type: 'button',
          onClick: async () => {
            const name = toDelete.value;
            if (!confirm(`Supprimer le compte « ${name} » ?\nSes transactions sont conservées mais ne compteront plus dans les soldes.`)) return;
            const snap = await run(() => api.deleteAccount(name), `Compte « ${name} » supprimé.`);
            if (snap) { applySnapshot(snap); render(); }
          },
        }, '❌ Supprimer ce compte')));
  }

  // ------------------------------------------------------------------ catégories
  function categoriesSection() {
    const newName = h('input', { type: 'text', placeholder: 'Ex : Loisirs', maxLength: 120, 'aria-label': 'Nom de la catégorie' });
    const newColor = h('input', { type: 'color', value: '#3b82f6', 'aria-label': 'Couleur de la nouvelle catégorie' });

    return h('section', { class: 'panel' },
      h('h3', null, '🏷️ Catégories & couleurs'),
      ...state.categories.filter((c) => !c.system).map((c) => h('div', { class: 'cat-row' },
        h('span', { class: 'cat-name', style: { color: c.color } }, c.name),
        h('input', {
          type: 'color', value: c.color.toLowerCase(), 'aria-label': `Couleur de ${c.name}`,
          onChange: async (e) => {
            const snap = await run(() => api.setCategoryColor(c.name, e.target.value), 'Couleur mise à jour.');
            if (snap) { applySnapshot(snap); render(); }
          },
        }),
        h('button', {
          class: 'btn ghost small', type: 'button', title: `Supprimer ${c.name}`, 'aria-label': `Supprimer ${c.name}`,
          onClick: async () => {
            if (!confirm(`Supprimer la catégorie « ${c.name} » ?\nLes transactions existantes la conservent.`)) return;
            const snap = await run(() => api.deleteCategory(c.name), `Catégorie « ${c.name} » supprimée.`);
            if (snap) { applySnapshot(snap); render(); }
          },
        }, '❌'))),
      h('hr'),
      h('p', { style: { margin: '0 0 .4rem', fontWeight: 600 } }, 'Ajouter une catégorie'),
      h('form', {
        class: 'inline',
        onSubmit: async (e) => {
          e.preventDefault();
          const snap = await run(() => api.addCategory(newName.value, newColor.value), `Catégorie « ${newName.value.trim()} » ajoutée.`);
          if (snap) { applySnapshot(snap); render(); }
        },
      }, newName, newColor, h('button', { class: 'btn', type: 'submit' }, '➕ Ajouter la catégorie')));
  }

  // ------------------------------------------------------------------ stockage (information : le chiffrement se configure côté serveur)
  function storageSection() {
    return h('section', { class: 'panel', id: 'storage-status' },
      h('h3', null, state.dbEncrypted ? '🔐 Base de données chiffrée' : '🔓 Base de données non chiffrée'),
      h('p', { class: 'muted', style: { margin: 0 } }, state.dbEncrypted
        ? 'Les fichiers de l’application sur le serveur (NAS) sont chiffrés au repos (AES-256) : ils ne sont pas lisibles sans la clé.'
        : 'Les données sont stockées en clair dans les fichiers du serveur. Pour les chiffrer, configurez une clé (section « Chiffrement de la base » du README).'),
      state.legacyJsonInClear && h('p', { class: 'warn', role: 'alert' },
        '⚠ L’ancien fichier banque_data.json (toutes vos données, en clair) est toujours dans le dossier de données du serveur. '
        + 'Il n’est plus utilisé : gardez-en une copie hors du NAS si besoin, puis supprimez-le du dossier data/.'));
  }

  // ------------------------------------------------------------------ export & danger
  function dataSection() {
    return h('section', { class: 'panel' },
      h('h3', null, '💾 Exporter vos données'),
      state.transactions.length
        ? h('a', { class: 'btn', href: '/api/export.csv', download: '' }, '📥 Télécharger mes transactions (CSV)')
        : h('div', { class: 'empty' }, 'Aucune donnée à exporter pour le moment.'),
      h('hr'),
      h('h3', null, '⚠️ Zone de danger'),
      h('button', {
        class: 'btn danger', type: 'button',
        onClick: async () => {
          if (!confirm('Effacer DÉFINITIVEMENT toutes les transactions ?\nCette action est irréversible (pensez à exporter le CSV avant).')) return;
          const res = await run(() => api.clearTx(), 'Toutes les transactions ont été effacées.');
          if (res) { state.transactions = []; applyBalances(res); simulator.refresh(); render(); }
        },
      }, '🚨 Effacer toutes les transactions'));
  }

  function render() {
    root.replaceChildren(
      h('h2', null, 'Paramètres'),
      h('div', { class: 'grid', style: { gap: '1rem' } },
        securitySection(),
        state.user.is_admin && usersSection(),
        storageSection(),
        h('div', { class: 'grid cols-2', style: { gap: '1rem', alignItems: 'start' } },
          accountsSection(),
          h('div', { class: 'grid', style: { gap: '1rem' } }, categoriesSection(), dataSection()))));
  }

  return {
    activate() {
      render();
      if (state.user.is_admin) refreshUsers();   // liste fraîche à chaque ouverture de l'onglet
    },
  };
}
