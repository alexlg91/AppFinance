/* État partagé de l'application (un simple objet : pas de framework nécessaire à cette échelle). */

export const state = {
  accounts: [],            // [{name, initial_balance}]
  categories: [],          // [{name, color, system}]
  colors: {},              // nom de catégorie -> couleur
  balances: {},            // nom de compte -> solde
  total: 0,
  years: [],
  transactions: [],        // toutes les transactions : filtrage et tri se font côté client
  protected: false,        // la connexion est-elle obligatoire (plusieurs utilisateurs ou mot de passe actif) ?
  user: { id: 0, username: '', is_admin: false, has_password: false },   // utilisateur connecté
  usersCount: 1,
  legacyJsonInClear: false, // (admin) un banque_data.json lisible traîne à côté de la base chiffrée
  dbEncrypted: false,      // la base est-elle chiffrée au repos (SQLCipher) ? information affichée dans Paramètres
  dashboardDirty: true,    // le dashboard doit-il être recalculé à la prochaine visite ?
};

/** Catégories modifiables par l'utilisateur (hors « Virement interne »). */
export const userCategories = () => state.categories.filter((c) => !c.system).map((c) => c.name);

export function applySnapshot(s) {
  state.accounts = s.accounts;
  state.categories = s.categories;
  state.colors = s.category_colors;
  state.balances = s.balances;
  state.total = s.total;
  state.dashboardDirty = true;
}

export function applyBalances(r) {
  state.balances = r.balances;
  state.total = r.total;
  state.dashboardDirty = true;
}

export function hydrate(data) {
  applySnapshot(data);
  state.years = data.years;
  state.transactions = data.transactions;
  state.protected = data.password_enabled;
  state.user = data.user;
  state.usersCount = data.users_count;
  state.dbEncrypted = Boolean(data.db_encrypted);
  state.legacyJsonInClear = Boolean(data.legacy_json_in_clear);
}

export const categoryColor = (name) => state.colors[name] || '#9CA3AF';
