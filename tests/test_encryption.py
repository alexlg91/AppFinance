"""Tests du chiffrement de la base au repos (SQLCipher).   python -m unittest discover -s tests -p "test_encryption.py"

Le test central scanne les OCTETS des fichiers du dossier de données : un témoin (la même base en clair) prouve que le
scanner détecte bien les données lisibles, donc que l'absence de résultat sur la base chiffrée est significative."""
import datetime as dt
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config, db, security, services  # noqa: E402
from test_services import make_v1_database  # noqa: E402

logging.disable(logging.WARNING)

MARK = "MARQUEUR-SECRET-Lidl-9f3a"
NEEDLES = [MARK, "Alice-Martin", "Compte Courant", "Course"]


def payloads(conn):
    """Contenu observable par chaque utilisateur (identique avant/après conversion)."""
    return {u["username"]: services.bootstrap_payload(conn, u) for u in services.list_users(conn)}


def scan(directory, needles=NEEDLES):
    """{fichier: [ce qui y est lisible en clair]} pour tous les fichiers du dossier (base, -wal, -shm, copies…)."""
    hits = {}
    for f in sorted(Path(directory).iterdir()):
        if not f.is_file():
            continue
        raw = f.read_bytes()
        found = [n for n in needles if n.encode("utf-8") in raw]
        if raw.startswith(db.SQLITE_MAGIC):
            found.append("<en-tête SQLite en clair>")
        if found:
            hits[f.name] = found
    return hits


def populate(conn):
    """Deux utilisateurs avec des données reconnaissables ; une transaction supprimée (compteur AUTOINCREMENT) ; une session."""
    admin = services.find_user(conn, "Admin")["id"]
    services.set_password(conn, admin, True, "adminpw")
    services.create_user(conn, admin, "Alice-Martin", "alicepw")
    alice = services.find_user(conn, "Alice-Martin")["id"]
    for uid in (admin, alice):
        for i in range(12):
            services.create_transaction(conn, uid, {
                "date": dt.date(2026, 3, 1 + i), "type": "Sortie", "account": "Compte Courant",
                "category": "Course", "name": f"{MARK} #{i}", "amount": 10 + i})
    last = services.list_transactions(conn, admin)[0]["id"]
    services.delete_transaction(conn, admin, last)            # le compteur d'ID doit survivre à la conversion
    return admin, alice, security.create_session(conn, admin, 3600)


@unittest.skipUnless(db.cipher_available(), "sqlcipher3 n'est pas installé")
class EncryptionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "banque.db"
        self.key = os.urandom(32).hex()

    def tearDown(self):
        self._tmp.cleanup()

    def plain_db(self, directory=None):
        directory = Path(directory or self.dir)
        conn = db.connect(directory / "banque.db")
        db.bootstrap_database(conn, None)
        return conn

    # ---------------------------------------------------------------- rien de lisible dans les fichiers
    def test_witness_the_scanner_does_see_cleartext_in_a_plain_database(self):
        conn = self.plain_db()
        populate(conn)
        conn.close()
        hits = scan(self.dir)
        self.assertIn("banque.db", hits)
        self.assertIn(MARK, hits["banque.db"])
        self.assertIn("<en-tête SQLite en clair>", hits["banque.db"])

    def test_encrypted_database_files_contain_nothing_readable(self):
        conn = db.connect(self.path, self.key)
        db.bootstrap_database(conn, None, key=self.key)
        populate(conn)
        self.assertEqual(scan(self.dir), {}, "base ouverte, journal WAL actif")
        self.assertTrue(any(f.name.endswith("-wal") for f in self.dir.iterdir()), "le test doit couvrir un WAL non vide")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.assertEqual(scan(self.dir), {}, "après checkpoint")
        conn.close()
        self.assertEqual(scan(self.dir, NEEDLES + ["adminpw", security.hash_password("adminpw"), "alicepw"]), {}, "après fermeture")
        self.assertEqual(db.file_state(self.path), "encrypted")

    # ---------------------------------------------------------------- accès refusés sans la bonne clé
    def test_wrong_key_missing_key_and_plain_driver_are_all_refused(self):
        conn = db.connect(self.path, self.key)
        db.bootstrap_database(conn, None, key=self.key)
        conn.close()
        before = sorted(p.name for p in self.dir.iterdir())

        for bad in (os.urandom(32).hex(), "0" * 64):
            with self.assertRaises(db.EncryptionError) as ctx:
                db.connect(self.path, bad)
            self.assertIn("clé de chiffrement incorrecte", str(ctx.exception))
        with self.assertRaises(db.EncryptionError) as ctx:        # chiffrée mais aucune clé configurée
            db.prepare_storage(self.path, None)
        self.assertIn("aucune clé", str(ctx.exception))
        with self.assertRaises(db.DATABASE_ERRORS):               # un client SQLite ordinaire (ex. `sqlite3` en CLI) n'y lit rien
            sqlite3.connect(self.path).execute("SELECT * FROM sqlite_master").fetchall()
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before, "aucune base vide créée à côté")

    def test_invalid_key_format_is_rejected_by_the_driver_layer(self):
        for bad in ("", "zz" * 32, "ab" * 31, 'x"; DROP TABLE users; --'):
            with self.assertRaises(db.EncryptionError):
                db.connect(self.dir / "x.db", bad)

    # ---------------------------------------------------------------- conversion clair -> chiffré
    def test_conversion_preserves_everything_and_erases_the_plaintext(self):
        conn = self.plain_db()
        admin, alice, token = populate(conn)
        before = payloads(conn)
        conn.close()
        self.assertIn("banque.db", scan(self.dir))                 # bien en clair au départ

        db.prepare_storage(self.path, self.key)

        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["banque.db"], "aucun reste (.plain-to-delete, .encrypting, -wal…)")
        self.assertEqual(scan(self.dir), {})
        self.assertEqual(db.file_state(self.path), "encrypted")

        conn = db.connect(self.path, self.key)
        db.bootstrap_database(conn, None, key=self.key)
        self.assertEqual(payloads(conn), before)                   # soldes, transactions, catégories, utilisateurs : identiques
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(security.validate_session(conn, token, 3600)[0], admin)       # sessions et mots de passe conservés
        self.assertEqual(security.verify_password("alicepw", services.find_user(conn, "Alice-Martin")["password_hash"]), (True, False))
        new = services.create_transaction(conn, admin, {"date": dt.date(2026, 5, 1), "type": "Sortie",
                                                        "account": "Compte Courant", "category": "Course", "amount": 1})
        deleted_id = max(t["id"] for t in before["Admin"]["transactions"]) + 1
        self.assertGreater(new["id"], deleted_id, "l'ID supprimé n'est jamais réattribué")
        conn.close()

        snapshot = self.path.read_bytes()
        db.prepare_storage(self.path, self.key)                    # idempotent : rien à refaire
        self.assertEqual(self.path.read_bytes(), snapshot)

    def test_conversion_replays_an_orphan_wal_from_an_unclean_shutdown(self):
        conn = self.plain_db()
        populate(conn)
        last = services.create_transaction(conn, 1, {"date": dt.date(2026, 6, 6), "type": "Sortie",
                                                     "account": "Compte Courant", "category": "Course",
                                                     "name": "DANS-LE-WAL-SEULEMENT", "amount": 3})
        crashed = self.dir / "crashed"
        crashed.mkdir()
        shutil.copy2(self.path, crashed / "banque.db")                         # copie « à chaud » : le dernier ajout n'est que dans le -wal
        shutil.copy2(str(self.path) + "-wal", str(crashed / "banque.db") + "-wal")
        conn.close()
        self.assertGreater(os.path.getsize(str(crashed / "banque.db") + "-wal"), 0)

        db.prepare_storage(crashed / "banque.db", self.key)

        self.assertEqual(sorted(p.name for p in crashed.iterdir()), ["banque.db"])
        self.assertEqual(scan(crashed, NEEDLES + ["DANS-LE-WAL-SEULEMENT"]), {})
        conn = db.connect(crashed / "banque.db", self.key)
        self.assertEqual(services.get_transaction(conn, 1, last["id"])["name"], "DANS-LE-WAL-SEULEMENT")
        conn.close()

    def test_original_is_kept_and_nothing_is_deleted_if_the_copy_does_not_match(self):
        conn = self.plain_db()
        populate(conn)
        conn.close()
        original = self.path.read_bytes()
        real, calls = db._fingerprint, []

        def corrupting(c):
            calls.append(1)
            result = real(c)
            if len(calls) == 2:                                    # 1er appel : source ; 2e : copie chiffrée -> on la « corrompt »
                result["transactions"] = (0, "faux")
            return result

        db._fingerprint = corrupting
        try:
            with self.assertRaises(db.EncryptionError) as ctx:
                db.encrypt_file(self.path, self.key)
        finally:
            db._fingerprint = real
        self.assertIn("pas identique", str(ctx.exception))
        self.assertEqual(self.path.read_bytes(), original, "la base en clair est intacte")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["banque.db"], "la copie douteuse est supprimée")

    def test_secrets_never_appear_in_logs(self):
        conn = self.plain_db()
        populate(conn)
        conn.close()
        logging.disable(logging.NOTSET)
        try:
            with self.assertLogs("banque.db", level="INFO") as logs:
                db.prepare_storage(self.path, self.key)
        finally:
            logging.disable(logging.WARNING)
        text = "\n".join(logs.output)
        self.assertIn("chiffrée", text)
        self.assertNotIn(self.key, text)

    # ---------------------------------------------------------------- reprise après arrêt brutal (chaque étape intermédiaire)
    def _encrypted_copy_of_plain(self, name):
        """(octets de la base en clair, octets de sa version chiffrée) pour fabriquer des états intermédiaires."""
        d = self.dir / name
        d.mkdir()
        conn = self.plain_db(d)
        populate(conn)
        conn.close()
        plain = (d / "banque.db").read_bytes()
        db.prepare_storage(d / "banque.db", self.key)
        return plain, (d / "banque.db").read_bytes()

    def test_crash_after_replace_before_erasing_the_old_plaintext(self):
        plain, enc = self._encrypted_copy_of_plain("seed")
        self.path.write_bytes(enc)
        (self.dir / "banque.db.plain-to-delete").write_bytes(plain)
        db.prepare_storage(self.path, self.key)
        self.assertFalse((self.dir / "banque.db.plain-to-delete").exists())
        self.assertEqual(scan(self.dir, [MARK]), {}, "ni ancien fichier en clair, ni copie lisible")

    def test_crash_between_the_two_renames_completes_the_conversion(self):
        plain, enc = self._encrypted_copy_of_plain("seed")
        (self.dir / "banque.db.plain-to-delete").write_bytes(plain)        # banque.db absent : arrêt entre les deux os.replace
        (self.dir / "banque.db.encrypting").write_bytes(enc)
        db.prepare_storage(self.path, self.key)
        self.assertEqual(db.file_state(self.path), "encrypted")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if p.is_file()), ["banque.db"])
        conn = db.connect(self.path, self.key)
        self.assertEqual(len(services.list_transactions(conn, 1)), 11)
        conn.close()

    def test_crash_during_the_copy_leaves_the_plaintext_intact_and_converts_on_restart(self):
        plain, _ = self._encrypted_copy_of_plain("seed")
        self.path.write_bytes(plain)
        (self.dir / "banque.db.encrypting").write_bytes(b"copie incomplete \x00\x01")
        db.prepare_storage(self.path, self.key)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if p.is_file()), ["banque.db"])
        conn = db.connect(self.path, self.key)
        self.assertEqual(len(services.list_transactions(conn, 1)), 11)
        conn.close()

    def test_leftover_partial_copy_is_removed_whatever_the_state_of_the_database(self):
        plain, enc = self._encrypted_copy_of_plain("seed")
        tmp = self.dir / "banque.db.encrypting"
        for content, key in ((plain, None), (enc, self.key)):               # base en clair sans clé configurée ; base déjà chiffrée
            self.path.write_bytes(content)
            tmp.write_bytes(b"copie incomplete")
            db.prepare_storage(self.path, key)
            self.assertFalse(tmp.exists())
            self.assertEqual(self.path.read_bytes(), content, "la base elle-même n'est pas touchée")

    def test_the_only_copy_is_never_lost(self):
        plain, _ = self._encrypted_copy_of_plain("seed")
        (self.dir / "banque.db.plain-to-delete").write_bytes(plain)        # ni base, ni copie chiffrée : l'ancien fichier est la seule copie
        db.prepare_storage(self.path, self.key)
        self.assertEqual(db.file_state(self.path), "encrypted")             # restauré PUIS converti
        conn = db.connect(self.path, self.key)
        self.assertEqual(len(services.list_transactions(conn, 1)), 11)
        conn.close()
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if p.is_file()), ["banque.db"])

    # ---------------------------------------------------------------- sauvegarde v1 et ancien JSON
    def test_upgrade_backup_is_encrypted_and_an_old_plain_backup_is_converted(self):
        make_v1_database(self.path)
        make_v1_database(self.dir / "banque.v1.bak.db")                    # sauvegarde laissée EN CLAIR par une mise à niveau antérieure
        self.assertIn("banque.v1.bak.db", scan(self.dir, ["Lidl", "Paie"]))
        db.prepare_storage(self.path, self.key, extra=[self.dir / "banque.v1.bak.db"])
        self.assertEqual(scan(self.dir, ["Lidl", "Paie", "Compte Courant"]), {})
        conn = db.connect(self.path, self.key)
        db.bootstrap_database(conn, None, backup_dir=self.dir, key=self.key)   # nouvelle sauvegarde : chiffrée aussi
        conn.close()
        self.assertEqual(scan(self.dir, ["Lidl", "Paie", "Compte Courant"]), {})
        backup = db.connect(self.dir / "banque.v1.bak.db", self.key)
        self.assertEqual(backup.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 3)
        backup.close()

    def test_json_import_straight_into_an_encrypted_database(self):
        from test_services import LEGACY
        (self.dir / "banque_data.json").write_text(LEGACY, encoding="utf-8")
        conn = db.connect(self.path, self.key)
        db.bootstrap_database(conn, self.dir / "banque_data.json", key=self.key)
        self.assertEqual(services.balances_payload(conn, 1)["total"], 3040.3)
        conn.close()
        self.assertEqual(scan(self.dir, ["Supermarché", "secret-en-clair"]).get("banque.db"), None)


@unittest.skipUnless(db.cipher_available(), "sqlcipher3 n'est pas installé")
class BackupScriptTests(unittest.TestCase):
    """scripts/backup.py : copie à chaud cohérente, chiffrée, jamais écrasante."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.key = os.urandom(32).hex()
        (self.dir / "k").write_text(self.key + "\n")
        self.env = {"DATA_DIR": str(self.dir), "DB_KEY_FILE": str(self.dir / "k")}
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import backup
        self.backup = backup
        self.conn = db.connect(self.dir / "banque.db", self.key)          # l'application est « en marche » : connexion ouverte, WAL actif
        db.bootstrap_database(self.conn, None, key=self.key)
        populate(self.conn)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_hot_backup_is_consistent_encrypted_and_restorable(self):
        target = self.dir / "backups" / "copie.db"
        self.assertEqual(self.backup.main(["backup.py", str(target)], self.env), 0)
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["copie.db"], "pas de .partial résiduel")
        self.assertEqual(oct(target.stat().st_mode & 0o777), "0o600")
        self.assertEqual(scan(target.parent), {}, "rien de lisible dans la sauvegarde")
        restored = db.connect(target, self.key)
        self.assertEqual(payloads(restored), payloads(self.conn))
        restored.close()

    def test_default_name_and_never_overwrites(self):
        self.assertEqual(self.backup.main(["backup.py"], self.env), 0)
        made = list((self.dir / "backups").glob("banque-*.db"))
        self.assertEqual(len(made), 1)
        before = made[0].read_bytes()
        self.assertEqual(self.backup.main(["backup.py", str(made[0])], self.env), 1)
        self.assertEqual(made[0].read_bytes(), before)

    def test_wrong_key_makes_the_script_fail_without_leaving_a_file(self):
        (self.dir / "k").write_text(os.urandom(32).hex())
        target = self.dir / "b" / "x.db"
        self.assertEqual(self.backup.main(["backup.py", str(target)], self.env), 1)
        self.assertEqual([p.name for p in target.parent.iterdir()] if target.parent.exists() else [], [])


class KeyConfigTests(unittest.TestCase):
    """Lecture/validation de la clé (aucune dépendance à SQLCipher)."""

    KEY = "ab" * 32

    def test_no_key_means_unencrypted(self):
        self.assertIsNone(config.read_db_key({}))
        self.assertIsNone(config.read_db_key({"DB_KEY": "   ", "DB_KEY_FILE": ""}))

    def test_key_from_env_is_normalised(self):
        self.assertEqual(config.read_db_key({"DB_KEY": ("AB" * 32)}), self.KEY)

    def test_key_file_with_trailing_newline_and_precedence_over_env(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "db_key"
            f.write_text(self.KEY + "\n", encoding="utf-8")
            self.assertEqual(config.read_db_key({"DB_KEY_FILE": str(f), "DB_KEY": "cd" * 32}), self.KEY)

    def test_invalid_or_unreadable_configuration_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "vide"; empty.write_text("", encoding="utf-8")
            short = Path(d) / "court"; short.write_text("abc", encoding="utf-8")
            cases = [{"DB_KEY": "abc"}, {"DB_KEY": "zz" * 32}, {"DB_KEY": "a" * 65},
                     {"DB_KEY_FILE": str(Path(d) / "absent")}, {"DB_KEY_FILE": str(empty)}, {"DB_KEY_FILE": str(short)},
                     {"DB_KEY_FILE": d}]                                      # un dossier à la place d'un fichier
            for env in cases:
                with self.assertRaises(config.ConfigError, msg=env):
                    config.read_db_key(env)

    def test_key_is_never_displayed(self):
        s = config.Settings(data_dir=Path("data"), db_key=self.KEY)
        self.assertNotIn(self.KEY, repr(s))
        with self.assertRaises(config.ConfigError) as ctx:
            config.read_db_key({"DB_KEY": "abc"})
        self.assertNotIn("abc", str(ctx.exception).split("fichier")[0].replace("DB_KEY", ""))


if __name__ == "__main__":
    unittest.main()
