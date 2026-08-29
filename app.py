import streamlit as st
import pandas as pd
import plotly.express as px
import datetime
import calendar
import json
import os
import streamlit.components.v1 as components

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Gestion Bancaire", layout="wide", page_icon="💰")

# --- KEEPALIVE CÔTÉ CLIENT (Empêche les déconnexions intempestives) ---
# Ce script tourne dans le navigateur et maintient la connexion WebSocket active
components.html(
    """
    <script>
    setInterval(function() {
        window.parent.postMessage('keepAlive', '*');
    }, 30000); // Ping toutes les 30 secondes
    </script>
    """,
    height=0,
    width=0,
)

# --- STYLE CSS PERSONNALISÉ (DESIGN COMPACT) ---
st.markdown("""
<style>
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 1.2rem !important;
    }

    h1 {
        color: #E53E3E !important;
        border-bottom: 2px solid #E53E3E;
        padding-bottom: 4px;
        margin-bottom: 0.6rem !important;
        font-size: 1.7rem !important;
    }

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

    button[data-baseweb="tab"] {
        font-weight: bold;
        padding-top: 4px !important;
        padding-bottom: 4px !important;
    }
    button[aria-selected="true"] {
        color: #E53E3E !important;
        border-bottom-color: #E53E3E !important;
    }

    .stButton > button {
        border-radius: 6px;
        transition: all 0.2s ease-in-out;
    }

    div[data-testid="stExpander"], div[data-testid="stForm"] {
        border: 1px solid #E5E7EB !important;
        border-radius: 8px;
    }

    hr {
        margin: 0.5rem 0 !important;
        border-color: #E5E7EB !important;
    }
</style>
""", unsafe_allow_html=True)

# --- NOM DU FICHIER DE SAUVEGARDE LOCALE ---
DATA_FILE = "data/banque_data.json"
os.makedirs("data", exist_ok=True)

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
    "Course": "#14B8A6",
    "Virement interne": "#6B7280"
}

# --- FONCTIONS DE PERSISTANCE DES DONNÉES ---
def charger_donnees():
    """Charge les données depuis le fichier JSON s'il existe."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            comptes = data.get("comptes", ['Compte Courant', 'Livret A', 'Livret B'])
            soldes_initiaux = data.get("soldes_initiaux", {'Compte Courant': 0.0, 'Livret A': 0.0, 'Livret B': 0.0})
            categories = data.get("categories", DEFAULT_CATEGORIES.copy())
            password_enabled = data.get("password_enabled", False)
            app_password = data.get("app_password", "")
            
            category_colors = data.get("category_colors", {})
            for cat in categories + ["Virement interne"]:
                if cat not in category_colors:
                    category_colors[cat] = DEFAULT_CATEGORY_COLORS.get(cat, "#3B82F6")

            trans_list = data.get("transactions", [])
            if trans_list:
                df = pd.DataFrame(trans_list)
                df['Date'] = pd.to_datetime(df['Date']).dt.date
            else:
                df = pd.DataFrame(columns=['ID', 'Date', 'Jour', 'Mois', 'Année', 'Type', 'Compte', 'Compte Cible', 'Catégorie', 'Nom', 'Montant'])
            
            return comptes, soldes_initiaux, categories, category_colors, df, password_enabled, app_password
        except Exception as e:
            st.error(f"Erreur lors de la lecture des données sauvegardées : {e}")
            
    return (
        ['Compte Courant', 'Livret A', 'Livret B'],
        {'Compte Courant': 0.0, 'Livret A': 0.0, 'Livret B': 0.0},
        DEFAULT_CATEGORIES.copy(),
        DEFAULT_CATEGORY_COLORS.copy(),
        pd.DataFrame(columns=['ID', 'Date', 'Jour', 'Mois', 'Année', 'Type', 'Compte', 'Compte Cible', 'Catégorie', 'Nom', 'Montant']),
        False,
        ""
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
        "transactions": trans_list,
        "password_enabled": st.session_state['password_enabled'],
        "app_password": st.session_state['app_password']
    }
    
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- INITIALISATION DE LA SESSION ---
if 'initialized' not in st.session_state:
    comptes, soldes_initiaux, categories, category_colors, df, pwd_enabled, pwd = charger_donnees()
    st.session_state['comptes'] = comptes
    st.session_state['soldes_initiaux'] = soldes_initiaux
    st.session_state['categories'] = categories
    st.session_state['category_colors'] = category_colors
    st.session_state['transactions'] = df
    st.session_state['password_enabled'] = pwd_enabled
    st.session_state['app_password'] = pwd
    st.session_state['authenticated'] = False
    st.session_state['initialized'] = True

if 'edit_trans_id' not in st.session_state:
    st.session_state['edit_trans_id'] = None

# --- SYSTEME DE VERROUILLAGE (MOT DE PASSE) ---
if st.session_state['password_enabled'] and not st.session_state['authenticated']:
    st.title("🔒 Accès Protégé")
    st.info("Cette application est protégée. Veuillez entrer le mot de passe pour accéder à vos comptes.")
    
    col_pwd1, col_pwd2, col_pwd3 = st.columns([1, 2, 1])
    with col_pwd2:
        with st.form("login_form"):
            pwd_input = st.text_input("Mot de passe", type="password")
            submit_login = st.form_submit_button("Déverrouiller l'accès")
            
            if submit_login:
                if pwd_input == st.session_state['app_password']:
                    st.session_state['authenticated'] = True
                    st.rerun()
                else:
                    st.error("Mot de passe incorrect.")
    st.stop()

# ==========================================
# APP PRINCIPALE
# ==========================================
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

    # 2. Solde actuel des comptes + TOTAL GLOBAL
    soldes_actuels = calculer_soldes_actuels()
    total_general = sum(soldes_actuels.values())
    
    cols = st.columns(len(soldes_actuels) + 1 if len(soldes_actuels) > 0 else 1)
    
    color_tot = "#22C55E" if total_general >= 0 else "#EF4444"
    cols[0].markdown(f"""
    <div style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-left: 5px solid {color_tot}; border-radius: 6px; padding: 6px 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <div style="color: #000000; font-weight: 600; font-size: 0.82rem;">🌐 TOTAL GÉNÉRAL</div>
        <div style="color: {color_tot}; font-size: 1.25rem; font-weight: bold;">{total_general:.2f} €</div>
    </div>
    """, unsafe_allow_html=True)
    
    for i, (compte, solde) in enumerate(soldes_actuels.items(), start=1):
        color_cpt = "#22C55E" if solde >= 0 else "#EF4444"
        cols[i].markdown(f"""
        <div style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-left: 5px solid {color_cpt}; border-radius: 6px; padding: 6px 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
            <div style="color: #000000; font-weight: 600; font-size: 0.82rem;">{compte}</div>
            <div style="color: {color_cpt}; font-size: 1.25rem; font-weight: bold;">{solde:.2f} €</div>
        </div>
        """, unsafe_allow_html=True)

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
                fig_pie_mois.update_traces(textinfo='percent+value')
                # LÉGENDE SUR LE CÔTÉ (Verticale) ET HAUTEUR AUGMENTÉE
                fig_pie_mois.update_layout(
                    height=300, 
                    margin=dict(l=0, r=0, t=10, b=10), 
                    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.0)
                )
                st.plotly_chart(fig_pie_mois, use_container_width=True)
            else:
                st.info(f"Aucune dépense en {mois_dict[mois_dash]} {annee_dash}.")

        # --- BLOC ANNÉE ---
        with col_annee:
            st.subheader(f"🗓️ Analyse Annuelle ({annee_dash})")
            
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
                fig_pie_an.update_traces(textinfo='percent+value')
                # LÉGENDE SUR LE CÔTÉ (Verticale) ET HAUTEUR AUGMENTÉE
                fig_pie_an.update_layout(
                    height=300, 
                    margin=dict(l=0, r=0, t=10, b=10), 
                    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.0)
                )
                st.plotly_chart(fig_pie_an, use_container_width=True)
            else:
                st.info(f"Aucune dépense en {annee_dash}.")

        st.divider()

        # 4. ÉVOLUTION DES SOLDES
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
            
            account_colors = {}
            for cpt in st.session_state['comptes']:
                cpt_lower = cpt.lower()
                if 'livret a' in cpt_lower:
                    account_colors[cpt] = "#3B82F6"
                elif 'courant' in cpt_lower or 'compte' in cpt_lower:
                    account_colors[cpt] = "#EF4444"
                elif 'livret' in cpt_lower:
                    account_colors[cpt] = "#F59E0B"
                else:
                    account_colors[cpt] = "#10B981"
            
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

        # 5. Moyennes Mensuelles & Totaux
        col_moyenne_dep, col_moyenne_ent = st.columns(2)
        
        with col_moyenne_dep:
            st.subheader(f"🔻 Moyenne et Total des dépenses ({annee_dash})")
            df_sorties_annee = df_sorties[df_sorties['Année'] == annee_dash]
            
            if not df_sorties_annee.empty:
                nb_mois_actifs = df_sorties_annee['Mois'].nunique()
                
                df_total_dep = df_sorties_annee.groupby('Catégorie')['Montant'].sum().reset_index()
                df_total_dep.columns = ['Catégorie', 'Total Annuel (€)']
                
                df_moyenne_dep = df_total_dep.copy()
                df_moyenne_dep['Moyenne (€/mois)'] = df_moyenne_dep['Total Annuel (€)'] / nb_mois_actifs
                
                fig_bar_dep = px.bar(df_moyenne_dep, y='Catégorie', x='Moyenne (€/mois)', color='Moyenne (€/mois)',
                                     orientation='h', color_continuous_scale='Reds', text_auto='.2f')
                fig_bar_dep.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10), yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_bar_dep, use_container_width=True)
                
                fig_bar_tot_dep = px.bar(df_total_dep, y='Catégorie', x='Total Annuel (€)', color='Catégorie', 
                                         orientation='h', color_discrete_map=st.session_state['category_colors'], text_auto='.2f')
                fig_bar_tot_dep.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10), yaxis={'categoryorder':'total ascending'}, showlegend=False)
                st.plotly_chart(fig_bar_tot_dep, use_container_width=True)

            else:
                st.write(f"Aucune dépense enregistrée en {annee_dash}.")

        with col_moyenne_ent:
            st.subheader(f"🍏 Moyenne et Total des entrées ({annee_dash})")
            df_entrees_annee = df[(df['Type'] == 'Entrée') & (df['Année'] == annee_dash)]
            
            if not df_entrees_annee.empty:
                nb_mois_actifs_in = df_entrees_annee['Mois'].nunique()
                
                df_total_ent = df_entrees_annee.groupby('Catégorie')['Montant'].sum().reset_index()
                df_total_ent.columns = ['Catégorie', 'Total Annuel (€)']
                
                df_moyenne_ent = df_total_ent.copy()
                df_moyenne_ent['Moyenne (€/mois)'] = df_moyenne_ent['Total Annuel (€)'] / nb_mois_actifs_in
                
                fig_bar_ent = px.bar(df_moyenne_ent, y='Catégorie', x='Moyenne (€/mois)', color='Moyenne (€/mois)',
                                     orientation='h', color_continuous_scale='Greens', text_auto='.2f')
                fig_bar_ent.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10), yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_bar_ent, use_container_width=True)
                
                fig_bar_tot_ent = px.bar(df_total_ent, y='Catégorie', x='Total Annuel (€)', color='Catégorie',
                                         orientation='h', color_discrete_map=st.session_state['category_colors'], text_auto='.2f')
                fig_bar_tot_ent.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10), yaxis={'categoryorder':'total ascending'}, showlegend=False)
                st.plotly_chart(fig_bar_tot_ent, use_container_width=True)
            else:
                st.write(f"Aucune entrée d'argent enregistrée en {annee_dash}.")

# ==========================================
# ONGLET 2 : TRANSACTIONS
# ==========================================
with tab2:
    st.header("Mes Transactions")
    
    annees_dispos = list(range(2020, datetime.datetime.now().year + 5))
    annee_choisie = st.selectbox("Sélectionnez l'année", annees_dispos, index=annees_dispos.index(datetime.datetime.now().year))
    
    # --- FORMULAIRE 1 : ENTRÉE / SORTIE ---
    with st.expander("➕ Enregistrer une Entrée ou Sortie d'argent", expanded=False):
        with st.form("ajout_transaction_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                type_trans = st.radio("Type de transaction", ["Entrée", "Sortie"], index=1)
                mois_choisi_num = st.selectbox("Mois", list(mois_dict.keys()), format_func=lambda x: mois_dict[x], index=datetime.datetime.now().month - 1)
                jour = st.number_input("Jour du mois", min_value=1, max_value=31, value=datetime.datetime.now().day)
                
            with col2:
                compte = st.selectbox("Compte", st.session_state['comptes'])
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
                        'Compte': compte,
                        'Compte Cible': None,
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

    # --- FORMULAIRE 2 : TRANSFERT ---
    with st.expander("🔄 Enregistrer un Transfert entre comptes", expanded=False):
        with st.form("ajout_transfert_form", clear_on_submit=True):
            st.markdown("**(Mouvement d'argent entre deux de vos comptes internes)**")
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Type :** Transfert")
                mois_choisi_num_t = st.selectbox("Mois ", list(mois_dict.keys()), format_func=lambda x: mois_dict[x], index=datetime.datetime.now().month - 1, key="mois_t")
                jour_t = st.number_input("Jour du mois ", min_value=1, max_value=31, value=datetime.datetime.now().day, key="jour_t")
                
            with col2:
                compte_source = st.selectbox("Compte de DÉPART", st.session_state['comptes'], key="compte_depart")
                compte_cible = st.selectbox("Compte d'ARRIVÉE", st.session_state['comptes'], key="compte_arrivee")
                
                nom_t = st.text_input("Nom / Description ", value="Virement interne", key="nom_t")
                montant_t = st.number_input("Montant à transférer (€)", min_value=0.01, step=1.0, key="mont_t")
            
            submit_btn_t = st.form_submit_button("🔄 Effectuer le transfert")
            
            if submit_btn_t:
                if compte_source == compte_cible:
                    st.error("Le compte de départ et d'arrivée ne peuvent pas être les mêmes.")
                else:
                    try:
                        date_val_t = datetime.date(annee_choisie, mois_choisi_num_t, int(jour_t))
                        nouveau_id_t = 1 if st.session_state['transactions'].empty else int(st.session_state['transactions']['ID'].max()) + 1
                        
                        nouvelle_ligne_t = {
                            'ID': nouveau_id_t,
                            'Date': date_val_t,
                            'Jour': int(jour_t),
                            'Mois': mois_choisi_num_t,
                            'Année': annee_choisie,
                            'Type': "Transfert",
                            'Compte': compte_source,
                            'Compte Cible': compte_cible,
                            'Catégorie': "Virement interne",
                            'Nom': nom_t,
                            'Montant': float(montant_t)
                        }
                        
                        st.session_state['transactions'].loc[len(st.session_state['transactions'])] = nouvelle_ligne_t
                        sauvegarder_donnees()
                        st.success("Transfert enregistré et sauvegardé !")
                        st.rerun()
                    except ValueError:
                        st.error("Date invalide.")

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
            st.markdown(f"""
            <div style="background: linear-gradient(90deg, #E53E3E 0%, #F87171 100%); padding: 12px 20px; border-radius: 8px; margin-top: 30px; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                <h3 style="margin: 0; color: white !important; font-size: 1.4rem; text-align: left; font-weight: bold;">📅 {mois_dict[m]} {annee_choisie}</h3>
            </div>
            """, unsafe_allow_html=True)

            df_mois = df_annee_affichage[df_annee_affichage['Mois'] == m]
            
            h_col1, h_col2, h_col3, h_col4, h_col5, h_col6, h_col7 = st.columns([1.2, 1.2, 2.5, 2, 2.5, 1.5, 1.0])
            h_col1.markdown("**Date**")
            h_col2.markdown("**Type**")
            h_col3.markdown("**Compte(s)**")
            h_col4.markdown("**Catégorie**")
            h_col5.markdown("**Nom**")
            h_col6.markdown("**Montant**")
            h_col7.markdown("**Action**")
            st.markdown("<hr style='margin: 0.2rem 0; border-color: #E5E7EB;'>", unsafe_allow_html=True)
            
            for idx, row in df_mois.iterrows():
                if st.session_state.get('edit_trans_id') == row['ID']:
                    with st.form(key=f"edit_form_{row['ID']}"):
                        st.markdown("**Modifier la transaction**")
                        ec1, ec2, ec3 = st.columns(3)
                        new_date = ec1.date_input("Date", value=row['Date'])
                        new_type = ec2.selectbox("Type", ["Entrée", "Sortie", "Transfert"], index=["Entrée", "Sortie", "Transfert"].index(row['Type']))
                        new_montant = ec3.number_input("Montant (€)", value=float(row['Montant']), min_value=0.01)

                        ec4, ec5, ec6 = st.columns(3)
                        new_compte = ec4.selectbox("Compte", st.session_state['comptes'], index=st.session_state['comptes'].index(row['Compte']) if row['Compte'] in st.session_state['comptes'] else 0)
                        
                        if new_type == "Transfert":
                            default_cible = st.session_state['comptes'].index(row['Compte Cible']) if row['Compte Cible'] in st.session_state['comptes'] else 0
                            new_compte_cible = ec5.selectbox("Compte d'arrivée", st.session_state['comptes'], index=default_cible)
                            new_cat = "Virement interne"
                        else:
                            new_compte_cible = None
                            new_cat = ec5.selectbox("Catégorie", st.session_state['categories'], index=st.session_state['categories'].index(row['Catégorie']) if row['Catégorie'] in st.session_state['categories'] else 0)
                        
                        new_nom = ec6.text_input("Nom", value=row['Nom'])

                        col_b1, col_b2 = st.columns(2)
                        if col_b1.form_submit_button("✅ Enregistrer"):
                            idx_to_update = st.session_state['transactions'].index[st.session_state['transactions']['ID'] == row['ID']].tolist()[0]
                            st.session_state['transactions'].at[idx_to_update, 'Date'] = new_date
                            st.session_state['transactions'].at[idx_to_update, 'Jour'] = new_date.day
                            st.session_state['transactions'].at[idx_to_update, 'Mois'] = new_date.month
                            st.session_state['transactions'].at[idx_to_update, 'Année'] = new_date.year
                            st.session_state['transactions'].at[idx_to_update, 'Type'] = new_type
                            st.session_state['transactions'].at[idx_to_update, 'Compte'] = new_compte
                            st.session_state['transactions'].at[idx_to_update, 'Compte Cible'] = new_compte_cible
                            st.session_state['transactions'].at[idx_to_update, 'Catégorie'] = new_cat
                            st.session_state['transactions'].at[idx_to_update, 'Nom'] = new_nom
                            st.session_state['transactions'].at[idx_to_update, 'Montant'] = new_montant
                            st.session_state['edit_trans_id'] = None
                            sauvegarder_donnees()
                            st.rerun()
                        if col_b2.form_submit_button("❌ Annuler"):
                            st.session_state['edit_trans_id'] = None
                            st.rerun()
                else:
                    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1.2, 1.2, 2.5, 2, 2.5, 1.5, 0.5, 0.5])
                    c1.write(f"{row['Jour']:02d}/{row['Mois']:02d}/{row['Année']}")
                    
                    color_type = "#EF4444" if row['Type'] == 'Sortie' else ("#22C55E" if row['Type'] == 'Entrée' else "#3B82F6")
                    c2.markdown(f"<span style='color:{color_type}; font-weight:bold;'>{row['Type']}</span>", unsafe_allow_html=True)
                    
                    if row['Type'] == 'Transfert':
                        c3.write(f"De: **{row['Compte']}** ➔ Vers: **{row['Compte Cible']}**")
                    else:
                        c3.write(f"{row['Compte']}")
                        
                    cat_color = st.session_state['category_colors'].get(row['Catégorie'], "#FFFFFF")
                    c4.markdown(f"<span style='color:{cat_color}; font-weight:bold;'>{row['Catégorie']}</span>", unsafe_allow_html=True)
                    
                    c5.write(row['Nom'])
                    
                    prefix_signe = "-" if row['Type'] == 'Sortie' else ("+" if row['Type'] == 'Entrée' else "")
                    c6.markdown(f"<span style='color:{color_type}; font-weight:bold;'>{prefix_signe}{row['Montant']:.2f} €</span>", unsafe_allow_html=True)
                    
                    if c7.button("✏️", key=f"edit_{row['ID']}", help="Modifier cette transaction"):
                        st.session_state['edit_trans_id'] = row['ID']
                        st.rerun()
                    
                    if c8.button("🗑️", key=f"del_{row['ID']}", help="Supprimer cette transaction"):
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
    
    st.subheader("🔒 Sécurité & Mot de passe")
    pwd_enabled = st.checkbox("Activer la protection par mot de passe au lancement", value=st.session_state.get('password_enabled', False))
    
    if pwd_enabled:
        col_pwd_1, col_pwd_2 = st.columns(2)
        with col_pwd_1:
            new_pwd = st.text_input("Définir ou modifier le mot de passe", type="password", value=st.session_state.get('app_password', ''))
            if st.button("💾 Sauvegarder le mot de passe"):
                if new_pwd.strip() == "":
                    st.error("Le mot de passe ne peut pas être vide.")
                else:
                    st.session_state['password_enabled'] = True
                    st.session_state['app_password'] = new_pwd
                    sauvegarder_donnees()
                    st.success("Paramètres de sécurité mis à jour ! Le mot de passe sera demandé au prochain lancement.")
    else:
        if st.session_state.get('password_enabled', False):
            if st.button("🔓 Désactiver la protection (Sauvegarder)"):
                st.session_state['password_enabled'] = False
                st.session_state['app_password'] = ""
                sauvegarder_donnees()
                st.success("Protection désactivée ! L'application est en accès libre.")
                st.rerun()
                
    st.divider()

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
        
        nouveau_compte = st.text_input("Ajouter un nouveau compte")
        if st.button("➕ Créer le compte"):
            if nouveau_compte and nouveau_compte not in st.session_state['comptes']:
                st.session_state['comptes'].append(nouveau_compte)
                st.session_state['soldes_initiaux'][nouveau_compte] = 0.0
                sauvegarder_donnees()
                st.success(f"Compte '{nouveau_compte}' créé avec succès !")
                st.rerun()
                
        st.divider()

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
        st.write("**Liste de vos catégories :**")
        
        categories_to_remove = []
        couleurs_modifiees = False
        
        h_col_nom, h_col_coul, h_col_sup = st.columns([2.5, 1, 1])
        h_col_nom.markdown("<span style='font-size:0.85rem; color:#6B7280;'>Nom</span>", unsafe_allow_html=True)
        h_col_coul.markdown("<span style='font-size:0.85rem; color:#6B7280;'>Couleur</span>", unsafe_allow_html=True)
        h_col_sup.markdown("<span style='font-size:0.85rem; color:#6B7280;'>Action</span>", unsafe_allow_html=True)
        
        for cat in st.session_state['categories']:
            col_nom, col_coul, col_sup = st.columns([2.5, 1, 1])
            
            with col_nom:
                st.markdown(f"<div style='margin-top: 8px; font-weight: 500;'>{cat}</div>", unsafe_allow_html=True)
            
            with col_coul:
                couleur_actuelle = st.session_state['category_colors'].get(cat, "#3B82F6")
                nouvelle_couleur = st.color_picker("Couleur", value=couleur_actuelle, key=f"color_{cat}", label_visibility="collapsed")
                if nouvelle_couleur != couleur_actuelle:
                    st.session_state['category_colors'][cat] = nouvelle_couleur
                    couleurs_modifiees = True
            
            with col_sup:
                if st.button("❌", key=f"del_cat_{cat}", help=f"Supprimer {cat}"):
                    categories_to_remove.append(cat)
                    
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

        if couleurs_modifiees:
            sauvegarder_donnees()
            st.toast("Couleurs mises à jour !")
            st.rerun()

        st.divider()
        
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