/* Client de l'API REST. Authentification = cookie de session HttpOnly (géré par le navigateur). */

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

async function request(method, url, body) {
  let res;
  try {
    res = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('Serveur injoignable. Vérifiez la connexion puis réessayez.', 0);
  }
  if (res.status === 401 && !url.startsWith('/api/auth/')) {
    onUnauthorized();                       // session expirée ou révoquée -> écran de verrouillage
    throw new ApiError('Session expirée : reconnectez-vous.', 401);
  }
  if (!res.ok) {
    let detail = `Erreur ${res.status}`;
    try {
      const data = await res.json();
      detail = Array.isArray(data.detail)   // erreurs de validation FastAPI (422)
        ? data.detail.map((d) => d.msg).join(' ; ')
        : data.detail || detail;
    } catch { /* corps non JSON */ }
    throw new ApiError(detail, res.status);
  }
  return res.status === 204 ? null : res.json();
}

const enc = encodeURIComponent;

export const api = {
  status: () => request('GET', '/api/auth/status'),
  login: (username, password) => request('POST', '/api/auth/login', { username, password }),
  logout: () => request('POST', '/api/auth/logout'),
  bootstrap: () => request('GET', '/api/bootstrap'),
  dashboard: (year, month) => request('GET', `/api/dashboard?year=${year}&month=${month}`),

  createTx: (tx) => request('POST', '/api/transactions', tx),
  updateTx: (id, tx) => request('PUT', `/api/transactions/${id}`, tx),
  deleteTx: (id) => request('DELETE', `/api/transactions/${id}`),
  clearTx: () => request('DELETE', '/api/transactions'),

  addAccount: (name) => request('POST', '/api/accounts', { name }),
  setInitialBalance: (name, value) => request('PUT', `/api/accounts/${enc(name)}`, { initial_balance: value }),
  deleteAccount: (name) => request('DELETE', `/api/accounts/${enc(name)}`),

  addCategory: (name, color) => request('POST', '/api/categories', { name, color }),
  setCategoryColor: (name, color) => request('PUT', `/api/categories/${enc(name)}`, { color }),
  deleteCategory: (name) => request('DELETE', `/api/categories/${enc(name)}`),

  setPassword: (enabled, password) => request('PUT', '/api/settings/password', { enabled, password }),

  // administration (réservée aux administrateurs : 403 sinon)
  users: () => request('GET', '/api/users'),
  createUser: (username, password, is_admin) => request('POST', '/api/users', { username, password, is_admin }),
  deleteUser: (id) => request('DELETE', `/api/users/${id}`),
  resetUserPassword: (id, password) => request('PUT', `/api/users/${id}/password`, { password }),
};
