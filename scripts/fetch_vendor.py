"""Télécharge Chart.js (version épinglée) dans app/static/vendor/.

Exécuté automatiquement au build de l'image Docker ; à lancer à la main pour un usage sans Docker :
    python scripts/fetch_vendor.py

Le fichier est servi localement : à l'exécution, l'application n'a besoin d'aucun CDN
(elle fonctionne hors-ligne, et la CSP `script-src 'self'` reste stricte).
"""
import sys
import urllib.request
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "vendor"

FILES = {
    "chart.umd.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js",
}
MIN_SIZE = 100_000  # garde-fou : une page d'erreur HTML ne passe pas pour la bibliothèque


def main() -> int:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        dest = VENDOR_DIR / name
        if dest.exists() and dest.stat().st_size >= MIN_SIZE:
            print(f"déjà présent : {dest}")
            continue
        print(f"téléchargement : {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "banque-fetch-vendor"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        if len(data) < MIN_SIZE or b"Chart" not in data[:200_000]:
            print(f"ERREUR : contenu inattendu pour {url} ({len(data)} octets)", file=sys.stderr)
            return 1
        dest.write_bytes(data)
        print(f"écrit : {dest} ({len(data) // 1024} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
