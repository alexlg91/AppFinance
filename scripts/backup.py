#!/usr/bin/env python3
"""Sauvegarde À CHAUD et COHÉRENTE de la base (application en marche), chiffrée avec la même clé.

    docker compose exec banque python scripts/backup.py                          # -> /data/backups/banque-AAAAMMJJ-HHMMSS.db
    docker compose exec banque python scripts/backup.py /data/backups/ma-copie.db

Pourquoi pas `cp` ou `sqlite3 .backup` ?  La base est en mode WAL : copier le seul fichier .db pendant que l'application
écrit peut donner une copie incohérente, et le client `sqlite3` standard ne sait pas lire une base SQLCipher.
Ce script utilise l'API de sauvegarde en ligne de SQLite, vérifie la copie (empreinte de toutes les tables) puis la
protège (droits 600). La copie reste chiffrée : sans la clé, elle est illisible — conservez donc aussi la clé (README).
Ne remplace jamais un fichier existant. Lit DATA_DIR / DB_KEY_FILE / DB_KEY comme l'application.
"""
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402


def backup(settings: config.Settings, target: Path) -> Path:
    if target.exists():
        raise FileExistsError(f"{target} existe déjà : choisissez un autre nom (aucun fichier n'est jamais écrasé).")
    if not settings.db_path.exists():
        raise FileNotFoundError(f"Base introuvable : {settings.db_path}")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = settings.db_key
    source = db.connect(settings.db_path, key)
    partial = target.with_name(target.name + ".partial")          # on n'expose jamais une copie à moitié écrite
    try:
        dest = db.open_backup_target(partial, key)
        try:
            source.backup(dest)
        finally:
            dest.close()
        copy = db.connect(partial, key)
        try:
            same = db._fingerprint(copy) == db._fingerprint(source) and copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            copy.close()
        if not same:
            raise RuntimeError("La copie n'est pas identique à la base (sauvegarde annulée).")
        if key is not None and db.file_state(partial) != "encrypted":
            raise RuntimeError("La copie n'est pas chiffrée (sauvegarde annulée).")
        os.chmod(partial, 0o600)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        source.close()
    return target


def main(argv: list[str], environ=os.environ) -> int:
    try:
        settings = config.Settings(data_dir=Path(environ.get("DATA_DIR", "data")), db_key=config.read_db_key(environ))
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = Path(argv[1]) if len(argv) > 1 else settings.data_dir / "backups" / f"banque-{stamp}.db"
        done = backup(settings, target)
    except (config.ConfigError, db.EncryptionError, OSError, RuntimeError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    state = "chiffrée" if settings.db_key else "NON chiffrée (aucune clé configurée)"
    print(f"Sauvegarde {state} : {done} ({done.stat().st_size // 1024} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
