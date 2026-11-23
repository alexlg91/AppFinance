"""Import de l'ancien fichier `data/banque_data.json` (format Streamlit) vers SQLite.

Clés lues : comptes, soldes_initiaux, categories, category_colors, transactions,
password_enabled, app_password.  L'ancienne appli n'avait qu'un utilisateur implicite : il devient
l'utilisateur administrateur « Admin », qui reprend toutes les données. Son hash SHA-256 (ou un ancien
mot de passe en clair) est repris tel quel : la vérification à la connexion gère les deux cas.
"""
import datetime as dt
import json
import logging
import math
import re
import sqlite3
from pathlib import Path

from . import constants as C
from .money import to_cents

log = logging.getLogger("banque.migration")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean(value):
    """None et NaN (pandas) -> None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def _unique(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _parse_date(rec: dict) -> str | None:
    raw = _clean(rec.get("Date"))
    if raw:
        try:
            return dt.date.fromisoformat(str(raw)[:10]).isoformat()
        except ValueError:
            pass
    try:  # repli : reconstruction depuis Année/Mois/Jour
        return dt.date(int(rec["Année"]), int(rec["Mois"]), int(rec["Jour"])).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def import_legacy_json(conn: sqlite3.Connection, path) -> dict:
    """Importe le JSON dans `conn` (à appeler dans une transaction). Retourne des statistiques."""
    from .db import INTEGRITY_ERRORS, create_user_row  # import local : évite l'import circulaire

    data = json.loads(Path(path).read_text(encoding="utf-8"))  # accepte NaN comme json.load d'origine
    if not isinstance(data, dict):
        raise ValueError(f"{path} : format inattendu (objet JSON attendu).")

    # --- Utilisateur « Admin » (l'ancien utilisateur implicite) ---------------------
    password_hash = str(_clean(data.get("app_password")) or "") if data.get("password_enabled") else ""
    uid = create_user_row(conn, C.DEFAULT_ADMIN_USERNAME, password_hash, is_admin=True)

    # --- Comptes & soldes initiaux --------------------------------------------------
    accounts = _unique(str(a) for a in (data.get("comptes") or C.DEFAULT_ACCOUNTS))
    initial = data.get("soldes_initiaux") or {}
    for pos, name in enumerate(accounts):
        conn.execute(
            "INSERT INTO accounts(user_id, name, position, initial_cents) VALUES(?, ?, ?, ?)",
            (uid, name, pos, to_cents(_clean(initial.get(name)) or 0.0)),
        )

    # --- Catégories & couleurs ------------------------------------------------------
    categories = _unique(str(c) for c in (data.get("categories") or C.DEFAULT_CATEGORIES)
                         if str(c) != C.INTERNAL_CATEGORY)
    colors = data.get("category_colors") or {}

    def color_of(cat: str) -> str:
        c = colors.get(cat)
        if isinstance(c, str) and HEX_COLOR.match(c):
            return c
        return C.DEFAULT_CATEGORY_COLORS.get(cat, C.FALLBACK_COLOR)

    for pos, cat in enumerate(categories):
        conn.execute(
            "INSERT INTO categories(user_id, name, position, color, system) VALUES(?, ?, ?, ?, 0)",
            (uid, cat, pos, color_of(cat)),
        )
    # La couleur de « Virement interne » (modifiable dans l'ancienne appli via le JSON) est conservée.
    conn.execute(
        "INSERT OR REPLACE INTO categories(user_id, name, position, color, system) VALUES(?, ?, 10000, ?, 1)",
        (uid, C.INTERNAL_CATEGORY, color_of(C.INTERNAL_CATEGORY)),
    )

    # --- Transactions ---------------------------------------------------------------
    imported = skipped = 0
    for rec in data.get("transactions") or []:
        try:
            date = _parse_date(rec)
            ttype = _clean(rec.get("Type"))
            cents = to_cents(_clean(rec.get("Montant")))
            account = _clean(rec.get("Compte"))
            if date is None or ttype not in C.TX_TYPES or cents <= 0 or not account:
                raise ValueError("ligne incomplète")

            target = _clean(rec.get("Compte Cible")) if ttype == C.TX_TRANSFERT else None
            category = _clean(rec.get("Catégorie")) or (
                C.INTERNAL_CATEGORY if ttype == C.TX_TRANSFERT else "Autre")
            row = (uid, date, ttype, str(account), None if target is None else str(target),
                   str(category), str(_clean(rec.get("Nom")) or ""), cents)

            legacy_id = _clean(rec.get("ID"))
            try:  # on conserve l'ID d'origine ; en cas de doublon, SQLite en attribue un nouveau
                conn.execute(
                    "INSERT INTO transactions(id, user_id, date, type, account, target_account, category, name, amount_cents) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)", (int(legacy_id), *row))
            except (*INTEGRITY_ERRORS, TypeError, ValueError):
                conn.execute(
                    "INSERT INTO transactions(user_id, date, type, account, target_account, category, name, amount_cents) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?)", row)
            imported += 1
        except (ValueError, TypeError) as exc:
            skipped += 1
            log.warning("Transaction ignorée (%s) : %r", exc, rec)

    return {"utilisateur": C.DEFAULT_ADMIN_USERNAME, "comptes": len(accounts), "categories": len(categories),
            "transactions_importees": imported, "transactions_ignorees": skipped}
