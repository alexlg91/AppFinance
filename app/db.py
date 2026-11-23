"""Accès SQLite : schéma v2 (multi-utilisateurs), mise à niveau depuis la v1, initialisation,
et chiffrement de la base au repos (SQLCipher, AES-256) lorsqu'une clé est configurée."""
import hashlib
import logging
import os
import sqlite3
from pathlib import Path

from . import constants as C
from .config import KEY_RE

try:  # SQLCipher : requis seulement si une clé de chiffrement est configurée
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError:  # pragma: no cover
    sqlcipher = None

log = logging.getLogger("banque.db")


class EncryptionError(RuntimeError):
    """Problème de chiffrement (clé absente/incorrecte, conversion impossible) : arrêt franc, jamais de repli en clair."""


# Les exceptions de sqlcipher3 NE dérivent PAS de celles de sqlite3 : toujours passer par ces tuples.
INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((sqlcipher.IntegrityError,) if sqlcipher else ())
OPERATIONAL_ERRORS = (sqlite3.OperationalError,) + ((sqlcipher.OperationalError,) if sqlcipher else ())
DATABASE_ERRORS = (sqlite3.DatabaseError,) + ((sqlcipher.DatabaseError,) if sqlcipher else ())

SQLITE_MAGIC = b"SQLite format 3\x00"     # en-tête d'un fichier SQLite NON chiffré
TMP_SUFFIX = ".encrypting"                # conversion en cours (copie chiffrée)
OLD_SUFFIX = ".plain-to-delete"           # ancienne copie en clair, avant effacement
WRONG_KEY = ("Impossible d'ouvrir la base : clé de chiffrement incorrecte (ou base non chiffrée). "
             "Vérifiez DB_KEY_FILE / DB_KEY : c'est la clé qui a servi à chiffrer cette base.")

SCHEMA_VERSION = 2

T_META = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)"""

# Identifiant insensible à la casse (ASCII). password_hash = SHA-256 hexadécimal (compatible avec l'ancien JSON).
T_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL DEFAULT '',
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)"""

# Toutes les données métier appartiennent à un utilisateur (isolation stricte, suppression en cascade).
T_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS accounts (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    position      INTEGER NOT NULL,
    initial_cents INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, name)
)"""

T_CATEGORIES = """
CREATE TABLE IF NOT EXISTS categories (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    position INTEGER NOT NULL,
    color    TEXT NOT NULL,
    system   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, name)
)"""

# AUTOINCREMENT : un ID supprimé n'est jamais réattribué.
T_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date           TEXT NOT NULL,                 -- ISO 8601 : AAAA-MM-JJ
    type           TEXT NOT NULL CHECK (type IN ('Entrée', 'Sortie', 'Transfert')),
    account        TEXT NOT NULL,
    target_account TEXT,
    category       TEXT NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    amount_cents   INTEGER NOT NULL
)"""

# Seul le hash SHA-256 du jeton est stocké : une fuite de la base ne donne pas de session valide.
T_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
)"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tx_user_date    ON transactions(user_id, date)",
    "CREATE INDEX IF NOT EXISTS idx_tx_user_account ON transactions(user_id, type, account)",
    "CREATE INDEX IF NOT EXISTS idx_tx_user_target  ON transactions(user_id, type, target_account)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user   ON sessions(user_id)",
]

TABLES = [T_META, T_USERS, T_ACCOUNTS, T_CATEGORIES, T_TRANSACTIONS, T_SESSIONS]
SYSTEM_CATEGORY_POSITION = 10_000


def cipher_available() -> bool:
    return sqlcipher is not None


def _driver(key):
    if key is None:
        return sqlite3
    if sqlcipher is None:
        raise EncryptionError("Une clé de chiffrement est configurée mais SQLCipher n'est pas installé "
                              "(pip install sqlcipher3-binary).")
    return sqlcipher


def _pragma_key(key: str) -> str:
    """Clé BRUTE de 256 bits (« x'…' ») : SQLCipher n'applique alors aucune dérivation (0,2 ms par connexion
    au lieu de ~165 ms avec une phrase de passe — or l'appli ouvre une connexion par requête)."""
    if not KEY_RE.match(key or ""):
        raise EncryptionError("Clé de chiffrement invalide (64 caractères hexadécimaux attendus).")
    return f"PRAGMA key = \"x'{key}'\""


def connect(path, key: str | None = None):
    """Ouvre une connexion (1 par requête). WAL = lectures non bloquées par les écritures.
    Avec `key` : base chiffrée SQLCipher ; la clé est vérifiée immédiatement (EncryptionError si incorrecte)."""
    drv = _driver(key)
    conn = drv.connect(str(path), timeout=10, check_same_thread=False)
    try:
        if key is not None:
            conn.execute("PRAGMA cipher_log_level = NONE")   # pas de « ERROR CORE » bruts dans les logs : EncryptionError suffit
            conn.execute(_pragma_key(key))          # DOIT être la toute première instruction (hors journalisation)
            try:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            except drv.DatabaseError as exc:
                raise EncryptionError(WRONG_KEY) from exc
        conn.row_factory = drv.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except BaseException:
        conn.close()
        raise
    return conn


# ------------------------------------------------------------------ chiffrement au repos
def file_state(path) -> str:
    """'absent' (inexistant ou vide) | 'plain' (SQLite en clair) | 'encrypted' (contenu illisible : chiffré, ou corrompu)."""
    try:
        if os.path.getsize(path) == 0:
            return "absent"
        with open(path, "rb") as f:
            head = f.read(len(SQLITE_MAGIC))
    except FileNotFoundError:
        return "absent"
    return "plain" if head == SQLITE_MAGIC else "encrypted"


def _sidecar(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


def _shred(path: Path) -> None:
    """Écrase puis supprime un fichier (au mieux : sans effet garanti sur SSD, systèmes de fichiers
    copy-on-write — btrfs/ZFS — et instantanés/sauvegardes du NAS ; voir le README)."""
    try:
        remaining = path.stat().st_size
        with open(path, "r+b") as f:
            while remaining > 0:
                n = min(1 << 20, remaining)
                f.write(b"\0" * n)
                remaining -= n
            f.flush()
            os.fsync(f.fileno())
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("Écrasement de %s impossible (%s) : suppression simple.", path, exc)
    path.unlink(missing_ok=True)


def _fingerprint(conn) -> dict:
    """Empreinte du contenu (par table : nombre de lignes + SHA-256 de toutes les lignes) pour PROUVER que la
    copie chiffrée est identique avant de supprimer l'original."""
    out = {}
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
        digest, count = hashlib.sha256(), 0
        for row in conn.execute(f'SELECT * FROM "{table.replace(chr(34), chr(34) * 2)}" ORDER BY rowid'):
            digest.update(repr(tuple(row)).encode("utf-8"))
            count += 1
        out[table] = (count, digest.hexdigest())
    out["__user_version__"] = conn.execute("PRAGMA user_version").fetchone()[0]
    return out


def _recover_leftovers(path: Path) -> None:
    """Reprise après un arrêt brutal pendant une conversion (chaque état intermédiaire est sûr)."""
    tmp, old = _sidecar(path, TMP_SUFFIX), _sidecar(path, OLD_SUFFIX)
    if old.exists():
        if not path.exists() and tmp.exists():      # arrêt entre « clair -> .plain-to-delete » et « .encrypting -> base »
            os.replace(tmp, path)
            log.warning("Conversion de %s reprise et terminée.", path.name)
        elif not path.exists():                     # cas anormal : ne JAMAIS perdre la seule copie existante
            os.replace(old, path)
            log.warning("%s restauré tel quel (conversion avortée).", path.name)
            return
        _shred(old)
    elif tmp.exists():                              # copie chiffrée incomplète : l'original en clair est intact
        tmp.unlink()


def encrypt_file(path, key: str) -> None:
    """Convertit une base SQLite EN CLAIR en base chiffrée, sur place et sans perte :
    copie chiffrée -> vérification d'identité (empreintes + intégrité) -> remplacement -> effacement de l'ancien fichier."""
    path = Path(path)
    tmp, old = _sidecar(path, TMP_SUFFIX), _sidecar(path, OLD_SUFFIX)
    drv = _driver(key)
    tmp.unlink(missing_ok=True)

    src = drv.connect(str(path), isolation_level=None)       # sans clé : lecture de la base en clair
    try:
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")       # rapatrie le journal WAL dans le fichier principal
        before = _fingerprint(src)
        src.execute("ATTACH DATABASE ? AS enc KEY ?", (str(tmp), f"x'{key}'"))
        src.execute("SELECT sqlcipher_export('enc')")
        src.execute(f"PRAGMA enc.user_version = {int(before['__user_version__'])}")
        src.execute("DETACH DATABASE enc")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        src.close()

    check = connect(tmp, key)                                # ré-ouverture INDÉPENDANTE avec la clé
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok" \
            and not check.execute("PRAGMA cipher_integrity_check").fetchall()
        after = _fingerprint(check)
    finally:
        check.close()
    if not ok or after != before:
        tmp.unlink(missing_ok=True)
        raise EncryptionError(f"La copie chiffrée de {path.name} n'est pas identique à l'original : "
                              f"conversion annulée, la base en clair n'a pas été modifiée.")

    for suffix in ("-wal", "-shm"):                          # journaux orphelins de l'ancienne base : ne doivent jamais
        _shred(Path(str(path) + suffix))                     # être rejoués sur la nouvelle
    os.replace(path, old)
    os.replace(tmp, path)
    _shred(old)
    log.warning("Base %s chiffrée (SQLCipher AES-256) ; l'ancienne copie en clair a été effacée.", path.name)


def prepare_storage(db_path, key: str | None, extra=()) -> None:
    """À appeler AVANT d'ouvrir la base. Garantit l'état « chiffré » demandé par la configuration :
      - clé configurée + base en clair   -> conversion automatique (idem pour les fichiers `extra`, ex. sauvegarde v1) ;
      - pas de clé + base chiffrée       -> arrêt avec explication (au lieu de créer une base vide à côté) ;
      - pas de clé + base en clair       -> fonctionnement inchangé, avec un avertissement."""
    db_path = Path(db_path)
    for p in (db_path, *map(Path, extra)):
        _recover_leftovers(p)
    state = file_state(db_path)
    if key is None:
        if state == "encrypted":
            raise EncryptionError(f"{db_path.name} est chiffrée mais aucune clé n'est configurée. "
                                  f"Définissez DB_KEY_FILE (ou DB_KEY) : l'application refuse de démarrer "
                                  f"plutôt que de créer une nouvelle base vide à côté.")
        if state == "plain":
            log.warning("⚠ Base NON chiffrée : %s est lisible par quiconque accède au dossier. "
                        "Configurez DB_KEY_FILE pour la chiffrer (voir README).", db_path)
        return
    for p in (db_path, *map(Path, extra)):
        if file_state(p) == "plain":
            encrypt_file(p, key)


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


# ------------------------------------------------------------------ utilisateurs & valeurs par défaut
def create_user_row(conn: sqlite3.Connection, username: str, password_hash: str = "",
                    is_admin: bool = False) -> int:
    return conn.execute(
        "INSERT INTO users(username, password_hash, is_admin) VALUES(?, ?, ?)",
        (username, password_hash, 1 if is_admin else 0)).lastrowid


def seed_user_defaults(conn: sqlite3.Connection, uid: int) -> None:
    """Comptes et catégories par défaut d'un NOUVEL utilisateur (mêmes que l'ancienne appli)."""
    conn.executemany(
        "INSERT INTO accounts(user_id, name, position, initial_cents) VALUES(?, ?, ?, 0)",
        [(uid, n, i) for i, n in enumerate(C.DEFAULT_ACCOUNTS)],
    )
    conn.executemany(
        "INSERT INTO categories(user_id, name, position, color, system) VALUES(?, ?, ?, ?, 0)",
        [(uid, n, i, C.DEFAULT_CATEGORY_COLORS.get(n, C.FALLBACK_COLOR))
         for i, n in enumerate(C.DEFAULT_CATEGORIES)],
    )


def ensure_system_categories(conn: sqlite3.Connection) -> None:
    """« Virement interne » existe pour chaque utilisateur (imposée aux transferts, non supprimable)."""
    conn.execute(
        "INSERT OR IGNORE INTO categories(user_id, name, position, color, system) "
        "SELECT id, ?, ?, ?, 1 FROM users",
        (C.INTERNAL_CATEGORY, SYSTEM_CATEGORY_POSITION, C.DEFAULT_CATEGORY_COLORS[C.INTERNAL_CATEGORY]),
    )


# ------------------------------------------------------------------ schéma & mise à niveau
def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (name,)).fetchone() is not None


def open_backup_target(path, key: str | None):
    """Fichier cible d'une copie de sauvegarde : chiffré avec la même clé quand le chiffrement est actif."""
    target = _driver(key).connect(str(path))
    if key is not None:
        target.execute(_pragma_key(key))
    return target


def _upgrade_v1_to_v2(conn: sqlite3.Connection, backup_dir: Path | None, key: str | None = None) -> None:
    """v1 (un seul utilisateur implicite) -> v2 : toutes les données passent à l'utilisateur « Admin ».

    - copie de sauvegarde `banque.v1.bak.db` AVANT toute modification ;
    - transaction unique : en cas d'erreur, rollback complet et l'application refuse de démarrer ;
    - IDs de transactions, ordre des comptes/catégories et mot de passe conservés ; les sessions v1 sont abandonnées.
    """
    log.warning("Mise à niveau de la base v1 -> v2 (multi-utilisateurs)…")
    if backup_dir is not None:
        backup = open_backup_target(Path(backup_dir) / "banque.v1.bak.db", key)
        try:
            conn.backup(backup)
        finally:
            backup.close()

    protected = get_meta(conn, "password_enabled") == "1"
    old_hash = (get_meta(conn, "app_password", "") or "") if protected else ""
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'transactions'").fetchone()
    old_seq = row["seq"] if row else 0
    conn.commit()

    try:
        conn.execute("BEGIN")
        for table in ("accounts", "categories", "transactions", "sessions"):
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_v1")
        for ddl in TABLES:
            conn.execute(ddl)
        uid = create_user_row(conn, C.DEFAULT_ADMIN_USERNAME, old_hash, is_admin=True)
        conn.execute("INSERT INTO accounts(user_id, name, position, initial_cents) "
                     "SELECT ?, name, position, initial_cents FROM accounts_v1", (uid,))
        conn.execute("INSERT INTO categories(user_id, name, position, color, system) "
                     "SELECT ?, name, position, color, system FROM categories_v1", (uid,))
        conn.execute("INSERT INTO transactions(id, user_id, date, type, account, target_account, category, name, amount_cents) "
                     "SELECT id, ?, date, type, account, target_account, category, name, amount_cents FROM transactions_v1", (uid,))
        conn.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'transactions'", (old_seq,))
        for table in ("accounts", "categories", "transactions", "sessions"):
            conn.execute(f"DROP TABLE {table}_v1")        # supprime aussi les anciens index
        conn.execute("DELETE FROM meta WHERE key IN ('password_enabled', 'app_password')")
        for index in INDEXES:
            conn.execute(index)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log.warning("Mise à niveau terminée : vos données appartiennent à l'utilisateur « %s ».", C.DEFAULT_ADMIN_USERNAME)


def bootstrap_database(conn: sqlite3.Connection, legacy_json: Path | None = None,
                       backup_dir: Path | None = None, key: str | None = None) -> None:
    """Crée / met à niveau le schéma et, au tout premier démarrage uniquement, importe `banque_data.json`.

    - Le JSON n'est JAMAIS modifié ni supprimé (rollback possible vers Streamlit).
    - Import atomique : en cas d'erreur, rien n'est écrit et l'application refuse de démarrer
      avec un message explicite (mieux que démarrer vide et laisser croire que les données ont disparu).
    """
    from . import migration  # import local : évite l'import circulaire

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        if _table_exists(conn, "transactions"):          # base créée par la v1 de l'application
            _upgrade_v1_to_v2(conn, backup_dir, key)
        else:                                            # base neuve
            with conn:
                for statement in (*TABLES, *INDEXES):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    if get_meta(conn, "initialized") != "1":
        with conn:  # transaction unique
            if legacy_json is not None and Path(legacy_json).is_file():
                stats = migration.import_legacy_json(conn, legacy_json)
                log.info("Migration de %s terminée : %s", legacy_json, stats)
            else:
                uid = create_user_row(conn, C.DEFAULT_ADMIN_USERNAME, "", is_admin=True)
                seed_user_defaults(conn, uid)
                log.info("Base initialisée (utilisateur « %s », valeurs par défaut).", C.DEFAULT_ADMIN_USERNAME)
            set_meta(conn, "initialized", "1")

    with conn:
        ensure_system_categories(conn)
