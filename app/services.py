"""Logique métier (sans dépendance web : testable avec la seule bibliothèque standard).

Règles reprises de l'application Streamlit :
  solde(compte) = solde_initial + Entrées − Sorties − Transferts sortants + Transferts entrants

Multi-utilisateurs : TOUTES les fonctions de données prennent `uid` et filtrent sur `user_id`.
Un utilisateur ne peut ni lire, ni modifier, ni supprimer les données d'un autre (un identifiant de
transaction appartenant à autrui est traité comme « introuvable » : 404).
"""
import csv
import datetime as dt
import io
import re
import sqlite3

from . import constants as C
from . import db, security
from .money import from_cents, to_cents

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
USERNAME_RE = re.compile(r"^[\w][\w .@'\-]*$")
CSV_HEADER = ["ID", "Date", "Jour", "Mois", "Année", "Type", "Compte", "Compte Cible",
              "Catégorie", "Nom", "Montant"]  # mêmes colonnes que l'export Streamlit


class ServiceError(Exception):
    """Erreur métier convertie en réponse HTTP {detail: message}."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


# =============================================================== utilisateurs
def _user(row) -> dict:
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"]),
            "has_password": bool(row["password_hash"])}


def get_user(conn, uid: int) -> dict | None:
    row = conn.execute("SELECT id, username, password_hash, is_admin FROM users WHERE id = ?", (uid,)).fetchone()
    return _user(row) if row else None


def find_user(conn, username: str):
    """Ligne complète (avec password_hash) pour la connexion ; identifiant insensible à la casse."""
    return conn.execute("SELECT id, username, password_hash, is_admin FROM users WHERE username = ?",
                        ((username or "").strip(),)).fetchone()


def count_users(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users(conn) -> list[dict]:
    rows = conn.execute("SELECT id, username, password_hash, is_admin FROM users ORDER BY is_admin DESC, username")
    return [_user(r) for r in rows]


def auth_required(conn) -> bool:
    """Connexion obligatoire dès qu'il y a plusieurs utilisateurs, ou si l'unique utilisateur a un mot de passe.
    Sinon (un seul utilisateur sans mot de passe) : accès libre, comme l'ancienne appli sans mot de passe."""
    if count_users(conn) > 1:
        return True
    row = conn.execute("SELECT password_hash FROM users").fetchone()
    return bool(row and row["password_hash"])


def open_mode_user(conn) -> dict | None:
    """Utilisateur implicite en accès libre (None s'il y en a plusieurs)."""
    if count_users(conn) != 1:
        return None
    return _user(conn.execute("SELECT id, username, password_hash, is_admin FROM users").fetchone())


def _require_admin(conn, actor_id: int) -> dict:
    actor = get_user(conn, actor_id)
    if actor is None or not actor["is_admin"]:
        raise ServiceError("Action réservée aux administrateurs.", 403)
    return actor


def _clean_username(username: str) -> str:
    name = " ".join((username or "").split())   # espaces superflus supprimés
    if not 1 <= len(name) <= 40 or not USERNAME_RE.match(name):
        raise ServiceError("Identifiant invalide : 1 à 40 caractères (lettres, chiffres, espaces, . _ @ ' -).")
    return name


def create_user(conn, actor_id: int, username: str, password: str, is_admin: bool = False) -> list[dict]:
    actor = _require_admin(conn, actor_id)
    if not actor["has_password"]:
        raise ServiceError("Définissez d'abord un mot de passe pour votre propre profil "
                           "avant d'ajouter des utilisateurs (sinon n'importe qui pourrait se connecter en votre nom).")
    name = _clean_username(username)
    if not (password or "").strip():
        raise ServiceError("Le mot de passe ne peut pas être vide.")
    if find_user(conn, name):
        raise ServiceError("Cet identifiant existe déjà.", 409)
    with conn:
        uid = db.create_user_row(conn, name, security.hash_password(password), is_admin)
        db.seed_user_defaults(conn, uid)
        db.ensure_system_categories(conn)
    return list_users(conn)


def delete_user(conn, actor_id: int, target_id: int) -> list[dict]:
    """Supprime l'utilisateur ET toutes ses données (comptes, catégories, transactions, sessions)."""
    _require_admin(conn, actor_id)
    if target_id == actor_id:
        raise ServiceError("Vous ne pouvez pas supprimer votre propre utilisateur.")
    if get_user(conn, target_id) is None:
        raise ServiceError("Utilisateur introuvable.", 404)
    with conn:
        for table in ("sessions", "transactions", "accounts", "categories"):  # explicite, sans dépendre de ON DELETE CASCADE
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (target_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (target_id,))
    return list_users(conn)


def reset_user_password(conn, actor_id: int, target_id: int, password: str) -> list[dict]:
    """Un administrateur définit un nouveau mot de passe pour un autre utilisateur (ses sessions sont révoquées)."""
    _require_admin(conn, actor_id)
    if target_id == actor_id:
        raise ServiceError("Pour votre propre mot de passe, utilisez « Sécurité & mot de passe ».")
    if get_user(conn, target_id) is None:
        raise ServiceError("Utilisateur introuvable.", 404)
    if not (password or "").strip():
        raise ServiceError("Le mot de passe ne peut pas être vide.")
    with conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(password), target_id))
    security.delete_user_sessions(conn, target_id)
    return list_users(conn)


def set_password(conn, uid: int, enabled: bool, password: str | None) -> bool:
    """Active / modifie / désactive le mot de passe de `uid`. Retourne `auth_required` après modification."""
    with conn:
        if not enabled:
            if count_users(conn) > 1:
                raise ServiceError("Impossible de désactiver la protection tant que d'autres utilisateurs existent.")
            conn.execute("UPDATE users SET password_hash = '' WHERE id = ?", (uid,))
        elif password is not None:
            if password.strip() == "":
                raise ServiceError("Le mot de passe ne peut pas être vide.")
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(password), uid))
        elif not (get_user(conn, uid) or {}).get("has_password"):
            raise ServiceError("Définissez un mot de passe pour activer la protection.")
    return auth_required(conn)


# =============================================================== comptes & catégories
def get_accounts(conn, uid: int):
    rows = conn.execute("SELECT name, initial_cents FROM accounts WHERE user_id = ? ORDER BY position, name", (uid,))
    return [{"name": r["name"], "initial_balance": from_cents(r["initial_cents"])} for r in rows]


def get_categories(conn, uid: int):
    rows = conn.execute("SELECT name, color, system FROM categories WHERE user_id = ? ORDER BY system, position, name", (uid,))
    return [{"name": r["name"], "color": r["color"], "system": bool(r["system"])} for r in rows]


def compute_balances(conn, uid: int, before: str | None = None) -> dict[str, int]:
    """Soldes en centimes, calculés par SQL (équivalent du groupby pandas d'origine).
    `before` (AAAA-MM-JJ) limite aux transactions strictement antérieures à cette date."""
    cond = "AND date < :before" if before else ""
    sql = f"""
        SELECT a.name AS name,
               a.initial_cents
             + COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE user_id = :uid AND type = 'Entrée'    AND account = a.name {cond}), 0)
             - COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE user_id = :uid AND type = 'Sortie'    AND account = a.name {cond}), 0)
             - COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE user_id = :uid AND type = 'Transfert' AND account = a.name {cond}), 0)
             + COALESCE((SELECT SUM(amount_cents) FROM transactions
                          WHERE user_id = :uid AND type = 'Transfert' AND target_account = a.name {cond}), 0) AS cents
        FROM accounts a WHERE a.user_id = :uid ORDER BY a.position, a.name
    """
    return {r["name"]: r["cents"] for r in conn.execute(sql, {"uid": uid, "before": before})}


def balances_payload(conn, uid: int) -> dict:
    balances = compute_balances(conn, uid)
    return {"balances": {k: from_cents(v) for k, v in balances.items()},
            "total": from_cents(sum(balances.values()))}


def snapshot(conn, uid: int) -> dict:
    """Configuration + soldes : renvoyé après chaque modification des paramètres."""
    cats = get_categories(conn, uid)
    return {"accounts": get_accounts(conn, uid), "categories": cats,
            "category_colors": {c["name"]: c["color"] for c in cats},
            **balances_payload(conn, uid)}


def available_years(conn, uid: int, today: dt.date | None = None) -> list[int]:
    """2020 → année courante + 4 (comme l'original), étendu si des données plus anciennes existent."""
    current = (today or dt.date.today()).year
    row = conn.execute("SELECT MIN(substr(date, 1, 4)) AS m FROM transactions WHERE user_id = ?", (uid,)).fetchone()
    first = min(2020, int(row["m"])) if row["m"] else 2020
    return list(range(first, current + 5))


def bootstrap_payload(conn, user: dict, db_encrypted: bool = False) -> dict:
    uid = user["id"]
    return {**snapshot(conn, uid), "years": available_years(conn, uid),
            "transactions": list_transactions(conn, uid),
            "password_enabled": auth_required(conn),
            "user": user, "users_count": count_users(conn),
            "db_encrypted": db_encrypted}       # information d'affichage (Paramètres) ; l'application ne la « décide » pas


def add_account(conn, uid: int, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ServiceError("Le nom du compte ne peut pas être vide.")
    if conn.execute("SELECT 1 FROM accounts WHERE user_id = ? AND name = ?", (uid, name)).fetchone():
        raise ServiceError("Ce compte existe déjà.", 409)
    with conn:
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM accounts WHERE user_id = ?", (uid,)).fetchone()[0]
        conn.execute("INSERT INTO accounts(user_id, name, position, initial_cents) VALUES(?, ?, ?, 0)", (uid, name, pos))
    return snapshot(conn, uid)


def set_initial_balance(conn, uid: int, name: str, value: float) -> dict:
    try:
        cents = to_cents(value)
    except ValueError:
        raise ServiceError("Solde initial invalide.")
    with conn:
        cur = conn.execute("UPDATE accounts SET initial_cents = ? WHERE user_id = ? AND name = ?", (cents, uid, name))
    if cur.rowcount == 0:
        raise ServiceError("Compte introuvable.", 404)
    return snapshot(conn, uid)


def delete_account(conn, uid: int, name: str) -> dict:
    """Comme l'original : les transactions existantes ne sont pas supprimées."""
    if conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id = ?", (uid,)).fetchone()[0] <= 1:
        raise ServiceError("Vous devez conserver au moins un compte.")
    with conn:
        cur = conn.execute("DELETE FROM accounts WHERE user_id = ? AND name = ?", (uid, name))
    if cur.rowcount == 0:
        raise ServiceError("Compte introuvable.", 404)
    return snapshot(conn, uid)


def _check_color(color: str) -> str:
    if not isinstance(color, str) or not HEX_COLOR.match(color):
        raise ServiceError("Couleur invalide (format attendu : #RRGGBB).")
    return color.upper()


def add_category(conn, uid: int, name: str, color: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ServiceError("Le nom de la catégorie ne peut pas être vide.")
    if name == C.INTERNAL_CATEGORY:
        raise ServiceError(f"« {C.INTERNAL_CATEGORY} » est réservée aux transferts.")
    color = _check_color(color)
    if conn.execute("SELECT 1 FROM categories WHERE user_id = ? AND name = ?", (uid, name)).fetchone():
        raise ServiceError("Cette catégorie existe déjà.", 409)
    with conn:
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM categories WHERE user_id = ? AND system = 0",
                           (uid,)).fetchone()[0]
        conn.execute("INSERT INTO categories(user_id, name, position, color, system) VALUES(?, ?, ?, ?, 0)",
                     (uid, name, pos, color))
    return snapshot(conn, uid)


def set_category_color(conn, uid: int, name: str, color: str) -> dict:
    color = _check_color(color)
    with conn:
        cur = conn.execute("UPDATE categories SET color = ? WHERE user_id = ? AND name = ?", (color, uid, name))
    if cur.rowcount == 0:
        raise ServiceError("Catégorie introuvable.", 404)
    return snapshot(conn, uid)


def delete_category(conn, uid: int, name: str) -> dict:
    """Comme l'original : les transactions existantes gardent le nom de la catégorie supprimée."""
    row = conn.execute("SELECT system FROM categories WHERE user_id = ? AND name = ?", (uid, name)).fetchone()
    if row is None:
        raise ServiceError("Catégorie introuvable.", 404)
    if row["system"]:
        raise ServiceError("Cette catégorie système ne peut pas être supprimée.")
    if conn.execute("SELECT COUNT(*) FROM categories WHERE user_id = ? AND system = 0", (uid,)).fetchone()[0] <= 1:
        raise ServiceError("Vous devez conserver au moins une catégorie.")
    with conn:
        conn.execute("DELETE FROM categories WHERE user_id = ? AND name = ?", (uid, name))
    return snapshot(conn, uid)


# =============================================================== transactions
_TX_COLUMNS = "id, date, type, account, target_account, category, name, amount_cents"


def _tx(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "date": r["date"], "type": r["type"], "account": r["account"],
            "target_account": r["target_account"], "category": r["category"],
            "name": r["name"], "amount": from_cents(r["amount_cents"])}


def list_transactions(conn, uid: int) -> list[dict]:
    return [_tx(r) for r in conn.execute(
        f"SELECT {_TX_COLUMNS} FROM transactions WHERE user_id = ? ORDER BY date DESC, id DESC", (uid,))]


def get_transaction(conn, uid: int, tx_id: int) -> dict:
    row = conn.execute(f"SELECT {_TX_COLUMNS} FROM transactions WHERE id = ? AND user_id = ?", (tx_id, uid)).fetchone()
    if row is None:  # inexistante OU appartenant à un autre utilisateur : même réponse
        raise ServiceError("Transaction introuvable.", 404)
    return _tx(row)


def _validate_tx(conn, uid: int, data: dict, current: dict | None = None) -> tuple:
    """Valide et normalise ; retourne le tuple prêt à insérer (sans id ni user_id)."""
    d = data.get("date")
    try:
        iso = d.isoformat() if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)).isoformat()
    except ValueError:
        raise ServiceError("Date invalide.")

    ttype = data.get("type")
    if ttype not in C.TX_TYPES:
        raise ServiceError("Type de transaction invalide.")

    try:
        cents = to_cents(data.get("amount"))
    except ValueError:
        raise ServiceError("Montant invalide.")
    if cents < 1:
        raise ServiceError("Le montant doit être d'au moins 0,01 €.")

    accounts = {a["name"] for a in get_accounts(conn, uid)}
    account = data.get("account")
    if account not in accounts:
        raise ServiceError("Compte inconnu.")
    name = (data.get("name") or "").strip()

    if ttype == C.TX_TRANSFERT:
        target = data.get("target_account")
        if target not in accounts:
            raise ServiceError("Compte d'arrivée inconnu.")
        if target == account:
            raise ServiceError("Le compte de départ et d'arrivée ne peuvent pas être les mêmes.")
        category = C.INTERNAL_CATEGORY
    else:
        target = None
        category = data.get("category")
        known = {c["name"] for c in get_categories(conn, uid) if not c["system"]}
        # Une catégorie supprimée reste acceptée si la transaction la portait déjà (édition d'un ancien enregistrement).
        if category not in known and not (current and current["category"] == category):
            raise ServiceError("Catégorie inconnue.")
    return (iso, ttype, account, target, category, name, cents)


def create_transaction(conn, uid: int, data: dict) -> dict:
    row = _validate_tx(conn, uid, data)
    with conn:
        cur = conn.execute(
            "INSERT INTO transactions(user_id, date, type, account, target_account, category, name, amount_cents) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)", (uid, *row))
    return get_transaction(conn, uid, cur.lastrowid)


def update_transaction(conn, uid: int, tx_id: int, data: dict) -> dict:
    current = get_transaction(conn, uid, tx_id)  # 404 si absente ou si elle appartient à un autre utilisateur
    row = _validate_tx(conn, uid, data, current)
    with conn:
        conn.execute(
            "UPDATE transactions SET date=?, type=?, account=?, target_account=?, category=?, name=?, "
            "amount_cents=? WHERE id=? AND user_id=?", (*row, tx_id, uid))
    return get_transaction(conn, uid, tx_id)


def delete_transaction(conn, uid: int, tx_id: int) -> None:
    with conn:
        cur = conn.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, uid))
    if cur.rowcount == 0:
        raise ServiceError("Transaction introuvable.", 404)


def clear_transactions(conn, uid: int) -> None:
    with conn:
        conn.execute("DELETE FROM transactions WHERE user_id = ?", (uid,))


# =============================================================== dashboard
def _bounds(year: int, month: int | None = None) -> tuple[str, str]:
    """[début, fin[ de l'année ou du mois, en ISO (les dates ISO se comparent comme du texte)."""
    if month is None:
        return dt.date(year, 1, 1).isoformat(), dt.date(year + 1, 1, 1).isoformat()
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dt.date(year, month, 1).isoformat(), dt.date(end_year, end_month, 1).isoformat()


def _flow(conn, uid: int, start: str, end: str) -> dict:
    rows = conn.execute(
        "SELECT type, SUM(amount_cents) AS s FROM transactions "
        "WHERE user_id = ? AND type IN ('Entrée', 'Sortie') AND date >= ? AND date < ? GROUP BY type", (uid, start, end))
    sums = {r["type"]: r["s"] for r in rows}
    e, s = sums.get(C.TX_ENTREE, 0), sums.get(C.TX_SORTIE, 0)
    return {"entrees": from_cents(e), "sorties": from_cents(s), "net": from_cents(e - s)}


def _by_category(conn, uid: int, ttype: str, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT category, SUM(amount_cents) AS s FROM transactions "
        "WHERE user_id = ? AND type = ? AND date >= ? AND date < ? GROUP BY category ORDER BY s DESC, category",
        (uid, ttype, start, end))
    return [{"category": r["category"], "amount": from_cents(r["s"])} for r in rows]


def _averages(conn, uid: int, ttype: str, start: str, end: str) -> dict:
    """Moyenne mensuelle par catégorie = total annuel / nb de mois ayant au moins une transaction de ce type."""
    months = conn.execute(
        "SELECT COUNT(DISTINCT substr(date, 1, 7)) FROM transactions "
        "WHERE user_id = ? AND type = ? AND date >= ? AND date < ?", (uid, ttype, start, end)).fetchone()[0]
    items = []
    if months:
        rows = conn.execute(
            "SELECT category, SUM(amount_cents) AS s FROM transactions "
            "WHERE user_id = ? AND type = ? AND date >= ? AND date < ? GROUP BY category", (uid, ttype, start, end))
        items = [{"category": r["category"], "total": from_cents(r["s"]),
                  "average": round(r["s"] / months / 100, 2)} for r in rows]
        items.sort(key=lambda i: (-i["average"], i["category"]))
    return {"months": months, "items": items}


def _evolution(conn, uid: int, start: str, end: str) -> dict:
    """Solde de chaque compte après chaque jour comportant au moins une transaction.

    CORRECTION par rapport à l'original : la courbe part du solde réel au 1er janvier
    (soldes initiaux + transactions des années précédentes) et non des seuls soldes initiaux,
    de sorte que le dernier point correspond bien au solde affiché dans les cartes."""
    accounts = [a["name"] for a in get_accounts(conn, uid)]
    running = compute_balances(conn, uid, before=start)
    dates: list[str] = []
    series: dict[str, list[float]] = {a: [] for a in accounts}

    def flush(day: str) -> None:
        dates.append(day)
        for a in accounts:
            series[a].append(from_cents(running[a]))

    rows = conn.execute(
        "SELECT date, type, account, target_account, amount_cents FROM transactions "
        "WHERE user_id = ? AND date >= ? AND date < ? ORDER BY date, id", (uid, start, end))
    last = None
    for r in rows:
        if last is not None and r["date"] != last:
            flush(last)
        last = r["date"]
        amount, src, tgt = r["amount_cents"], r["account"], r["target_account"]
        if r["type"] == C.TX_ENTREE and src in running:
            running[src] += amount
        elif r["type"] == C.TX_SORTIE and src in running:
            running[src] -= amount
        elif r["type"] == C.TX_TRANSFERT:
            if src in running:
                running[src] -= amount
            if tgt in running:
                running[tgt] += amount
    if last is not None:
        flush(last)
    return {"dates": dates, "series": [{"account": a, "values": series[a]} for a in accounts]}


def dashboard(conn, uid: int, year: int, month: int) -> dict:
    ys, ye = _bounds(year)
    ms, me = _bounds(year, month)
    total = conn.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ?", (uid,)).fetchone()[0]
    return {
        "year": year, "month": month, "has_data": total > 0,
        "month_flow": _flow(conn, uid, ms, me), "year_flow": _flow(conn, uid, ys, ye),
        "month_expenses": _by_category(conn, uid, C.TX_SORTIE, ms, me),
        "month_income": _by_category(conn, uid, C.TX_ENTREE, ms, me),
        "year_expenses": _by_category(conn, uid, C.TX_SORTIE, ys, ye),
        "year_income": _by_category(conn, uid, C.TX_ENTREE, ys, ye),
        "evolution": _evolution(conn, uid, ys, ye),
        "avg_expenses": _averages(conn, uid, C.TX_SORTIE, ys, ye),
        "avg_income": _averages(conn, uid, C.TX_ENTREE, ys, ye),
    }


# =============================================================== export CSV
def export_csv(conn, uid: int) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for r in conn.execute(f"SELECT {_TX_COLUMNS} FROM transactions WHERE user_id = ? ORDER BY id", (uid,)):
        y, m, d = r["date"].split("-")
        writer.writerow([r["id"], r["date"], int(d), int(m), int(y), r["type"], r["account"],
                         r["target_account"] or "", r["category"], r["name"],
                         f"{r['amount_cents'] / 100:.2f}"])
    return out.getvalue()
