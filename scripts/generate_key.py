#!/usr/bin/env python3
"""Génère la clé de chiffrement de la base (256 bits aléatoires, en hexadécimal) dans un fichier protégé.

    python scripts/generate_key.py                 # écrit secrets/db_key
    python scripts/generate_key.py /chemin/db_key  # autre emplacement

  * Le fichier est créé en lecture/écriture pour VOUS seul (chmod 600), dans un dossier en 700.
  * Ne remplace JAMAIS un fichier existant : écraser la clé rendrait la base définitivement illisible.
  * La clé n'est pas affichée (elle resterait dans l'historique/les journaux du terminal).
  * Équivalent sans Python :  mkdir -p secrets && (umask 077; openssl rand -hex 32 > secrets/db_key)
"""
import os
import secrets
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "secrets/db_key")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # O_EXCL : échoue si le fichier existe déjà
    except FileExistsError:
        print(f"REFUS : {path} existe déjà. Écraser la clé rendrait la base chiffrée définitivement illisible.\n"
              f"Conservez ce fichier ; pour repartir de zéro, supprimez-le vous-même en connaissance de cause.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Impossible de créer {path} : {exc}", file=sys.stderr)
        return 1
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(secrets.token_hex(32) + "\n")
    print(f"Clé créée : {path}  (64 caractères hexadécimaux, droits 600)\n\n"
          f"⚠  FAITES-EN UNE COPIE MAINTENANT, ailleurs que sur le NAS (gestionnaire de mots de passe, clé USB rangée) :\n"
          f"   sans cette clé, la base chiffrée est IRRÉCUPÉRABLE — il n'existe aucune procédure de secours.\n"
          f"   Pour l'afficher une fois, à l'abri des regards :  cat {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
