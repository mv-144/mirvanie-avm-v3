import streamlit as st
import pandas as pd
import datetime
from fpdf import FPDF
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURATION ---
st.set_page_config(page_title="Mirvanie - Estimateur", page_icon="🏠", layout="wide")

# --- CONNEXION GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- CHARGEMENT DES PRIX ---
@st.cache_data
def load_zones():
    try:
        df = pd.read_excel('mirvanie_grille_corrigee.xlsx', sheet_name='Zones')
        df.columns = df.columns.str.strip().str.lower()
        return df
    except Exception as e:
        st.error(f"Erreur de chargement de l'Excel : {e}")
        return pd.DataFrame()

df_zones = load_zones()

# --- GÉNÉRATION DU PDF ---
def generate_pdf(data, details):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_fill_color(0, 86, 179)
    pdf.rect(0, 0, 210, 30, 'F')
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 20, "MIRVANIE - RAPPORT D'ESTIMATION", ln=True, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(15)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "Informations du bien", ln=True)
    pdf.set_font("Arial", size=12)
    for key, value in data.items():
        pdf.cell(0, 8, f"{key} : {value}", ln=True)
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "Détail de l'estimation", ln=True)
    pdf.set_font("Arial", size=12)
    for key, value in details.items():
        pdf.cell(0, 8, f"{key} : {value}", ln=True)
    pdf.ln(20)
    pdf.set_font("Arial", 'I', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, "Estimation indicative generee par Mirvanie.", ln=True, align='C')
    return pdf.output(dest='S').encode('latin-1')

# --- LOGIQUE D'ESTIMATION ---
def calculer_estimation(loc, type_bien, segment, surf_hab, surf_terrain, annee, etat, docs, equipements, parking_choices):
    resultat = df_zones[(df_zones['localisation'] == loc) & 
                        (df_zones['type_bien'] == type_bien) & 
                        (df_zones['segment'] == segment)]
    
    if resultat.empty:
        return None, None, "Données non disponibles pour cette combinaison."
    
    prix_m2 = (resultat.iloc[0]['prix_min_m2'] + resultat.iloc[0]['prix_max_m2']) / 2
    
    # --- LOGIQUE DE VÉTUSTÉ ---
    age = max(0, datetime.datetime.now().year - annee)
    coef_vetuste = max(0.70, 1 - (age * 0.01)) 
    coef_etat = {"excellent": 1.10, "bon": 1.00, "moyen": 0.85, "à rénover": 0.60}
    
    # --- LOGIQUE DOCUMENTS FONCIERS (Prix le plus élevé si choix multiples) ---
    coef_doc_map = {"Titre foncier": 1.15, "Arrêté de concession définitive": 1.10, 
                    "Lettre d'attribution": 0.90, "Non communiqué": 0.80}
    # On cherche le coefficient le plus protecteur parmi les documents sélectionnés
    coef_doc = max([coef_doc_map.get(d, 0.80) for d in docs])
    
    # --- CALCULS ---
    if type_bien == "Terrain":
        valeur_bati = 0
        valeur_terrain = surf_terrain * prix_m2 * coef_doc
    else:
        # Pour une maison, on estime que le terrain vaut 30% du prix global de la zone
        prix_terrain_m2 = prix_m2 * 0.30
        valeur_bati = surf_hab * prix_m2 * coef_etat.get(etat.lower(), 1.0) * coef_vetuste
        surf_terrain_libre = max(0, surf_terrain - surf_hab)
        valeur_terrain = surf_terrain_libre * prix_terrain_m2 * coef_doc
    
    # --- ÉQUIPEMENTS & PARKING ---
    bonus_equip = 0
    if "Piscine" in equipements: bonus_equip += 0.08
    if "Ascenseur" in equipements: bonus_equip += 0.05
    if "Groupe électrogène" in equipements or "panneau solaire" in equipements: bonus_equip += 0.04
    if "Balcon/Terrasse" in equipements: bonus_equip += 0.03
    bonus_equip = min(bonus_equip, 0.20)
    
    # Logique Parking Multiple
    bonus_parking = 0
    if "Privé" in parking_choices: bonus_parking += 0.03
    if "Garage" in parking_choices: bonus_parking += 0.05
    if "Rue" in parking_choices: bonus_parking += 0.00 # La rue n'ajoute pas de valeur
    bonus_parking = min(bonus_parking, 0.09)
    
    estimation_finale = (valeur_bati * (1 + bonus_equip + bonus_parking)) + valeur_terrain
    
    details = {
        "Valeur du bâti": f"{valeur_bati:,.0f} FCFA" if type_bien != "Terrain" else "N/A",
        "Valeur du terrain": f"{valeur_terrain:,.0f} FCFA",
        "Bonus équipements": f"{bonus_equip*100:+.1f}%",
        "Bonus parking": f"{bonus_parking*100:+.1f}%",
        "Décote vétusté": f"{(coef_vetuste-1)*100:.1f}%" if type_bien != "Terrain" else "N/A"
    }
    
    return estimation_finale, details, None

# --- INTERFACE PRINCIPALE ---
tab1, tab2 = st.tabs(["🏠 Nouvelle Estimation", "🔐 Admin Mirvanie"])

with tab1:
    st.title("🏠 Estimateur Immobilier Mirvanie")
    st.write("Propulsé par l'analyse des micro-zones de Côte d'Ivoire.")

    if not df_zones.empty:
        with st.form("estimation_form"):
            st.subheader("📍 Localisation")
            communes = sorted(df_zones['localisation'].unique())
            loc_choisie = st.selectbox("Sélectionnez la micro-zone :", communes)
            
            types_dispo = sorted(df_zones[df_zones['localisation'] == loc_choisie]['type_bien'].unique())
            type_choisi = st.selectbox("Type de bien :", types_dispo)
            
            segments_dispo = sorted(df_zones[(df_zones['localisation'] == loc_choisie) & 
                                             (df_zones['type_bien'] == type_choisi)]['segment'].unique())
            segment_choisi = st.selectbox("Marché (Neuf ou Ancien) :", segments_dispo)

            st.subheader("📐 Configuration")
            col1, col2 = st.columns(2)
            
            with col1:
                surface_habitable = st.number_input("Surface habitable (m²) :", min_value=0, value=100 if type_choisi != "Terrain" else 0)
                surface_terrain = st.number_input("Surface totale du terrain (m²) :", min_value=10, value=100)
                annee_construction = st.number_input("Année de construction :", min_value=1900, max_value=2026, value=2015 if type_choisi != "Terrain" else 2026)
                etat_bien = st.selectbox("État du bien :", ["excellent", "bon", "moyen", "à rénover"]) if type_choisi != "Terrain" else None

            with col2:
                # NOUVEAU : Choix multiples pour les documents fonciers
                docs_foncier = st.multiselect("Document(s) foncier(s) :", [
                    "Titre foncier", "Arrêté de concession définitive", "Certificat de mutation", 
                    "Lettre d'attribution", "Acte notarié de vente", "Non communiqué"
                ], default=["Titre foncier"])
                
                # NOUVEAU : Choix multiples pour le stationnement
                parking_choices = st.multiselect("Stationnement (plusieurs choix possibles) :", [
                    "Aucun", "Rue", "Privé", "Garage"
                ], default=["Aucun"])
                
                equipements = st.multiselect("Équipements :", [
                    "Balcon/Terrasse", "Ascenseur", "Piscine", "panneau solaire", "Groupe électrogène"
                ])

            submit = st.form_submit_button("💰 Lancer l'estimation", use_container_width=True)

        if submit:
            estimation, details, erreur = calculer_estimation(
                loc_choisie, type_choisi, segment_choisi, 
                surface_habitable, surface_terrain, annee_construction,
                etat_bien, docs_foncier, equipements, parking_choices
            )
            
            if erreur:
                st.warning(erreur)
            else:
                st.success("### 📊 Estimation Mirvanie")
                col_res1, col_res2 = st.columns([1, 1])
                with col_res1:
                    st.metric(label="Valeur estimée", value=f"{estimation:,.0f} FCFA")
                    st.info(f"📉 **Basse (-10%)** : {estimation * 0.90:,.0f} FCFA\n\n📈 **Haute (+10%)** : {estimation * 1.10:,.0f} FCFA")
                with col_res2:
                    st.write("**Détail du calcul :**")
                    for k, v in details.items():
                        st.write(f"- {k} : **{v}**")
                
                # --- SAUVEGARDE DANS GOOGLE SHEETS ---
                try:
                    df_actuel = conn.read(worksheet="Sheet1", ttl=0) # Lit les données actuelles
                    nouvelle_ligne = pd.DataFrame([{
                        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "adresse": loc_choisie,
                        "type_bien": type_choisi,
                        "annee": annee_construction,
                        "surface_habitable": surface_habitable,
                        "surface_terrain": surface_terrain,
                        "estimation_totale": estimation
                    }])
                    df_mis_a_jour = pd.concat([df_actuel, nouvelle_ligne], ignore_index=True)
                    conn.update(worksheet="Sheet1", data=df_mis_a_jour)
                    st.toast("✅ Estimation sauvegardée dans Google Sheets !")
                except Exception as e:
                    st.warning(f"Impossible de sauvegarder dans Google Sheets (Vérifiez la configuration). Erreur : {e}")

                # PDF
                pdf_data = {
                    "Adresse": loc_choisie, "Type": type_choisi, "Marché": segment_choisi,
                    "Surface habitable": f"{surface_habitable} m²", "Surface terrain": f"{surface_terrain} m²",
                    "Estimation": f"{estimation:,.0f} FCFA"
                }
                pdf_bytes = generate_pdf(pdf_data, details)
                st.download_button("📄 Télécharger le rapport (PDF)", data=pdf_bytes, file_name="rapport_mirvanie.pdf", mime="application/pdf")

# --- ONGLET ADMIN ---
with tab2:
    st.title("🔐 Espace Administrateur")
    
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        password = st.text_input("Mot de passe :", type="password")
        if st.button("Connexion"):
            # Le mot de passe par défaut est admin123 si pas configuré dans les secrets
            if password == st.secrets.get("ADMIN_PASSWORD", "admin123"):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
    else:
        st.success("Connecté.")
        if st.button("Déconnexion"):
            st.session_state.authenticated = False
            st.rerun()
        
        # LECTURE DEPUIS GOOGLE SHEETS
        try:
            df_estimations = conn.read(worksheet="Sheet1", ttl=0)
            
            if not df_estimations.empty:
                st.metric("Total des estimations", len(df_estimations))
                csv = df_estimations.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Exporter (CSV)", data=csv, file_name="estimations_mirvanie.csv", mime="text/csv")
                st.dataframe(df_estimations, use_container_width=True)
            else:
                st.info("Aucune estimation enregistrée pour le moment.")
        except Exception as e:
            st.error(f"Erreur de connexion à Google Sheets : {e}")