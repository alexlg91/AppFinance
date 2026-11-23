"""Tests de la logique métier :
    python -m unittest discover -s tests -p "test_services.py"
Toute la suite peut rejouer contre une base CHIFFRÉE (SQLCipher) :
    BANQUE_TEST_DB_KEY=$(openssl rand -hex 32) python -m unittest discover -s tests -p "test_services.py"
(test_api.py est un module pytest : ne pas le lancer avec unittest)."""
import datetime as dt
import logging
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, security, services  # noqa: E402

logging.disable(logging.WARNING)  # les lignes invalides ignorées sont volontaires dans ces tests
from app.money import from_cents, to_cents  # noqa: E402

# JSON au format EXACT produit par l'ancienne appli (to_dict + json.dump) ; "NaN" = valeur pandas manquante.
LEGACY = """{
    "comptes": ["Compte Courant", "Livret A", "Épargne"],
    "soldes_initiaux": {"Compte Courant": 100.5, "Livret A": 1000.0, "Épargne": 0.0},
    "categories": ["Salaire", "Course", "Loisirs"],
    "category_colors": {"Salaire": "#22C55E", "Course": "#14B8A6", "Loisirs": "#123456", "Virement interne": "#6B7280"},
    "transactions": [
        {"ID": 1, "Date": "2025-12-30", "Jour": 30, "Mois": 12, "Année": 2025, "Type": "Entrée",
         "Compte": "Compte Courant", "Compte Cible": null, "Catégorie": "Salaire", "Nom": "Paie déc.", "Montant": 2000.0},
        {"ID": 2, "Date": "2026-01-05", "Jour": 5, "Mois": 1, "Année": 2026, "Type": "Sortie",
         "Compte": "Compte Courant", "Compte Cible": NaN, "Catégorie": "Course", "Nom": "Supermarché", "Montant": 59.9},
        {"ID": 3, "Date": "2026-01-10", "Jour": 10, "Mois": 1, "Année": 2026, "Type": "Transfert",
         "Compte": "Compte Courant", "Compte Cible": "Livret A", "Catégorie": "Virement interne", "Nom": "Épargne", "Montant": 300.0},
        {"ID": 4, "Date": "2026-02-02", "Jour": 2, "Mois": 2, "Année": 2026, "Type": "Sortie",
         "Compte": "Livret A", "Compte Cible": null, "Catégorie": "Loisirs", "Nom": NaN, "Montant": 0.1},
        {"ID": 5, "Date": "2026-02-03", "Jour": 3, "Mois": 2, "Année": 2026, "Type": "Sortie",
         "Compte": "Livret A", "Compte Cible": null, "Catégorie": "Loisirs", "Nom": "", "Montant": 0.2},
        {"ID": 6, "Date": "pas-une-date", "Type": "Sortie", "Compte": "Livret A", "Catégorie": "Loisirs", "Nom": "x", "Montant": 5}
    ],
    "password_enabled": true,
    "app_password": "secret-en-clair"
}"""


KEY = os.environ.get("BANQUE_TEST_DB_KEY") or None   # None : base en clair ; sinon toute la suite tourne chiffrée


def fresh_db(legacy: str | None = None):
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name)
    legacy_path = None
    if legacy is not None:
        legacy_path = path / "banque_data.json"
        legacy_path.write_text(legacy, encoding="utf-8")
    conn = db.connect(path / "banque.db", KEY)
    db.bootstrap_database(conn, legacy_path, backup_dir=path, key=KEY)
    return tmp, conn


def uid_of(conn, username="Admin") -> int:
    return services.find_user(conn, username)["id"]


class MoneyTests(unittest.TestCase):
    def test_cents_roundtrip_and_no_float_drift(self):
        self.assertEqual(to_cents(0.1) + to_cents(0.2), to_cents(0.3))
        self.assertEqual(to_cents(59.9), 5990)
        self.assertEqual(from_cents(5990), 59.9)
        self.assertEqual(to_cents(1.005), 101)  # arrondi commercial (demi supérieur)

    def test_invalid(self):
        for bad in (None, float("nan"), float("inf"), "abc", True):
            with self.assertRaises(ValueError):
                to_cents(bad)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.conn = fresh_db(LEGACY)
        self.uid = uid_of(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_imports_everything_and_skips_bad_rows(self):
        txs = services.list_transactions(self.conn, self.uid)
        self.assertEqual(len(txs), 5)  # la ligne à date invalide est ignorée
        self.assertEqual(sorted(t["id"] for t in txs), [1, 2, 3, 4, 5])  # IDs d'origine conservés
        nan_target = services.get_transaction(self.conn, self.uid, 2)
        self.assertIsNone(nan_target["target_account"])  # NaN -> None
        self.assertEqual(services.get_transaction(self.conn, self.uid, 4)["name"], "")  # NaN -> ""

    def test_accounts_categories_colors(self):
        self.assertEqual([a["name"] for a in services.get_accounts(self.conn, self.uid)],
                         ["Compte Courant", "Livret A", "Épargne"])
        self.assertEqual(services.get_accounts(self.conn, self.uid)[0]["initial_balance"], 100.5)
        colors = services.snapshot(self.conn, self.uid)["category_colors"]
        self.assertEqual(colors["Loisirs"], "#123456")
        self.assertIn("Virement interne", colors)

    def test_balances_match_streamlit_formula(self):
        b = services.snapshot(self.conn, self.uid)["balances"]
        # Courant : 100.5 + 2000 − 59.9 − 300 = 1740.6 ; Livret A : 1000 + 300 − 0.1 − 0.2 = 1299.7
        self.assertEqual(b["Compte Courant"], 1740.6)
        self.assertEqual(b["Livret A"], 1299.7)
        self.assertEqual(b["Épargne"], 0.0)
        self.assertEqual(services.snapshot(self.conn, self.uid)["total"], 3040.3)

    def test_duplicate_legacy_ids_get_a_new_id_instead_of_failing(self):
        dup = LEGACY.replace('"ID": 2,', '"ID": 1,')        # deux transactions avec l'ID 1 : la seconde reçoit un nouvel ID
        tmp, conn = fresh_db(dup)
        try:
            uid = uid_of(conn)
            self.assertEqual(len(services.list_transactions(conn, uid)), 5)   # aucune perte
            self.assertEqual(len({t["id"] for t in services.list_transactions(conn, uid)}), 5)
        finally:
            conn.close(); tmp.cleanup()

    def test_idempotent_on_restart(self):
        db.bootstrap_database(self.conn, None, key=KEY)  # second démarrage : ne ré-importe rien
        self.assertEqual(len(services.list_transactions(self.conn, self.uid)), 5)

    def test_corrupt_json_fails_loudly_and_writes_nothing(self):
        tmp, _ = fresh_db(None)
        tmp.cleanup()
        tmp2 = tempfile.TemporaryDirectory()
        p = Path(tmp2.name)
        (p / "banque_data.json").write_text("{ pas du json", encoding="utf-8")
        conn = db.connect(p / "banque.db", KEY)
        with self.assertRaises(ValueError):
            db.bootstrap_database(conn, p / "banque_data.json", key=KEY)
        self.assertIsNone(db.get_meta(conn, "initialized"))  # base restée « non initialisée »
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 0)
        conn.close()
        tmp2.cleanup()

    def test_legacy_plaintext_password_is_accepted_then_upgraded(self):
        stored = services.find_user(self.conn, "Admin")["password_hash"]
        self.assertEqual(stored, "secret-en-clair")  # repris tel quel, converti à la 1re connexion
        self.assertTrue(services.auth_required(self.conn))
        ok, upgrade = security.verify_password("secret-en-clair", stored)
        self.assertEqual((ok, upgrade), (True, True))
        self.assertEqual(security.verify_password("faux", stored), (False, False))


class PasswordTests(unittest.TestCase):
    def test_sha256_compat_with_existing_fingerprints(self):
        # Empreinte calculée par l'ancienne appli : hashlib.sha256("motdepasse".encode()).hexdigest()
        legacy_hash = "967520ae23e8ee14888bae72809031b98398ae4a636773e18fff917d77679334"
        self.assertEqual(security.hash_password("motdepasse"), legacy_hash)
        self.assertEqual(security.verify_password("motdepasse", legacy_hash), (True, False))
        self.assertEqual(security.verify_password("Motdepasse", legacy_hash), (False, False))
        self.assertEqual(security.verify_password("é€ü", security.hash_password("é€ü")), (True, False))

    def test_empty_stored_never_matches(self):
        self.assertEqual(security.verify_password("", ""), (False, False))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.conn = fresh_db(None)  # valeurs par défaut
        self.uid = uid_of(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def tx(self, **kw):
        base = {"date": dt.date(2026, 3, 15), "type": "Sortie", "account": "Compte Courant",
                "target_account": None, "category": "Course", "name": "Test", "amount": 10.0}
        base.update(kw)
        return base

    def test_defaults_on_first_run(self):
        accounts = [a["name"] for a in services.get_accounts(self.conn, self.uid)]
        self.assertEqual(accounts, ["Compte Courant", "Livret A", "Livret B"])
        self.assertIn("Virement interne", services.snapshot(self.conn, self.uid)["category_colors"])
        self.assertFalse(services.auth_required(self.conn))

    def test_create_update_delete_and_balances(self):
        services.create_transaction(self.conn, self.uid, self.tx(type="Entrée", category="Salaire", amount=1000))
        t = services.create_transaction(self.conn, self.uid, self.tx(amount=12.34))
        self.assertEqual(services.balances_payload(self.conn, self.uid)["balances"]["Compte Courant"], 987.66)
        services.update_transaction(self.conn, self.uid, t["id"], self.tx(amount=20, name="modifié"))
        self.assertEqual(services.get_transaction(self.conn, self.uid, t["id"])["name"], "modifié")
        self.assertEqual(services.balances_payload(self.conn, self.uid)["total"], 980.0)
        services.delete_transaction(self.conn, self.uid, t["id"])
        self.assertEqual(services.balances_payload(self.conn, self.uid)["total"], 1000.0)
        with self.assertRaises(services.ServiceError) as ctx:
            services.delete_transaction(self.conn, self.uid, t["id"])
        self.assertEqual(ctx.exception.status, 404)

    def test_transfer_moves_money_without_changing_total(self):
        services.create_transaction(self.conn, self.uid, self.tx(type="Entrée", category="Salaire", amount=500))
        t = services.create_transaction(self.conn, self.uid, self.tx(
            type="Transfert", target_account="Livret A", category="n'importe quoi", amount=200))
        self.assertEqual(t["category"], "Virement interne")  # imposée
        p = services.balances_payload(self.conn, self.uid)
        self.assertEqual((p["balances"]["Compte Courant"], p["balances"]["Livret A"], p["total"]), (300.0, 200.0, 500.0))

    def test_validation_errors(self):
        bad = [
            self.tx(amount=0), self.tx(amount=-5), self.tx(amount=float("nan")),
            self.tx(account="Inconnu"), self.tx(category="Inexistante"), self.tx(type="Autre"),
            self.tx(date="2026-02-31"),
            self.tx(type="Transfert", target_account="Compte Courant"),  # même compte
            self.tx(type="Transfert", target_account="Inconnu"),
        ]
        for payload in bad:
            with self.assertRaises(services.ServiceError, msg=payload):
                services.create_transaction(self.conn, self.uid, payload)
        self.assertEqual(services.list_transactions(self.conn, self.uid), [])

    def test_editing_a_tx_whose_category_was_deleted_is_still_possible(self):
        t = services.create_transaction(self.conn, self.uid, self.tx(category="Voiture"))
        services.delete_category(self.conn, self.uid, "Voiture")
        services.update_transaction(self.conn, self.uid, t["id"], self.tx(category="Voiture", amount=99))
        with self.assertRaises(services.ServiceError):  # mais on ne peut pas l'attribuer à une nouvelle tx
            services.create_transaction(self.conn, self.uid, self.tx(category="Voiture"))

    def test_clear(self):
        services.create_transaction(self.conn, self.uid, self.tx())
        services.clear_transactions(self.conn, self.uid)
        self.assertEqual(services.list_transactions(self.conn, self.uid), [])

    def test_ids_are_never_reused(self):
        a = services.create_transaction(self.conn, self.uid, self.tx())
        services.delete_transaction(self.conn, self.uid, a["id"])
        b = services.create_transaction(self.conn, self.uid, self.tx())
        self.assertGreater(b["id"], a["id"])

    def test_csv_export_has_original_columns(self):
        services.create_transaction(self.conn, self.uid, self.tx(name='a,"b"', amount=5.5))
        lines = services.export_csv(self.conn, self.uid).splitlines()
        self.assertEqual(lines[0], "ID,Date,Jour,Mois,Année,Type,Compte,Compte Cible,Catégorie,Nom,Montant")
        self.assertEqual(lines[1], '1,2026-03-15,15,3,2026,Sortie,Compte Courant,,Course,"a,""b""",5.50')


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.conn = fresh_db(None)
        self.uid = uid_of(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_account_rules(self):
        services.add_account(self.conn, self.uid, "  Assurance vie ")
        with self.assertRaises(services.ServiceError):
            services.add_account(self.conn, self.uid, "Assurance vie")
        with self.assertRaises(services.ServiceError):
            services.add_account(self.conn, self.uid, "   ")
        snap = services.set_initial_balance(self.conn, self.uid, "Livret A", 1500.25)
        self.assertEqual(snap["balances"]["Livret A"], 1500.25)
        for name in ("Compte Courant", "Livret A", "Livret B"):
            services.delete_account(self.conn, self.uid, name)
        with self.assertRaises(services.ServiceError):  # il doit en rester un
            services.delete_account(self.conn, self.uid, "Assurance vie")

    def test_category_rules(self):
        services.add_category(self.conn, self.uid, "Loisirs", "#abcdef")
        self.assertEqual(services.snapshot(self.conn, self.uid)["category_colors"]["Loisirs"], "#ABCDEF")
        for bad in (("Loisirs", "#000000"), ("", "#000000"), ("Virement interne", "#000000"), ("X", "rouge")):
            with self.assertRaises(services.ServiceError, msg=bad):
                services.add_category(self.conn, self.uid, *bad)
        with self.assertRaises(services.ServiceError):
            services.delete_category(self.conn, self.uid, "Virement interne")  # système
        for name in [c["name"] for c in services.get_categories(self.conn, self.uid) if not c["system"]][:-1]:
            services.delete_category(self.conn, self.uid, name)
        with self.assertRaises(services.ServiceError):  # au moins une catégorie conservée
            services.delete_category(self.conn, self.uid, "Loisirs")

    def test_password_lifecycle(self):
        self.assertTrue(services.set_password(self.conn, self.uid, True, "abc"))
        self.assertEqual(services.find_user(self.conn, "Admin")["password_hash"], security.hash_password("abc"))
        with self.assertRaises(services.ServiceError):
            services.set_password(self.conn, self.uid, True, "   ")
        self.assertTrue(services.set_password(self.conn, self.uid, True, None))  # conserve l'existant
        self.assertFalse(services.set_password(self.conn, self.uid, False, None))
        self.assertEqual(services.find_user(self.conn, "Admin")["password_hash"], "")
        with self.assertRaises(services.ServiceError):  # activer sans mot de passe défini
            services.set_password(self.conn, self.uid, True, None)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.conn = fresh_db(LEGACY)
        self.uid = uid_of(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_flows_and_donuts(self):
        d = services.dashboard(self.conn, self.uid, 2026, 1)
        self.assertEqual(d["month_flow"], {"entrees": 0.0, "sorties": 59.9, "net": -59.9})  # transfert exclu
        self.assertEqual(d["year_flow"]["sorties"], 60.2)
        self.assertEqual(d["month_expenses"], [{"category": "Course", "amount": 59.9}])
        self.assertEqual(d["month_income"], [])
        self.assertEqual(services.dashboard(self.conn, self.uid, 2025, 12)["month_flow"]["entrees"], 2000.0)

    def test_december_bounds(self):
        d = services.dashboard(self.conn, self.uid, 2025, 12)
        self.assertEqual(d["month_income"], [{"category": "Salaire", "amount": 2000.0}])

    def test_averages_use_active_months_only(self):
        d = services.dashboard(self.conn, self.uid, 2026, 1)["avg_expenses"]
        self.assertEqual(d["months"], 2)  # janvier + février
        by = {i["category"]: i for i in d["items"]}
        self.assertEqual(by["Course"]["average"], 29.95)  # 59.90 / 2
        self.assertEqual(by["Loisirs"]["total"], 0.3)
        self.assertEqual(d["items"][0]["category"], "Course")  # trié par moyenne décroissante

    def test_evolution_starts_from_real_opening_balance(self):
        ev = services.dashboard(self.conn, self.uid, 2026, 1)["evolution"]
        self.assertEqual(ev["dates"], ["2026-01-05", "2026-01-10", "2026-02-02", "2026-02-03"])
        courant = next(s for s in ev["series"] if s["account"] == "Compte Courant")["values"]
        # ouverture 2026 = 100.5 + 2000 = 2100.5 (le salaire de décembre 2025 est bien pris en compte)
        self.assertEqual(courant, [2040.6, 1740.6, 1740.6, 1740.6])
        last = {s["account"]: s["values"][-1] for s in ev["series"]}
        self.assertEqual(last, services.balances_payload(self.conn, self.uid)["balances"])  # cohérent avec les cartes

    def test_empty_year(self):
        d = services.dashboard(self.conn, self.uid, 2030, 6)
        self.assertEqual(d["evolution"]["dates"], [])
        self.assertTrue(d["has_data"])
        self.assertEqual(d["avg_expenses"], {"months": 0, "items": []})

    def test_years_range(self):
        self.assertEqual(services.available_years(self.conn, self.uid, dt.date(2026, 11, 21)), list(range(2020, 2031)))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.conn = fresh_db(None)
        self.uid = uid_of(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_session_lifecycle_survives_new_connection(self):
        token = security.create_session(self.conn, self.uid, 3600)
        raw = self.conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
        self.assertNotEqual(raw, token)  # le jeton brut n'est jamais stocké
        conn2 = db.connect(self.tmp.name + "/banque.db", KEY)  # « redémarrage » : nouvelle connexion
        self.assertEqual(security.validate_session(conn2, token, 3600), (self.uid, False))
        self.assertEqual(security.validate_session(conn2, "faux", 3600), (None, False))
        security.delete_session(conn2, token)
        self.assertEqual(security.validate_session(conn2, token, 3600), (None, False))
        conn2.close()

    def test_expiry_and_sliding_renewal(self):
        token = security.create_session(self.conn, self.uid, 3600)
        self.conn.execute("UPDATE sessions SET expires_at = ?", (int(time.time()) + 100,))  # < 50 % restant
        self.conn.commit()
        self.assertEqual(security.validate_session(self.conn, token, 3600), (self.uid, True))
        self.conn.execute("UPDATE sessions SET expires_at = ?", (int(time.time()) - 1,))
        self.conn.commit()
        self.assertEqual(security.validate_session(self.conn, token, 3600), (None, False))

    def test_sessions_are_revoked_per_user(self):
        other = db.create_user_row(self.conn, "Autre", security.hash_password("x"))
        self.conn.commit()
        mine, theirs = security.create_session(self.conn, self.uid, 3600), security.create_session(self.conn, other, 3600)
        security.delete_user_sessions(self.conn, self.uid)
        self.assertEqual(security.validate_session(self.conn, mine, 3600)[0], None)
        self.assertEqual(security.validate_session(self.conn, theirs, 3600)[0], other)  # l'autre reste connecté

    def test_throttle(self):
        th = security.LoginThrottle(max_failures=3, window=60)
        for _ in range(3):
            self.assertEqual(th.blocked_for("1.2.3.4"), 0)
            th.record_failure("1.2.3.4")
        self.assertGreater(th.blocked_for("1.2.3.4"), 0)
        self.assertEqual(th.blocked_for("5.6.7.8"), 0)  # autre IP non affectée
        th.reset("1.2.3.4")
        self.assertEqual(th.blocked_for("1.2.3.4"), 0)


class MultiUserTests(unittest.TestCase):
    """Plusieurs utilisateurs : droits, isolation stricte des données, cycle de vie."""

    def setUp(self):
        self.tmp, self.conn = fresh_db(None)
        self.admin = uid_of(self.conn)
        services.set_password(self.conn, self.admin, True, "adminpw")   # prérequis pour créer des utilisateurs
        services.create_user(self.conn, self.admin, "Alice", "alicepw")
        self.alice = uid_of(self.conn, "Alice")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def tx(self, **kw):
        base = {"date": dt.date(2026, 3, 15), "type": "Sortie", "account": "Compte Courant",
                "target_account": None, "category": "Course", "name": "Test", "amount": 10.0}
        base.update(kw)
        return base

    def test_open_mode_rules(self):
        tmp, conn = fresh_db(None)
        try:
            admin = uid_of(conn)
            self.assertFalse(services.auth_required(conn))                  # un seul utilisateur, sans mot de passe
            self.assertEqual(services.open_mode_user(conn)["username"], "Admin")
            with self.assertRaises(services.ServiceError) as ctx:           # créer un utilisateur exige un mot de passe admin
                services.create_user(conn, admin, "Bob", "pw")
            self.assertIn("mot de passe", ctx.exception.message)
        finally:
            conn.close(); tmp.cleanup()

    def test_auth_required_once_several_users(self):
        self.assertTrue(services.auth_required(self.conn))
        self.assertIsNone(services.open_mode_user(self.conn))
        self.assertEqual([u["username"] for u in services.list_users(self.conn)], ["Admin", "Alice"])
        self.assertEqual([u["is_admin"] for u in services.list_users(self.conn)], [True, False])

    def test_username_rules(self):
        for ok_name, expected in (("  Bob   Dupont ", "Bob Dupont"), ("éric.d-1@x", "éric.d-1@x")):
            users = services.create_user(self.conn, self.admin, ok_name, "pw")
            self.assertIn(expected, [u["username"] for u in users])
        with self.assertRaises(services.ServiceError) as ctx:               # doublon insensible à la casse
            services.create_user(self.conn, self.admin, "aLiCe", "pw")
        self.assertEqual(ctx.exception.status, 409)
        for bad in ("", "   ", "<script>", "a" * 41, "-tiret", "x/y"):
            with self.assertRaises(services.ServiceError, msg=repr(bad)):
                services.create_user(self.conn, self.admin, bad, "pw")
        with self.assertRaises(services.ServiceError):
            services.create_user(self.conn, self.admin, "Zoé", "   ")      # mot de passe vide
        self.assertEqual(services.find_user(self.conn, "ALICE")["id"], self.alice)

    def test_new_user_gets_defaults_and_empty_ledger(self):
        snap = services.snapshot(self.conn, self.alice)
        self.assertEqual([a["name"] for a in snap["accounts"]], ["Compte Courant", "Livret A", "Livret B"])
        self.assertIn("Virement interne", snap["category_colors"])
        self.assertEqual(snap["total"], 0.0)
        self.assertEqual(services.list_transactions(self.conn, self.alice), [])

    def test_non_admin_cannot_manage_users(self):
        for call in (lambda: services.create_user(self.conn, self.alice, "Eve", "pw"),
                     lambda: services.delete_user(self.conn, self.alice, self.admin),
                     lambda: services.reset_user_password(self.conn, self.alice, self.admin, "pwned")):
            with self.assertRaises(services.ServiceError) as ctx:
                call()
            self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(security.verify_password("adminpw", services.find_user(self.conn, "Admin")["password_hash"]), (True, False))

    def test_data_isolation_between_users(self):
        mine = services.create_transaction(self.conn, self.admin, self.tx(type="Entrée", category="Salaire", amount=1000))
        services.set_initial_balance(self.conn, self.admin, "Livret A", 500)
        services.add_category(self.conn, self.admin, "Loisirs", "#123456")

        # Alice ne voit rien de ce qui appartient à Admin
        self.assertEqual(services.list_transactions(self.conn, self.alice), [])
        self.assertEqual(services.balances_payload(self.conn, self.alice)["total"], 0.0)
        self.assertNotIn("Loisirs", services.snapshot(self.conn, self.alice)["category_colors"])
        self.assertFalse(services.dashboard(self.conn, self.alice, 2026, 3)["has_data"])
        self.assertEqual(services.export_csv(self.conn, self.alice).count("\n"), 1)   # en-tête seul
        self.assertEqual(services.available_years(self.conn, self.alice, dt.date(2026, 1, 1))[0], 2020)

        # …et ne peut ni lire, ni modifier, ni supprimer la transaction d'Admin (404, pas 403 : on ne révèle rien)
        for call in (lambda: services.get_transaction(self.conn, self.alice, mine["id"]),
                     lambda: services.update_transaction(self.conn, self.alice, mine["id"], self.tx(amount=1)),
                     lambda: services.delete_transaction(self.conn, self.alice, mine["id"])):
            with self.assertRaises(services.ServiceError) as ctx:
                call()
            self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(services.get_transaction(self.conn, self.admin, mine["id"])["amount"], 1000.0)

        # les opérations d'Alice n'affectent pas Admin
        services.set_initial_balance(self.conn, self.alice, "Livret A", 77)
        services.clear_transactions(self.conn, self.alice)
        services.delete_category(self.conn, self.alice, "Voiture")
        self.assertEqual(services.balances_payload(self.conn, self.admin)["balances"]["Livret A"], 500.0)
        self.assertEqual(len(services.list_transactions(self.conn, self.admin)), 1)
        self.assertIn("Voiture", services.snapshot(self.conn, self.admin)["category_colors"])

    def test_same_account_names_do_not_collide(self):
        services.create_transaction(self.conn, self.admin, self.tx(type="Entrée", category="Salaire", amount=100))
        services.create_transaction(self.conn, self.alice, self.tx(type="Entrée", category="Salaire", amount=7))
        self.assertEqual(services.balances_payload(self.conn, self.admin)["balances"]["Compte Courant"], 100.0)
        self.assertEqual(services.balances_payload(self.conn, self.alice)["balances"]["Compte Courant"], 7.0)

    def test_delete_user_removes_all_of_their_data_only(self):
        services.create_transaction(self.conn, self.admin, self.tx())
        services.create_transaction(self.conn, self.alice, self.tx())
        security.create_session(self.conn, self.alice, 3600)
        with self.assertRaises(services.ServiceError):                      # pas soi-même
            services.delete_user(self.conn, self.admin, self.admin)
        with self.assertRaises(services.ServiceError) as ctx:
            services.delete_user(self.conn, self.admin, 9999)
        self.assertEqual(ctx.exception.status, 404)

        users = services.delete_user(self.conn, self.admin, self.alice)
        self.assertEqual([u["username"] for u in users], ["Admin"])
        for table in ("transactions", "accounts", "categories", "sessions"):
            n = self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (self.alice,)).fetchone()[0]
            self.assertEqual(n, 0, table)
        self.assertEqual(len(services.list_transactions(self.conn, self.admin)), 1)   # Admin intact

    def test_foreign_key_cascade_as_safety_net(self):
        services.create_transaction(self.conn, self.alice, self.tx())
        with self.conn:
            self.conn.execute("DELETE FROM users WHERE id = ?", (self.alice,))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ?", (self.alice,)).fetchone()[0], 0)

    def test_admin_password_reset_revokes_sessions(self):
        token = security.create_session(self.conn, self.alice, 3600)
        self.assertEqual(security.validate_session(self.conn, token, 3600)[0], self.alice)
        services.reset_user_password(self.conn, self.admin, self.alice, "nouveau")
        self.assertIsNone(security.validate_session(self.conn, token, 3600)[0])          # déconnectée
        stored = services.find_user(self.conn, "Alice")["password_hash"]
        self.assertEqual(security.verify_password("nouveau", stored), (True, False))
        self.assertEqual(security.verify_password("alicepw", stored), (False, False))
        with self.assertRaises(services.ServiceError):                                    # pas son propre mot de passe par cette route
            services.reset_user_password(self.conn, self.admin, self.admin, "x")
        with self.assertRaises(services.ServiceError):
            services.reset_user_password(self.conn, self.admin, self.alice, "  ")

    def test_protection_cannot_be_disabled_while_several_users(self):
        with self.assertRaises(services.ServiceError):
            services.set_password(self.conn, self.admin, False, None)
        self.assertTrue(services.set_password(self.conn, self.alice, True, "autre"))      # changer SON mot de passe : OK
        services.delete_user(self.conn, self.admin, self.alice)
        self.assertFalse(services.set_password(self.conn, self.admin, False, None))       # seul : désactivation possible
        self.assertFalse(services.auth_required(self.conn))

    def test_bootstrap_payload_is_scoped_to_the_user(self):
        services.create_transaction(self.conn, self.admin, self.tx())
        a = services.bootstrap_payload(self.conn, services.get_user(self.conn, self.admin))
        b = services.bootstrap_payload(self.conn, services.get_user(self.conn, self.alice))
        self.assertEqual((len(a["transactions"]), len(b["transactions"])), (1, 0))
        self.assertEqual((a["user"]["username"], b["user"]["username"]), ("Admin", "Alice"))
        self.assertEqual((a["users_count"], a["password_enabled"]), (2, True))
        self.assertNotIn("password_hash", a["user"])      # jamais exposé au client


V1_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE accounts (name TEXT PRIMARY KEY, position INTEGER NOT NULL, initial_cents INTEGER NOT NULL DEFAULT 0);
CREATE TABLE categories (name TEXT PRIMARY KEY, position INTEGER NOT NULL, color TEXT NOT NULL, system INTEGER NOT NULL DEFAULT 0);
CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('Entrée', 'Sortie', 'Transfert')), account TEXT NOT NULL, target_account TEXT,
    category TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', amount_cents INTEGER NOT NULL);
CREATE INDEX idx_tx_date ON transactions(date);
CREATE INDEX idx_tx_account ON transactions(type, account);
CREATE INDEX idx_tx_target ON transactions(type, target_account);
CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, expires_at INTEGER NOT NULL);
"""


def make_v1_database(path: Path, with_sessions_table: bool = True):
    """Reproduit fidèlement une base créée par la v1 (un seul utilisateur implicite)."""
    raw = sqlite3.connect(path)
    schema = V1_SCHEMA if with_sessions_table else V1_SCHEMA.replace("CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, expires_at INTEGER NOT NULL);", "")
    raw.executescript(schema)
    raw.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("initialized", "1"), ("password_enabled", "1"), ("app_password", security.hash_password("v1pass"))])
    raw.executemany("INSERT INTO accounts VALUES (?, ?, ?)", [("Compte Courant", 0, 10050), ("Épargne", 1, 0)])
    raw.executemany("INSERT INTO categories VALUES (?, ?, ?, ?)", [
        ("Salaire", 0, "#22C55E", 0), ("Course", 1, "#14B8A6", 0), ("Virement interne", 10000, "#6B7280", 1)])
    raw.executemany(
        "INSERT INTO transactions(date, type, account, target_account, category, name, amount_cents) VALUES (?,?,?,?,?,?,?)", [
            ("2026-01-05", "Entrée", "Compte Courant", None, "Salaire", "Paie", 200000),
            ("2026-01-06", "Sortie", "Compte Courant", None, "Course", "Lidl", 5990),
            ("2026-01-07", "Transfert", "Compte Courant", "Épargne", "Virement interne", "Épargne", 30000),
            ("2026-01-08", "Sortie", "Épargne", None, "Course", "à supprimer", 100)])
    raw.execute("DELETE FROM transactions WHERE id = 4")          # séquence AUTOINCREMENT = 4 : l'ID 4 ne doit jamais être réutilisé
    if with_sessions_table:
        raw.execute("INSERT INTO sessions VALUES ('ancien-hash', 9999999999)")
    raw.commit()
    raw.close()


def open_v1(path: Path):
    """Chemin réel de l'appli : prepare_storage (chiffre la base v1 et sa sauvegarde si une clé est configurée), puis ouverture."""
    db.prepare_storage(path / "banque.db", KEY, extra=[path / "banque.v1.bak.db"])
    return db.connect(path / "banque.db", KEY)


class UpgradeFromV1Tests(unittest.TestCase):
    """Une base déjà utilisée avec la v1 est migrée sans perte vers « Admin »."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_upgrade_keeps_everything_for_admin(self):
        make_v1_database(self.path / "banque.db")
        conn = open_v1(self.path)
        db.bootstrap_database(conn, None, backup_dir=self.path, key=KEY)
        uid = uid_of(conn)

        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
        admin = services.get_user(conn, uid)
        self.assertEqual((admin["username"], admin["is_admin"], admin["has_password"]), ("Admin", True, True))
        self.assertEqual(security.verify_password("v1pass", services.find_user(conn, "Admin")["password_hash"]), (True, False))
        self.assertIsNone(db.get_meta(conn, "app_password"))                        # plus dans meta
        self.assertTrue(services.auth_required(conn))

        self.assertEqual([t["id"] for t in services.list_transactions(conn, uid)], [3, 2, 1])   # IDs conservés
        snap = services.snapshot(conn, uid)
        self.assertEqual(snap["balances"], {"Compte Courant": 1740.6, "Épargne": 300.0})        # mêmes soldes qu'avant
        self.assertEqual(snap["category_colors"]["Course"], "#14B8A6")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)       # sessions v1 abandonnées

        new_tx = services.create_transaction(conn, uid, {"date": dt.date(2026, 2, 1), "type": "Sortie",
                                                         "account": "Compte Courant", "category": "Course", "amount": 1})
        self.assertEqual(new_tx["id"], 5)                                                       # 4 n'est pas réattribué

        for old in ("accounts_v1", "categories_v1", "transactions_v1", "sessions_v1"):
            self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (old,)).fetchone())
        db.bootstrap_database(conn, None, backup_dir=self.path, key=KEY)                        # idempotent au redémarrage
        self.assertEqual(db.get_meta(conn, "initialized"), "1")
        self.assertEqual(services.count_users(conn), 1)
        conn.close()

    def test_backup_is_written_before_upgrade(self):
        make_v1_database(self.path / "banque.db")
        conn = open_v1(self.path)
        db.bootstrap_database(conn, None, backup_dir=self.path, key=KEY)
        conn.close()
        backup = db.connect(self.path / "banque.v1.bak.db", KEY)    # chiffrée avec la même clé quand le chiffrement est actif
        cols = [r[1] for r in backup.execute("PRAGMA table_info(transactions)")]
        self.assertNotIn("user_id", cols)                                                       # copie fidèle de la v1
        self.assertEqual(backup.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 3)
        backup.close()

    def test_failed_upgrade_rolls_back_completely(self):
        make_v1_database(self.path / "banque.db", with_sessions_table=False)                    # base v1 « abîmée »
        conn = open_v1(self.path)
        with self.assertRaises(db.OPERATIONAL_ERRORS):
            db.bootstrap_database(conn, None, backup_dir=self.path, key=KEY)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("accounts", names)                                                        # tables d'origine intactes
        self.assertNotIn("users", names)
        self.assertNotIn("accounts_v1", names)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 3)
        conn.close()


if __name__ == "__main__":
    unittest.main()
