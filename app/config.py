"""Configuration via variables d'environnement (12-factor)."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")
KEY_HELP = ("La clé de chiffrement doit être une valeur aléatoire de 64 caractères hexadécimaux (256 bits). "
            "Pour en générer une : `openssl rand -hex 32 > secrets/db_key && chmod 600 secrets/db_key` "
            "ou `python scripts/generate_key.py`.")


class ConfigError(RuntimeError):
    """Configuration invalide : l'application refuse de démarrer (jamais de repli silencieux)."""


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def parse_db_key(raw: str, source: str) -> str:
    key = (raw or "").strip()
    if not KEY_RE.match(key):
        raise ConfigError(f"Clé de chiffrement invalide ({source}). {KEY_HELP}")
    return key.lower()


def read_db_key(environ=os.environ) -> str | None:
    """Clé de chiffrement de la base : `DB_KEY_FILE` (recommandé : secret Docker) sinon `DB_KEY`.
    Aucune clé configurée -> None (base non chiffrée, comme avant).
    Clé configurée mais illisible/invalide -> ConfigError : on ne démarre PAS en clair par erreur."""
    key_file = (environ.get("DB_KEY_FILE") or "").strip()
    if key_file:
        try:
            raw = Path(key_file).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ConfigError(f"DB_KEY_FILE={key_file} : fichier introuvable. {KEY_HELP}") from None
        except OSError as exc:
            uid = os.getuid() if hasattr(os, "getuid") else "?"
            raise ConfigError(
                f"DB_KEY_FILE={key_file} : lecture impossible pour l'utilisateur {uid} ({exc}). "
                f"Le fichier (sur l'hôte, ex. ./secrets/db_key) doit appartenir à l'utilisateur du conteneur (PUID) : "
                f"`sudo chown $(id -u):$(id -g) ./secrets/db_key && chmod 600 ./secrets/db_key`.") from exc
        return parse_db_key(raw, f"fichier {key_file}")
    raw_env = (environ.get("DB_KEY") or "").strip()
    if raw_env:
        return parse_db_key(raw_env, "variable DB_KEY")
    return None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    session_ttl_days: int = 30      # durée de vie (glissante) de la session
    cookie_secure: bool = False     # passer à true derrière HTTPS
    enable_docs: bool = False       # expose /api/docs (Swagger) si true
    db_key: str | None = field(default=None, repr=False)   # clé SQLCipher (jamais affichée) ; None = base non chiffrée

    @property
    def db_path(self) -> Path:
        return self.data_dir / "banque.db"

    @property
    def v1_backup_path(self) -> Path:
        return self.data_dir / "banque.v1.bak.db"

    @property
    def legacy_json_path(self) -> Path:
        # Même nom/dossier que l'ancienne appli : monter l'ancien dossier `data/` suffit.
        return self.data_dir / "banque_data.json"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            session_ttl_days=max(1, int(os.getenv("SESSION_TTL_DAYS", "30"))),
            cookie_secure=_env_bool("COOKIE_SECURE", False),
            enable_docs=_env_bool("ENABLE_DOCS", False),
            db_key=read_db_key(),
        )
