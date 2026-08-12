import streamlit as st
import pandas as pd
import plotly.express as px
import datetime
import calendar
import json
import os

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Gestion Bancaire", layout="wide", page_icon="💰")

# --- STYLE CSS PERSONNALISÉ (DESIGN COMPACT) ---
st.markdown("""
<style>
    /* Réduction des marges globales de la page */
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 1.2rem !important;
    }

    /* Titre principal rouge avec ligne rouge fine */
    h1 {
        color: #E53E3E !important;
        border-bottom: 2px solid #E53E3E;
        padding-bottom: 4px;
        margin-bottom: 0.6rem !important;
        font-size: 1.7rem !important;
    }

    /* Autres titres (h2, h3) plus compacts */
    h2 {
        color: #FFFFFF !important;
        font-size: 1.2rem !important;
        margin-top: 0.3rem !important;
        margin-bottom: 0.3rem !important;
    }
    h3 {
        color: #FFFFFF !important;
        font-size: 1.05rem !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0.2rem !important;
    }

    /* Cartes des soldes (Metrics) compactes */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-left: 4px solid #E53E3E;
        border-radius: 6px;
        padding: 6px 12px;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
    }
    
    div[data-testid="stMetricLabel"] {
        color: #4B5563 !important;
        font-weight: 600;
        font-size: 0.82rem !important;
    }
    
    div[data-testid="stMetricValue"] {
        color: #111827 !important;
        font-size: 1.25rem !important;
    }

    /* Style des Onglets (Tabs) */
    button[data-baseweb="tab"] {
        font-weight: bold;
        padding-top: 4px !important;
        padding-bottom: 4px !important;
    }
    button[aria-selected="true"] {
        color: #E53E3E !important;
        border-bottom-color: #E53E3E !important;
    }

    /* Boutons */
    .stButton > button {
        border-radius: 6px;
        transition: all 0.2s ease-in-out;
    }

    /* Blocs déroulants et formulaires */
    div[data-testid="stExpander"], div[data-testid="stForm"] {
        border: 1px solid #E5E7EB !important;
        border-radius: 8px;
    }

    /* Ligne de séparation compacte */
    hr {
        margin: 0.5rem 0 !important;
        border-color: #E5E7EB !important;
    }
</style>
""", unsafe_allow_html=True)

# --- NOM DU FICHIER DE SAUVEGARDE LOCALE ---
DATA_FILE = "banque_data.json"

DEFAULT_CATEGORIES = ["Salaire", "Aide", "Virement", "Abonnement", "Voiture", "Cigarettes", "Occasion", "Appartement", "Course"]

DEFAULT_CATEGORY_COLORS = {
    "Salaire": "#22C55E",
    "Aide": "#10B981",
    "Virement": "#3B82F6",
    "Abonnement": "#6366F1",
    "Voiture": "#8B5CF6",
    "Cigarettes": "#EC4899",
    "Occasion": "#F59E0B",
    "Appartement": "#EF4444",
    "Course": "#14B8A6"
}

# --- FONCTIONS DE PERSISTANCE DES DONNÉES ---
def charger_donnees():
    """Charge les données depuis le fichier JSON s'il existe."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            comptes = data.get("comptes", ['Compte Courant', 'Livret A', 'Livret Jeune'])
            soldes_initiaux = data.get("soldes_initiaux", {'Compte Courant': 0.0, 'Livret A': 0.0, 'Livret Jeune': 0.0})
            categories = data.get("categories", DEFAULT_CATEGORIES.copy())
            
            category_colors = data.get("category_colors", {})
            for cat in categories:
                if cat not in category_colors:
                    category_colors[cat] = DEFAULT_CATEGORY_COLORS.get(cat, "#3B82F6")

            trans_list = data.get("transactions", [])
            if trans_list:
                df = pd.DataFrame(trans_list)
                df['Date'] = pd.to_datetime(df['Date']).dt.date
            else:
                df = pd.DataFrame(columns=['ID', 'Date', 'Jour', 'Mois', 'Année', 'Type', 'Compte', 'Compte Cible', 'Catégorie', 'Nom', 'Montant'])
            
            return comptes, soldes_initiaux, categories, category_colors, df
        except Exception as e:
            st.error(f"Erreur lors de la lecture des données sauvegardées : {e}")
            
    return (
        ['Compte Courant', 'Livret A', 'Livret Jeune'],
        {'Compte Courant': 0.0, 'Livret A': 0.0, 'Livret Jeune': 0.0},
        DEFAULT_CATEGORIES.copy(),
        DEFAULT_CATEGORY_COLORS.copy(),
        pd.DataFrame(columns=['ID', 'Date', 'Jour', 'Mois', 'Année', 'Type', 'Compte', 'Compte Cible', 'Catégorie', 'Nom', 'Montant'])
    )

def sauvegarder_donnees():
    """Sauvegarde les données dans le fichier JSON."""
    df_to_save = st.session_state['transactions'].copy()
    if not df_to_save.empty:
        df_to_save['Date'] = df_to_save['Date'].astype(str)
        trans_list = df_to_save.to_dict(orient="records")
    else:
        trans_list = []
        
    data = {
        "comptes": st.session_state['comptes'],
        "soldes_initiaux": st.session_state['soldes_initiaux'],
        "categories": st.session_state['categories'],
        "category_colors": st.session_state['category_colors'],
        "transactions": trans_list
    }
    
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- INITIALISATION DE LA SESSION ---
if 'initialized' not in st.session_state:
    comptes, soldes_initiaux, categories, category_colors, df = charger_donnees()
    st.session_state['comptes'] = comptes
    st.session_state['soldes_initiaux'] = soldes_initiaux
    st.session_state['categories'] = categories
    st.session_state['category_colors'] = category_colors
    st.session_state['transactions'] = df
    st.session_state['initialized'] = True

st.title("💰 Mon Gestionnaire de Finances")

df = st.session_state['transactions']

mois_dict = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 
             7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}

# --- CALCUL DES SOLDES ACTUELS ---
def calculer_soldes_actuels():
    soldes = st.session_state['soldes_initiaux'].copy()
    for _, row in st.session_state['transactions'].iterrows():
        montant = float(row['Montant'])
        if row['Type'] == 'Entrée':
            if row['Compte'] in soldes:
                soldes[row['Compte']] += montant
        elif row['Type'] == 'Sortie':
            if row['Compte'] in soldes:
                soldes[row['Compte']] -= montant
        elif row['Type'] == 'Transfert':
            if row['Compte'] in soldes:
                soldes[row['Compte']] -= montant
            if row['Compte Cible'] in soldes:
                soldes[row['Compte Cible']] += montant
    return soldes

# --- CREATION DES ONGLETS ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📝 Transactions", "⚙️ Paramètres"])

# ==========================================
# ONGLET 1 : DASHBOARD COMPACT
# ==========================================
with tab1:
    st.header("Tableau de bord")
    
    # 1. Barre de contrôle (Sélection d'année & de mois)
    col_dash1, col_dash2 = st.columns(2)
    annees_dispos = list(range(2020, datetime.datetime.now().year + 5))
    
    with col_dash1:
        annee_dash = st.selectbox(
            "Année du Dashboard", 
            annees_dispos, 
            index=annees_dispos.index(datetime.datetime.now().year),
            key="dash_annee"
        )
    with col_dash2:
        mois_dash = st.selectbox(
            "Mois à analyser", 
            list(mois_dict.keys()), 
            format_func=lambda x: mois_dict[x], 
            index=datetime.datetime.now().month - 1,
            key="dash_mois"
        )

    # 2. Solde actuel des comptes (Cartes métriques compactes)
    soldes_actuels = calculer_soldes_actuels()
    cols = st.columns(len(soldes_actuels) if len(soldes_actuels) > 0 else 1)
    for i, (compte, solde) in enumerate(soldes_actuels.items()):
        cols[i].metric(label=compte, value=f"{solde:.2f} €")

    st.divider()

    if df.empty:
        st.info("Aucune transaction enregistrée. Rendez-vous dans l'onglet 'Transactions' pour commencer.")
    else:
        # 3. ANALYSES PLACÉES AU-DESSUS (Mois à gauche, Année à droite)
        df_in_out = df[df['Type'].isin(['Entrée', 'Sortie'])]
        df_sorties = df[df['Type'] == 'Sortie']

        col_mois, col_annee = st.columns(2)

        # --- BLOC MOIS ---
        with col_mois:
            st.subheader(f"📅 Analyse Mensuelle ({mois_dict[mois_dash]} {annee_dash})")
            
            # Balance Mensuelle
            df_in_out_mois = df_in_out[(df_in_out['Année'] == annee_dash) & (df_in_out['Mois'] == mois_dash)]
            balance_mois = df_in_out_mois.groupby('Type')['Montant'].sum()
            entrees_mois = balance_mois.get('Entrée', 0.0)
            sorties_mois = balance_mois.get('Sortie', 0.0)
            bal_mois_val = entrees_mois - sorties_mois
            color_mois = "#22C55E" if bal_mois_val >= 0 else "#EF4444"

            st.markdown(f"""
            <div style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-left: 4px solid {color_mois}; border-radius: 6px; padding: 8px 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); margin-bottom: 6px;">
                <div style="color: #4B5563; font-weight: 600; font-size: 13px;">Balance de {mois_dict[mois_dash]} {annee_dash}</div>
                <div style="color: {color_mois}; font-size: 22px; font-weight: bold; margin: 2px 0;">{bal_mois_val:.2f} €</div>
                <div style="color: #6B7280; font-size: 12px;">➕ {entrees_mois:.2f} € | ➖ {sorties_mois:.2f} €</div>
            </div>
            """, unsafe_allow_html=True)

            # Camembert du Mois
            df_mois_depenses = df_sorties[(df_sorties['Année'] == annee_dash) & (df_sorties['Mois'] == mois_dash)]
            if not df_mois_depenses.empty:
                fig_pie_mois = px.pie(
                    df_mois_depenses, 
                    values='Montant', 
                    names='Catégorie', 
                    color='Catégorie',
                    color_discrete_map=st.session_state['category_colors'],
                    hole=0.4
                )
                fig_pie_mois.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", yanchor="top", y=-0.05))
                st.plotly_chart(fig_pie_mois, use_container_width=True)
            else:
                st.info(f"Aucune dépense en {mois_dict[mois_dash]} {annee_dash}.")

        # --- BLOC ANNÉE ---
        with col_annee:
            st.subheader(f"🗓️ Analyse Annuelle ({annee_dash})")
            
            # Balance Annuelle
            balance_annee = df_in_out[df_in_out['Année'] == annee_dash].groupby('Type')['Montant'].sum()
            entrees_annee = balance_annee.get('Entrée', 0.0)
            sorties_annee = balance_annee.get('Sortie', 0.0)
            bal_annee_val = entrees_annee - sorties_annee
            color_annee = "#22C55E" if bal_annee_val >= 0 else "#EF4444"

            st.markdown(f"""
            <div style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-left: 4px solid {color_annee}; border-radius: 6px; padding: 8px 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); margin-bottom: 6px;">
                <div style="color: #4B5563; font-weight: 600; font-size: 13px;">Balance Annuelle ({annee_dash})</div>
                <div style="color: {color_annee}; font-size: 22px; font-weight: bold; margin: 2px 0;">{bal_annee_val:.2f} €</div>
                <div style="color: #6B7280; font-size: 12px;">➕ {entrees_annee:.2f} € | ➖ {sorties_annee:.2f} €</div>
            </div>
            """, unsafe_allow_html=True)

            # Camembert de l'Année
            df_an_depenses = df_sorties[df_sorties['Année'] == annee_dash]
            if not df_an_depenses.empty:
                fig_pie_an = px.pie(
                    df_an_depenses, 
                    values='Montant', 
                    names='Catégorie', 
                    color='Catégorie',
                    color_discrete_map=st.session_state['category_colors'],
                    hole=0.4
                )
                fig_pie_an.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", yanchor="top", y=-0.05))
                st.plotly_chart(fig_pie_an, use_container_width=True)
            else:
                st.info(f"Aucune dépense en {annee_dash}.")

        st.divider()

        # 4. ÉVOLUTION DES SOLDES (Placée en dessous des analyses)
        st.subheader(f"📈 Évolution des soldes en {annee_dash}")
        df_annee = df[df['Année'] == annee_dash].sort_values(by=['Mois', 'Jour'])
        
        if not df_annee.empty:
            historique = []
            soldes_temp = st.session_state['soldes_initiaux'].copy()
            
            for _, row in df_annee.iterrows():
                if row['Type'] == 'Entrée':
                    if row['Compte'] in soldes_temp:
                        soldes_temp[row['Compte']] += row['Montant']
                elif row['Type'] == 'Sortie':
                    if row['Compte'] in soldes_temp:
                        soldes_temp[row['Compte']] -= row['Montant']
                elif row['Type'] == 'Transfert': 
                    if row['Compte'] in soldes_temp:
                        soldes_temp[row['Compte']] -= row['Montant']
                    if row['Compte Cible'] in soldes_temp:
                        soldes_temp[row['Compte Cible']] += row['Montant']
                
                for cpt in st.session_state['comptes']:
                    historique.append({'Date': row['Date'], 'Compte': cpt, 'Solde': soldes_temp[cpt]})
                    
            df_hist = pd.DataFrame(historique)
            
            # Attribution des couleurs : Rouge pour Compte Courant, Bleu pour Livret A, Jaune pour les autres livrets
            account_colors = {}
            for cpt in st.session_state['comptes']:
                cpt_lower = cpt.lower()
                if 'livret a' in cpt_lower:
                    account_colors[cpt] = "#3B82F6"  # Bleu
                elif 'courant' in cpt_lower or 'compte' in cpt_lower:
                    account_colors[cpt] = "#EF4444"  # Rouge
                elif 'livret' in cpt_lower:
                    account_colors[cpt] = "#F59E0B"  # Jaune / Ambre
                else:
                    account_colors[cpt] = "#10B981"  # Vert par défaut
            
            fig_evo = px.line(
                df_hist, 
                x='Date', 
                y='Solde', 
                color='Compte', 
                markers=True,
                color_discrete_map=account_colors
            )
            fig_evo.update_layout(height=270, margin=dict(l=10, r=10, t=20, b=10))
            st.plotly_chart(fig_evo, use_container_width=True)
        else:
            st.write(f"Aucune donnée disponible pour l'année {annee_dash}.")

        st.divider()

        # 5. Moyenne mensuelle par catégorie pour l'année sélectionnée
        st.subheader(f"📊 Moyenne mensuelle par catégorie de dépense ({annee_dash})")
        df_sorties_annee = df_sorties[df_sorties['Année'] == annee_dash]
        if not df_sorties_annee.empty:
            nb_mois_actifs = df_sorties_annee['Mois'].nunique()
            if nb_mois_actifs > 0:
                df_moyenne = (df_sorties_annee.groupby('Catégorie')['Montant'].sum() / nb_mois_actifs).reset_index()
                df_moyenne.columns = ['Catégorie', 'Moyenne (€)']
                fig_bar = px.bar(df_moyenne, x='Catégorie', y='Moyenne (€)', color='Moyenne (€)',
                                 color_continuous_scale='Reds')
                fig_bar.update_layout(height=250, margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.write(f"Aucune dépense enregistrée en {annee_dash}.")


# ==========================================
# ONGLET 2 : TRANSACTIONS
# ==========================================
with tab2:
    st.header("Mes Transactions")
    
    # Choix de l'année
    annees_dispos = list(range(2020, datetime.datetime.now().year + 5))
    annee_choisie = st.selectbox("Sélectionnez l'année", annees_dispos, index=annees_dispos.index(datetime.datetime.now().year))
    
    # Formulaire d'ajout
    with st.expander("➕ Enregistrer une nouvelle transaction", expanded=False):
        with st.form("ajout_transaction_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                type_trans = st.radio("Type de transaction", ["Entrée", "Sortie", "Transfert"])
                mois_choisi_num = st.selectbox("Mois", list(mois_dict.keys()), format_func=lambda x: mois_dict[x], index=datetime.datetime.now().month - 1)
                jour = st.number_input("Jour du mois", min_value=1, max_value=31, value=datetime.datetime.now().day)
                
            with col2:
                if type_trans == "Transfert":
                    compte_source = st.selectbox("Compte départ", st.session_state['comptes'], key="compte_depart")
                    comptes_cibles = [c for c in st.session_state['comptes'] if c != compte_source]
                    compte_cible = st.selectbox("Compte arrivée", comptes_cibles if comptes_cibles else st.session_state['comptes'], key="compte_arrivee")
                else:
                    compte_source = st.selectbox("Compte", st.session_state['comptes'])
                    compte_cible = None
                
                categorie = st.selectbox("Catégorie", st.session_state['categories'])
                nom = st.text_input("Nom / Description")
                montant = st.number_input("Montant (€)", min_value=0.01, step=1.0)
            
            submit_btn = st.form_submit_button("💾 Enregistrer la transaction")
            
            if submit_btn:
                try:
                    date_val = datetime.date(annee_choisie, mois_choisi_num, int(jour))
                    
                    nouveau_id = 1 if st.session_state['transactions'].empty else int(st.session_state['transactions']['ID'].max()) + 1
                    
                    nouvelle_ligne = {
                        'ID': nouveau_id,
                        'Date': date_val,
                        'Jour': int(jour),
                        'Mois': mois_choisi_num,
                        'Année': annee_choisie,
                        'Type': type_trans,
                        'Compte': compte_source,
                        'Compte Cible': compte_cible,
                        'Catégorie': categorie,
                        'Nom': nom,
                        'Montant': float(montant)
                    }
                    
                    st.session_state['transactions'].loc[len(st.session_state['transactions'])] = nouvelle_ligne
                    sauvegarder_donnees()
                    st.success("Transaction enregistrée et sauvegardée !")
                    st.rerun()
                except ValueError:
                    st.error("Date invalide (ex: 31 Février).")

    st.divider()
    
    # Affichage des transactions par mois
    df_annee_affichage = st.session_state['transactions'][
        st.session_state['transactions']['Année'] == annee_choisie
    ].sort_values(by=['Mois', 'Jour', 'ID'], ascending=[False, False, False])
    
    if df_annee_affichage.empty:
        st.info(f"Aucune transaction pour l'année {annee_choisie}.")
    else:
        mois_presents = df_annee_affichage['Mois'].unique()
        for m in sorted(mois_presents, reverse=True):
            st.markdown(f"### 📅 {mois_dict[m]} {annee_choisie}")
            df_mois = df_annee_affichage[df_annee_affichage['Mois'] == m]
            
            # En-têtes du tableau
            h_col1, h_col2, h_col3, h_col4, h_col5, h_col6, h_col7 = st.columns([1.2, 1.2, 2.5, 2, 2.5, 1.5, 0.8])
            h_col1.markdown("**Date**")
            h_col2.markdown("**Type**")
            h_col3.markdown("**Compte(s)**")
            h_col4.markdown("**Catégorie**")
            h_col5.markdown("**Nom**")
            h_col6.markdown("**Montant**")
            h_col7.markdown("**Action**")
            st.markdown("<hr style='margin: 0.2rem 0; border-color: #E5E7EB;'>", unsafe_allow_html=True)
            
            # Lignes du tableau
            for idx, row in df_mois.iterrows():
                c1, c2, c3, c4, c5, c6, c7 = st.columns([1.2, 1.2, 2.5, 2, 2.5, 1.5, 0.8])
                c1.write(f"{row['Jour']:02d}/{row['Mois']:02d}/{row['Année']}")
                
                color_type = "#E53E3E" if row['Type'] == 'Sortie' else ("#2F855A" if row['Type'] == 'Entrée' else "#3182CE")
                c2.markdown(f"<span style='color:{color_type}; font-weight:bold;'>{row['Type']}</span>", unsafe_allow_html=True)
                
                if row['Type'] == 'Transfert':
                    c3.write(f"De: **{row['Compte']}** ➔ Vers: **{row['Compte Cible']}**")
                else:
                    c3.write(f"{row['Compte']}")
                    
                c4.write(row['Catégorie'])
                c5.write(row['Nom'])
                
                prefix_signe = "-" if row['Type'] == 'Sortie' else ""
                c6.write(f"**{prefix_signe}{row['Montant']:.2f} €**")
                
                if c7.button("🗑️", key=f"del_{row['ID']}", help="Supprimer cette transaction"):
                    st.session_state['transactions'] = st.session_state['transactions'][
                        st.session_state['transactions']['ID'] != row['ID']
                    ]
                    sauvegarder_donnees()
                    st.toast("Transaction supprimée !")
                    st.rerun()


# ==========================================
# ONGLET 3 : PARAMÈTRES
# ==========================================
with tab3:
    st.header("Paramètres")
    
    col_param1, col_param2 = st.columns(2)
    
    with col_param1:
        st.subheader("💳 Gestion des Comptes")
        
        st.write("**Définir les soldes de départ :**")
        soldes_modifies = False
        for cpt in st.session_state['comptes']:
            ancien_solde = float(st.session_state['soldes_initiaux'].get(cpt, 0.0))
            nouveau_solde = st.number_input(f"Solde initial - {cpt}", value=ancien_solde, step=100.0, key=f"init_{cpt}")
            if nouveau_solde != ancien_solde:
                st.session_state['soldes_initiaux'][cpt] = nouveau_solde
                soldes_modifies = True
                
        if soldes_modifies:
            sauvegarder_donnees()
            st.toast("Soldes de départ mis à jour !")

        st.divider()
        
        # Ajouter un compte
        nouveau_compte = st.text_input("Ajouter un nouveau compte")
        if st.button("➕ Créer le compte"):
            if nouveau_compte and nouveau_compte not in st.session_state['comptes']:
                st.session_state['comptes'].append(nouveau_compte)
                st.session_state['soldes_initiaux'][nouveau_compte] = 0.0
                sauvegarder_donnees()
                st.success(f"Compte '{nouveau_compte}' créé avec succès !")
                st.rerun()
                
        st.divider()

        # Supprimer un compte
        compte_a_supprimer = st.selectbox("Supprimer un compte", st.session_state['comptes'])
        if st.button("❌ Supprimer ce compte"):
            if len(st.session_state['comptes']) > 1:
                st.session_state['comptes'].remove(compte_a_supprimer)
                if compte_a_supprimer in st.session_state['soldes_initiaux']:
                    del st.session_state['soldes_initiaux'][compte_a_supprimer]
                sauvegarder_donnees()
                st.warning(f"Compte '{compte_a_supprimer}' supprimé !")
                st.rerun()
            else:
                st.error("Vous devez conserver au moins un compte.")

    with col_param2:
        st.subheader("🏷️ Gestion des Catégories & Couleurs")
        
        # === LISTE DES CATÉGORIES EXISTANTES (NOM + COULEUR + SUPPRIMER) ===
        st.write("**Liste de vos catégories :**")
        
        categories_to_remove = []
        couleurs_modifiees = False
        
        # En-têtes pour un alignement propre (optionnel mais visuellement meilleur)
        h_col_nom, h_col_coul, h_col_sup = st.columns([2.5, 1, 1])
        h_col_nom.markdown("<span style='font-size:0.85rem; color:#6B7280;'>Nom</span>", unsafe_allow_html=True)
        h_col_coul.markdown("<span style='font-size:0.85rem; color:#6B7280;'>Couleur</span>", unsafe_allow_html=True)
        h_col_sup.markdown("<span style='font-size:0.85rem; color:#6B7280;'>Action</span>", unsafe_allow_html=True)
        
        for cat in st.session_state['categories']:
            col_nom, col_coul, col_sup = st.columns([2.5, 1, 1])
            
            # 1. Nom
            with col_nom:
                st.markdown(f"<div style='margin-top: 8px; font-weight: 500;'>{cat}</div>", unsafe_allow_html=True)
            
            # 2. Couleur
            with col_coul:
                couleur_actuelle = st.session_state['category_colors'].get(cat, "#3B82F6")
                # On cache le label de l'input pour gagner de la place
                nouvelle_couleur = st.color_picker("Couleur", value=couleur_actuelle, key=f"color_{cat}", label_visibility="collapsed")
                if nouvelle_couleur != couleur_actuelle:
                    st.session_state['category_colors'][cat] = nouvelle_couleur
                    couleurs_modifiees = True
            
            # 3. Bouton supprimer
            with col_sup:
                if st.button("❌", key=f"del_cat_{cat}", help=f"Supprimer {cat}"):
                    categories_to_remove.append(cat)
                    
        # Gestion des suppressions
        if categories_to_remove:
            for cat in categories_to_remove:
                if len(st.session_state['categories']) > 1:
                    st.session_state['categories'].remove(cat)
                    if cat in st.session_state['category_colors']:
                        del st.session_state['category_colors'][cat]
                    sauvegarder_donnees()
                    st.toast(f"Catégorie '{cat}' supprimée !")
                else:
                    st.error("Vous devez conserver au moins une catégorie.")
            st.rerun()

        # Gestion de la sauvegarde des couleurs
        if couleurs_modifiees:
            sauvegarder_donnees()
            st.toast("Couleurs mises à jour !")
            st.rerun()

        st.divider()
        
        # === AJOUTER UNE NOUVELLE CATÉGORIE ===
        st.write("**Ajouter une nouvelle catégorie :**")
        col_cat_in, col_cat_col = st.columns([2.5, 2])
        
        with col_cat_in:
            nouvelle_cat = st.text_input("Nom de la catégorie", placeholder="Ex: Loisirs", label_visibility="collapsed")
        with col_cat_col:
            couleur_nouvelle_cat = st.color_picker("Couleur", value="#3B82F6", key="new_cat_color_picker", label_visibility="collapsed")
            
        if st.button("➕ Ajouter la catégorie"):
            if nouvelle_cat and nouvelle_cat not in st.session_state['categories']:
                st.session_state['categories'].append(nouvelle_cat)
                st.session_state['category_colors'][nouvelle_cat] = couleur_nouvelle_cat
                sauvegarder_donnees()
                st.success(f"Catégorie '{nouvelle_cat}' ajoutée !")
                st.rerun()
            elif nouvelle_cat in st.session_state['categories']:
                st.warning("Cette catégorie existe déjà.")
                
        st.divider()

        st.subheader("💾 Exporter vos données")
        if not st.session_state['transactions'].empty:
            csv_data = st.session_state['transactions'].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Télécharger mes transactions (CSV)",
                data=csv_data,
                file_name=f'transactions_bancaires_{datetime.date.today()}.csv',
                mime='text/csv',
            )
        else:
            st.info("Aucune donnée à exporter pour le moment.")
            
        st.divider()
        st.subheader("⚠️ Zone de danger")
        if st.button("🚨 Effacer toutes les transactions"):
            st.session_state['transactions'] = pd.DataFrame(
                columns=['ID', 'Date', 'Jour', 'Mois', 'Année', 'Type', 'Compte', 'Compte Cible', 'Catégorie', 'Nom', 'Montant']
            )
            sauvegarder_donnees()
            st.success("Toutes les données ont été réinitialisées.")
            st.rerun()