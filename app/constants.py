"""Constantes métier partagées (identiques à l'application Streamlit d'origine)."""

TX_ENTREE = "Entrée"
TX_SORTIE = "Sortie"
TX_TRANSFERT = "Transfert"
TX_TYPES = (TX_ENTREE, TX_SORTIE, TX_TRANSFERT)

# Catégorie « système » : imposée aux transferts, non supprimable, absente des paramètres.
INTERNAL_CATEGORY = "Virement interne"

DEFAULT_ACCOUNTS = ["Compte Courant", "Livret A", "Livret B"]

DEFAULT_CATEGORIES = [
    "Salaire", "Aide", "Virement", "Abonnement", "Voiture",
    "Cigarettes", "Occasion", "Appartement", "Course",
]

DEFAULT_CATEGORY_COLORS = {
    "Salaire": "#22C55E",
    "Aide": "#10B981",
    "Virement": "#3B82F6",
    "Abonnement": "#6366F1",
    "Voiture": "#8B5CF6",
    "Cigarettes": "#EC4899",
    "Occasion": "#F59E0B",
    "Appartement": "#EF4444",
    "Course": "#14B8A6",
    INTERNAL_CATEGORY: "#6B7280",
}

FALLBACK_COLOR = "#3B82F6"

# Premier utilisateur (administrateur) créé à l'installation ou lors de la migration depuis la v1 / Streamlit.
DEFAULT_ADMIN_USERNAME = "Admin"
