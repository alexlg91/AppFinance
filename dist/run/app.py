import streamlit as st
import pandas as pd
import plotly.express as px
import datetime
import calendar

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Gestion Bancaire", layout="wide")
st.title("💰 Mon Gestionnaire de Finances")

# --- INITIALISATION DES DONNÉES (Session State) ---
# Ces données resteront en mémoire tant que l'application tourne
if 'comptes' not in st.session_state:
    st.session_state['comptes'] = ['Compte Courant', 'Livret A', 'Livret Jeune']
if 'soldes_initiaux' not in st.session_state:
    st.session_state['soldes_initiaux'] = {'Compte Courant': 0.0, 'Livret A': 0.0, 'Livret Jeune': 0.0}
if 'transactions' not in st.session_state:
    # Création d'un dataframe vide avec les bonnes colonnes
    st.session_state['transactions'] = pd.DataFrame(
        columns=['ID', 'Date', 'Jour', 'Mois', 'Année', 'Type', 'Compte', 'Compte Cible', 'Catégorie', 'Nom', 'Montant']
    )

df = st.session_state['transactions']

# Listes prédéfinies
categories_list = ["Salaire", "Aide", "Virement", "Abonnement", "Voiture", "Cigarettes", "Occasion", "Appartement", "Course"]
mois_list = list(calendar.month_name)[1:] # Noms des mois (en anglais par défaut, on peut utiliser des chiffres pour simplifier)
mois_dict = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 
             7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}

# --- FONCTIONS UTILES ---
def calculer_soldes_actuels():
    soldes = st.session_state['soldes_initiaux'].copy()
    for _, row in df.iterrows():
        montant = float(row['Montant'])
        if row['Type'] == 'Entrée':
            soldes[row['Compte']] += montant
        elif row['Type'] == 'Sortie':
            soldes[row['Compte']] -= montant
        elif row['Type'] == 'Transfert':
            soldes[row['Compte']] -= montant
            soldes[row['Compte Cible']] += montant
    return soldes

# --- CREATION DES ONGLETS ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📝 Transactions", "⚙️ Paramètres"])

# ==========================================
# ONGLET 1 : DASHBOARD
# ==========================================
with tab1:
    st.header("Tableau de bord")
    
    if df.empty:
        st.info("Aucune transaction pour le moment. Ajoutez-en dans l'onglet 'Transactions'.")
    else:
        # 1. Solde des comptes
        st.subheader("Solde actuel des comptes")
        soldes_actuels = calculer_soldes_actuels()
        cols = st.columns(len(soldes_actuels) if len(soldes_actuels) > 0 else 1)
        for i, (compte, solde) in enumerate(soldes_actuels.items()):
            cols[i].metric(label=compte, value=f"{solde:.2f} €")

        st.divider()
        
        # Filtres temporels pour les graphiques
        annee_en_cours = datetime.datetime.now().year
        mois_en_cours = datetime.datetime.now().month

        # 2. Graphique d'évolution du solde (simplifié par mois)
        st.subheader(f"Évolution des soldes en {annee_en_cours}")
        df_annee = df[df['Année'] == annee_en_cours].sort_values(by=['Mois', 'Jour'])
        
        if not df_annee.empty:
            # On crée un historique chronologique pour tracer les courbes
            historique = []
            soldes_temp = st.session_state['soldes_initiaux'].copy()
            
            for _, row in df_annee.iterrows():
                if row['Type'] == 'Entrée': soldes_temp[row['Compte']] += row['Montant']
                elif row['Type'] == 'Sortie': soldes_temp[row['Compte']] -= row['Montant']
                elif row['Type'] == 'Transfert': 
                    soldes_temp[row['Compte']] -= row['Montant']
                    soldes_temp[row['Compte Cible']] += row['Montant']
                
                for cpt in st.session_state['comptes']:
                    historique.append({'Date': row['Date'], 'Compte': cpt, 'Solde': soldes_temp[cpt]})
                    
            df_hist = pd.DataFrame(historique)
            fig_evo = px.line(df_hist, x='Date', y='Solde', color='Compte', markers=True)
            st.plotly_chart(fig_evo, use_container_width=True)
        else:
            st.write("Pas assez de données pour l'évolution de cette année.")

        st.divider()

        # 3. Camembert répartition des dépenses (Sorties uniquement)
        col1, col2 = st.columns(2)
        df_sorties = df[df['Type'] == 'Sortie']
        
        with col1:
            st.subheader("Dépenses (Mois en cours)")
            df_mois = df_sorties[(df_sorties['Année'] == annee_en_cours) & (df_sorties['Mois'] == mois_en_cours)]
            if not df_mois.empty:
                fig_pie_mois = px.pie(df_mois, values='Montant', names='Catégorie', hole=0.4)
                st.plotly_chart(fig_pie_mois, use_container_width=True)
            else:
                st.write("Aucune dépense ce mois-ci.")
                
        with col2:
            st.subheader("Dépenses (Année en cours)")
            df_an = df_sorties[df_sorties['Année'] == annee_en_cours]
            if not df_an.empty:
                fig_pie_an = px.pie(df_an, values='Montant', names='Catégorie', hole=0.4)
                st.plotly_chart(fig_pie_an, use_container_width=True)
            else:
                st.write("Aucune dépense cette année.")

        st.divider()

        # 4. Moyenne sur les mois écoulés par catégorie
        st.subheader("Moyenne mensuelle par catégorie de dépense")
        if not df_sorties.empty:
            nb_mois_actifs = df_sorties['Mois'].nunique()
            if nb_mois_actifs > 0:
                df_moyenne = df_sorties.groupby('Catégorie')['Montant'].sum() / nb_mois_actifs
                st.bar_chart(df_moyenne)

        st.divider()

        # 5. Balance (Entrées vs Sorties)
        st.subheader("Balance (Entrées vs Sorties)")
        df_in_out = df[df['Type'].isin(['Entrée', 'Sortie'])]
        
        balance_annee = df_in_out[df_in_out['Année'] == annee_en_cours].groupby('Type')['Montant'].sum()
        entrees_annee = balance_annee.get('Entrée', 0)
        sorties_annee = balance_annee.get('Sortie', 0)
        
        col_b1, col_b2 = st.columns(2)
        col_b1.metric("Balance Annuelle", f"{entrees_annee - sorties_annee:.2f} €", f"Entrées: {entrees_annee} | Sorties: {sorties_annee}")
        
        df_in_out_mois = df_in_out[(df_in_out['Année'] == annee_en_cours) & (df_in_out['Mois'] == mois_en_cours)]
        balance_mois = df_in_out_mois.groupby('Type')['Montant'].sum()
        entrees_mois = balance_mois.get('Entrée', 0)
        sorties_mois = balance_mois.get('Sortie', 0)
        
        col_b2.metric("Balance du Mois", f"{entrees_mois - sorties_mois:.2f} €", f"Entrées: {entrees_mois} | Sorties: {sorties_mois}")


# ==========================================
# ONGLET 2 : TRANSACTIONS
# ==========================================
with tab2:
    st.header("Mes Transactions")
    
    # Choix de l'année
    annees_dispos = list(range(2020, datetime.datetime.now().year + 5))
    annee_choisie = st.selectbox("Sélectionnez l'année", annees_dispos, index=annees_dispos.index(datetime.datetime.now().year))
    
    with st.expander("➕ Ajouter une nouvelle transaction", expanded=False):
        with st.form("ajout_transaction_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                type_trans = st.radio("Type", ["Entrée", "Sortie", "Transfert"])
                mois_choisi_num = st.selectbox("Mois", list(mois_dict.keys()), format_func=lambda x: mois_dict[x])
                jour = st.number_input("Jour du mois", min_value=1, max_value=31, value=1)
                
            with col2:
                compte = st.selectbox("Compte Source", st.session_state['comptes'])
                compte_cible = st.selectbox("Compte Cible (si Transfert)", st.session_state['comptes']) if type_trans == "Transfert" else None
                categorie = st.selectbox("Catégorie", categories_list)
                nom = st.text_input("Nom de la transaction")
                montant = st.number_input("Montant (€)", min_value=0.01, step=1.0)
            
            submit_btn = st.form_submit_button("Enregistrer la transaction")
            
            if submit_btn:
                try:
                    date_val = datetime.date(annee_choisie, mois_choisi_num, int(jour))
                    nouvelle_ligne = {
                        'ID': len(st.session_state['transactions']) + 1,
                        'Date': date_val,
                        'Jour': int(jour),
                        'Mois': mois_choisi_num,
                        'Année': annee_choisie,
                        'Type': type_trans,
                        'Compte': compte,
                        'Compte Cible': compte_cible,
                        'Catégorie': categorie,
                        'Nom': nom,
                        'Montant': float(montant)
                    }
                    st.session_state['transactions'].loc[len(st.session_state['transactions'])] = nouvelle_ligne
                    st.success("Transaction ajoutée avec succès !")
                    st.rerun() # Rafraîchir pour mettre à jour l'affichage
                except ValueError:
                    st.error("Date invalide (ex: 31 Février n'existe pas).")
    
    st.divider()
    
    # Affichage des transactions par mois pour l'année sélectionnée
    df_annee_affichage = df[df['Année'] == annee_choisie].sort_values(by=['Mois', 'Jour'], ascending=[False, False])
    
    if df_annee_affichage.empty:
        st.write(f"Aucune transaction enregistrée pour l'année {annee_choisie}.")
    else:
        # Grouper par mois
        mois_presents = df_annee_affichage['Mois'].unique()
        for m in sorted(mois_presents, reverse=True):
            st.subheader(f"{mois_dict[m]} {annee_choisie}")
            df_mois = df_annee_affichage[df_annee_affichage['Mois'] == m].drop(columns=['ID', 'Mois', 'Année'])
            st.dataframe(df_mois, use_container_width=True, hide_index=True)


# ==========================================
# ONGLET 3 : PARAMÈTRES
# ==========================================
with tab3:
    st.header("Paramètres")
    
    col_param1, col_param2 = st.columns(2)
    
    with col_param1:
        st.subheader("💳 Gestion des Comptes")
        
        # Saisir/Modifier solde de départ
        st.write("**Définir les soldes de départ :**")
        for cpt in st.session_state['comptes']:
            nouveau_solde = st.number_input(f"Solde de départ - {cpt}", value=float(st.session_state['soldes_initiaux'][cpt]), step=100.0)
            st.session_state['soldes_initiaux'][cpt] = nouveau_solde

        st.divider()
        
        # Ajouter un compte
        nouveau_compte = st.text_input("Ajouter un nouveau compte")
        if st.button("Créer le compte"):
            if nouveau_compte and nouveau_compte not in st.session_state['comptes']:
                st.session_state['comptes'].append(nouveau_compte)
                st.session_state['soldes_initiaux'][nouveau_compte] = 0.0
                st.success(f"Compte '{nouveau_compte}' créé !")
                st.rerun()
                
        # Supprimer un compte
        compte_a_supprimer = st.selectbox("Supprimer un compte", st.session_state['comptes'])
        if st.button("Supprimer ce compte"):
            if len(st.session_state['comptes']) > 1:
                st.session_state['comptes'].remove(compte_a_supprimer)
                del st.session_state['soldes_initiaux'][compte_a_supprimer]
                st.warning(f"Compte '{compte_a_supprimer}' supprimé !")
                st.rerun()
            else:
                st.error("Vous devez garder au moins un compte.")

    with col_param2:
        st.subheader("💾 Exporter les données")
        st.write("Vous pouvez sauvegarder l'intégralité de vos transactions sur votre ordinateur sous forme de fichier Excel/CSV.")
        
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Télécharger mes transactions (CSV)",
                data=csv,
                file_name=f'transactions_bancaires_{datetime.date.today()}.csv',
                mime='text/csv',
            )
        else:
            st.info("Aucune donnée à exporter.")
            
        st.divider()
        st.subheader("⚠️ Remise à zéro")
        if st.button("Effacer toutes les transactions"):
            st.session_state['transactions'] = st.session_state['transactions'].iloc[0:0] # Vider le dataframe
            st.success("Toutes les données ont été effacées.")
            st.rerun()