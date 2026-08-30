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

# --- KEEPALIVE CÔTÉ CLIENT ---
components.html(
    """
    <script>
    setInterval(function() {
        window.parent.postMessage('keepAlive', '*');
    }, 30000);
    </script>
    """,
    height=0,
    width=0,
)

# --- STYLE CSS PERSONNALISÉ (DESIGN COMPACT) ---
st.markdown("""
<style>
    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 1rem !important;
    }

    h1 {
        color: #E53E3E !important;
        border-bottom: 2px solid #E53E3E;
        padding-bottom: 4px;
        margin-bottom: 0.4rem !important;
        font-size: 1.6rem !important;
    }

    h2 {
        color: #FFFFFF !important;
        font-size: 1.15rem !important;
        margin-top: 0.2rem !important;
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
        padding-top: 2px !important;
        padding-bottom: 2px !important;
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
        margin: 0.4rem 0 !important;
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

# --- SYSTEME DE VERROUILLAGE (OPTIMISÉ BITWARDEN) ---
if st.session_state['password_enabled'] and not st.session_state['authenticated']:
    st.title("🔒 Accès Protégé")
    st.info("Cette application est protégée. Veuillez entrer le mot de passe pour accéder à vos comptes.")
    
    col_pwd1, col_pwd2, col_pwd3 = st.columns([1, 2, 1])
    with col_pwd2:
        with st.form("login_form"):
            username_input = st.text_input("Identifiant", value="Admin")
            pwd_input = st.text_input("Mot de passe", type="password")
            submit_login = st.form_submit_button("Déverrouiller l'accès")
            
            if submit_login:
                if pwd_input == st.session_state['app_password']:
                    st.session_state['authenticated'] = True
                    st.rerun()
                else:
                    st.error("Mot de passe incorrect.")
                    
    components.html(
        """
        <script>
        setTimeout(function() {
            const doc = window.parent.document;
            const inputs = doc.querySelectorAll('input');
            inputs.forEach(input => {
                if (input.type === 'password') {
                    input.setAttribute('autocomplete', 'current-password');
                    input.setAttribute('name', 'password');
                } else if (input.type === 'text') {
                    input.setAttribute('autocomplete', 'username');
                    input.setAttribute('name', 'username');
                }
            });
        }, 300);
        </script>
        """,
        height=0,
        width=0,
    )
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

            st.markdown("**Dépenses du mois**")
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
                fig_pie_mois.update_layout(
                    height=280, 
                    margin=dict(l=0, r=0, t=10, b=10), 
                    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.0)
                )
                st.plotly_chart(fig_pie_mois, use_container_width=True)
            else:
                st.info(f"Aucune dépense en {mois_dict[mois_dash]} {annee_dash}.")

            st.markdown("**Entrées du mois**")
            df_mois_entrees = df[(df['Type'] == 'Entrée') & (df['Année'] == annee_dash) & (df['Mois'] == mois_dash)]
            if not df_mois_entrees.empty:
                fig_pie_mois_ent = px.pie(
                    df_mois_entrees, 
                    values='Montant', 
                    names='Catégorie', 
                    color='Catégorie',
                    color_discrete_map=st.session_state['category_colors'],
                    hole=0.4
                )
                fig_pie_mois_ent.update_traces(textinfo='percent+value')
                fig_pie_mois_ent.update_layout(
                    height=280, 
                    margin=dict(l=0, r=0, t=10, b=10), 
                    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.0)
                )
                st.plotly_chart(fig_pie_mois_ent, use_container_width=True)
            else:
                st.info(f"Aucune entrée en {mois_dict[mois_dash]} {annee_dash}.")

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

            st.markdown("**Dépenses de l'année**")
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
                fig_pie_an.update_layout(
                    height=280, 
                    margin=dict(l=0, r=0, t=10, b=10), 
                    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.0)
                )
                st.plotly_chart(fig_pie_an, use_container_width=True)
            else:
                st.info(f"Aucune dépense en {annee_dash}.")

            st.markdown("**Entrées de l'année**")
            df_an_entrees = df[(df['Type'] == 'Entrée') & (df['Année'] == annee_dash)]
            if not df_an_entrees.empty:
                fig_pie_an_ent = px.pie(
                    df_an_entrees, 
                    values='Montant', 
                    names='Catégorie', 
                    color='Catégorie',
                    color_discrete_map=st.session_state['category_colors'],
                    hole=0.4
                )
                fig_pie_an_ent.update_traces(textinfo='percent+value')
                fig_pie_an_ent.update_layout(
                    height=280, 
                    margin=dict(l=0, r=0, t=10, b=10), 
                    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.0)
                )
                st.plotly_chart(fig_pie_an_ent, use_container_width=True)
            else:
                st.info(f"Aucune entrée en {annee_dash}.")

        st.divider()

        # ÉVOLUTION DES SOLDES
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

        # Moyennes Mensuelles & Totaux
        col_moyenne_dep, col_moyenne_ent = st.columns(2)
        
        with col_moyenne_dep:
            st.subheader(f"🔻 Moyenne des dépenses ({annee_dash})")
            df_sorties_annee = df_sorties[df_sorties['Année'] == annee_dash]
            
            if not df_sorties_annee.empty:
                nb_mois_actifs = df_sorties_annee['Mois'].nunique()
                
                df_total_dep = df_sorties_annee.groupby('Catégorie')['Montant'].sum().reset_index()
                df_total_dep.columns = ['Catégorie', 'Total Annuel (€)']
                
                df_moyenne_dep = df_total_dep.copy()
                df_moyenne_dep['Moyenne (€/mois)'] = df_moyenne_dep['Total Annuel (€)'] / nb_mois_actifs
                
                st.markdown("**Moyenne mensuelle**")
                fig_bar_dep = px.bar(df_moyenne_dep, y='Catégorie', x='Moyenne (€/mois)', color='Moyenne (€/mois)',
                                     orientation='h', color_continuous_scale='Reds', text_auto='.2f')
                fig_bar_dep.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10), yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_bar_dep, use_container_width=True)

            else:
                st.write(f"Aucune dépense enregistrée en {annee_dash}.")

        with col_moyenne_ent:
            st.subheader(f"🍏 Moyenne des entrées ({annee_dash})")
            df_entrees_annee = df[(df['Type'] == 'Entrée') & (df['Année'] == annee_dash)]
            
            if not df_entrees_annee.empty:
                nb_mois_actifs_in = df_entrees_annee['Mois'].nunique()
                
                df_total_ent = df_entrees_annee.groupby('Catégorie')['Montant'].sum().reset_index()
                df_total_ent.columns = ['Catégorie', 'Total Annuel (€)']
                
                df_moyenne_ent = df_total_ent.copy()
                df_moyenne_ent['Moyenne (€/mois)'] = df_moyenne_ent['Total Annuel (€)'] / nb_mois_actifs_in
                
                st.markdown("**Moyenne mensuelle**")
                fig_bar_ent = px.bar(df_moyenne_ent, y='Catégorie', x='Moyenne (€/mois)', color='Moyenne (€/mois)',
                                     orientation='h', color_continuous_scale='Greens', text_auto='.2f')
                fig_bar_ent.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10), yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_bar_ent, use_container_width=True)
                
            else:
                st.write(f"Aucune entrée d'argent enregistrée en {annee_dash}.")

# ==========================================
# ONGLET 2 : TRANSACTIONS (SÉPARATION PAR MOIS RETROUVÉE)
# ==========================================
with tab2:
    st.markdown("<h2 style='margin-top: -15px; margin-bottom: 8px;'>📝 Mes Transactions</h2>", unsafe_allow_html=True)
    
    soldes_actuels_t2 = calculer_soldes_actuels()
    total_general_t2 = sum(soldes_actuels_t2.values())
    
    cols_t2 = st.columns(len(soldes_actuels_t2) + 1 if len(soldes_actuels_t2) > 0 else 1)
    
    color_tot_t2 = "#22C55E" if total_general_t2 >= 0 else "#EF4444"
    cols_t2[0].markdown(f"""
    <div style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-left: 4px solid {color_tot_t2}; border-radius: 6px; padding: 4px 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <div style="color: #000000; font-weight: 600; font-size: 0.75rem;">🌐 TOTAL GÉNÉRAL</div>
        <div style="color: {color_tot_t2}; font-size: 1.1rem; font-weight: bold;">{total_general_t2:.2f} €</div>
    </div>
    """, unsafe_allow_html=True)
    
    for i, (compte, solde) in enumerate(soldes_actuels_t2.items(), start=1):
        color_cpt = "#22C55E" if solde >= 0 else "#EF4444"
        cols_t2[i].markdown(f"""
        <div style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-left: 4px solid {color_cpt}; border-radius: 6px; padding: 4px 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
            <div style="color: #000000; font-weight: 600; font-size: 0.75rem;">{compte}</div>
            <div style="color: {color_cpt}; font-size: 1.1rem; font-weight: bold;">{solde:.2f} €</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<div style='margin-bottom: 8px;'></div>", unsafe_allow_html=True)

    annees_dispos = list(range(2020, datetime.datetime.now().year + 5))
    
    with st.expander("➕ Enregistrer une Entrée ou Sortie d'argent", expanded=False):
        with st.form("ajout_transaction_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                type_trans = st.radio("Type de transaction", ["Entrée", "Sortie"], index=1)
                annee_saisie = st.selectbox("Année de la transaction", annees_dispos, index=annees_dispos.index(datetime.datetime.now().year))
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
                    date_val = datetime.date(annee_saisie, mois_choisi_num, int(jour))
                    nouveau_id = 1 if st.session_state['transactions'].empty else int(st.session_state['transactions']['ID'].max()) + 1
                    
                    nouvelle_ligne = {
                        'ID': nouveau_id,
                        'Date': date_val,
                        'Jour': int(jour),
                        'Mois': mois_choisi_num,
                        'Année': annee_saisie,
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

    with st.expander("🔄 Enregistrer un Transfert entre comptes", expanded=False):
        with st.form("ajout_transfert_form", clear_on_submit=True):
            st.markdown("**(Mouvement d'argent entre deux de vos comptes internes)**")
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Type :** Transfert")
                annee_saisie_t = st.selectbox("Année de la transaction", annees_dispos, index=annees_dispos.index(datetime.datetime.now().year), key="annee_t")
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
                        date_val_t = datetime.date(annee_saisie_t, mois_choisi_num_t, int(jour_t))
                        nouveau_id_t = 1 if st.session_state['transactions'].empty else int(st.session_state['transactions']['ID'].max()) + 1
                        
                        nouvelle_ligne_t = {
                            'ID': nouveau_id_t,
                            'Date': date_val_t,
                            'Jour': int(jour_t),
                            'Mois': mois_choisi_num_t,
                            'Année': annee_saisie_t,
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

    st.markdown("### 🔍 Recherche & Filtres")
    f_col1, f_col2, f_col3, f_col4, f_col5, f_col6 = st.columns([1.2, 1.8, 1.5, 1.5, 1.2, 2.0])
    
    with f_col1:
        annee_filtre = st.selectbox("Année", ["Toutes"] + annees_dispos, index=annees_dispos.index(datetime.datetime.now().year) + 1, key="f_annee")
        
    with f_col2:
        search_query = st.text_input("Recherche (Nom)", "", placeholder="Ex: Course, Netflix...", key="f_query")
        
    with f_col3:
        cat_filtre = st.selectbox("Catégorie", ["Toutes"] + st.session_state['categories'] + ["Virement interne"], key="f_cat")
        
    with f_col4:
        compte_filtre = st.selectbox("Compte", ["Tous"] + st.session_state['comptes'], key="f_compte")
        
    with f_col5:
        type_filtre = st.selectbox("Type", ["Tous", "Entrée", "Sortie", "Transfert"], key="f_type")
        
    with f_col6:
        tri_filtre = st.selectbox(
            "Tri d'affichage",
            ["Date (Décroissant)", "Date (Croissant)", "Montant (Croissant)", "Montant (Décroissant)", "Par Catégorie"],
            key="f_tri"
        )

    df_filtered = st.session_state['transactions'].copy()

    if annee_filtre != "Toutes":
        df_filtered = df_filtered[df_filtered['Année'] == int(annee_filtre)]

    if search_query.strip():
        df_filtered = df_filtered[df_filtered['Nom'].str.contains(search_query.strip(), case=False, na=False)]

    if cat_filtre != "Toutes":
        df_filtered = df_filtered[df_filtered['Catégorie'] == cat_filtre]

    if compte_filtre != "Tous":
        df_filtered = df_filtered[(df_filtered['Compte'] == compte_filtre) | (df_filtered['Compte Cible'] == compte_filtre)]

    if type_filtre != "Tous":
        df_filtered = df_filtered[df_filtered['Type'] == type_filtre]

    if tri_filtre == "Date (Décroissant)":
        df_filtered = df_filtered.sort_values(by=['Année', 'Mois', 'Jour', 'ID'], ascending=[False, False, False, False])
    elif tri_filtre == "Date (Croissant)":
        df_filtered = df_filtered.sort_values(by=['Année', 'Mois', 'Jour', 'ID'], ascending=[True, True, True, True])
    elif tri_filtre == "Montant (Croissant)":
        df_filtered = df_filtered.sort_values(by=['Montant', 'ID'], ascending=[True, True])
    elif tri_filtre == "Montant (Décroissant)":
        df_filtered = df_filtered.sort_values(by=['Montant', 'ID'], ascending=[False, False])
    elif tri_filtre == "Par Catégorie":
        df_filtered = df_filtered.sort_values(by=['Catégorie', 'Montant'], ascending=[True, False])

    tot_entrees = df_filtered[df_filtered['Type'] == 'Entrée']['Montant'].sum()
    tot_sorties = df_filtered[df_filtered['Type'] == 'Sortie']['Montant'].sum()
    diff_net = tot_entrees - tot_sorties
    color_net = "#22C55E" if diff_net >= 0 else "#EF4444"

    st.markdown(f"""
    <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 8px 14px; margin-top: 6px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;">
        <div>
            <span style="font-weight: bold; color: #1E293B;">📊 Résumé de la sélection :</span> &nbsp;
            <span style="color: #22C55E; font-weight: 600;">➕ Entrées : {tot_entrees:.2f} €</span> &nbsp;|&nbsp;
            <span style="color: #EF4444; font-weight: 600;">➖ Dépenses : {tot_sorties:.2f} €</span> &nbsp;|&nbsp;
            <span style="color: {color_net}; font-weight: bold;">⚖️ Net : {diff_net:+.2f} €</span>
        </div>
        <div style="color: #64748B; font-size: 0.85rem; font-weight: 500;">
            <b>{len(df_filtered)}</b> transaction(s) trouvée(s)
        </div>
    </div>
    """, unsafe_allow_html=True)

    if df_filtered.empty:
        st.info("Aucune transaction ne correspond aux critères de recherche actuels.")
    else:
        # Groupe les transactions par mois et année pour afficher les séparations
        current_month_key = None
        
        for idx, row in df_filtered.iterrows():
            month_key = (row['Année'], row['Mois'])
            
            # Affichage de l'en-tête de mois à chaque changement de mois/année
            if month_key != current_month_key:
                current_month_key = month_key
                st.markdown(f"<h3 style='margin-top: 20px; margin-bottom: 6px; color: #E53E3E; border-bottom: 1px solid #E53E3E; padding-bottom: 2px;'>📅 {mois_dict[row['Mois']]} {row['Année']}</h3>", unsafe_allow_html=True)
                
                h_col1, h_col2, h_col3, h_col4, h_col5, h_col6, h_col7 = st.columns([1.2, 1.2, 2.5, 2, 2.5, 1.5, 1.0])
                h_col1.markdown("**Date**")
                h_col2.markdown("**Type**")
                h_col3.markdown("**Compte(s)**")
                h_col4.markdown("**Catégorie**")
                h_col5.markdown("**Nom**")
                h_col6.markdown("**Montant**")
                h_col7.markdown("**Action**")
                st.markdown("<hr style='margin: 0.2rem 0; border-color: #E5E7EB;'>", unsafe_allow_html=True)

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