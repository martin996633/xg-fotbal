import streamlit as st
import requests
import pandas as pd
import numpy as np
from scipy.stats import poisson

# --- KONFIGURACE ---
try:
    API_KEY = st.secrets["API_KEY"]
except:
    # Pokud nemáte nastaveno v secrets, vložte klíč sem
    API_KEY = "VÁŠ_API_KLÍČ_ZDE" 

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io",
    'x-rapidapi-key': API_KEY
}

# Váhy pro Heuristic xG Proxy (Klíčové pro přesnost bez oficiálního xG)
WEIGHTS = {
    'SOT': 0.40,      # Střely na bránu
    'SIB': 0.35,      # Střely z vápna
    'SOFF': 0.10,     # Střely mimo
    'CORNERS': 0.15   # Rohy
}

class GlobalHtScanner:
    """
    Engine pro globální skenování a výpočet predikcí.
    """
    
    @staticmethod
    def fetch_statistics(fixture_id):
        """Získá statistiky zápasu a namapuje je na Home/Away."""
        url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
        try:
            res = requests.get(url, headers=HEADERS).json().get('response', [])
            stats_map = {
                'home': {'sot': 0, 'sib': 0, 'soff': 0, 'corners': 0, 'da': 0, 'red': 0},
                'away': {'sot': 0, 'sib': 0, 'soff': 0, 'corners': 0, 'da': 0, 'red': 0}
            }
            if not res: return stats_map

            for i, side in enumerate(['home', 'away']):
                if i < len(res):
                    r = {item['type']: item['value'] for item in res[i]['statistics']}
                    s = stats_map[side]
                    s['sot'] = int(r.get('Shots on Goal') or 0)
                    s['sib'] = int(r.get('Shots insidebox') or 0)
                    s['soff'] = int(r.get('Shots off Goal') or 0)
                    s['corners'] = int(r.get('Corner Kicks') or 0)
                    s['da'] = int(r.get('Dangerous Attacks') or 0)
                    s['red'] = int(r.get('Red Cards') or 0)
            return stats_map
        except:
            return None

    @staticmethod
    def calculate_2h_lambda(stats_h, stats_a):
        """Vypočítá očekávaný počet gólů (λ) pro 2. poločas."""
        def get_team_intensity(s):
            # Základní síla z kvality šancí
            base = (s['sot'] * WEIGHTS['SOT']) + \
                   (s['sib'] * WEIGHTS['SIB']) + \
                   (s['corners'] * WEIGHTS['CORNERS'])
            
            # Multiplikátor pro nebezpečné útoky (Intenzita tlaku)
            da_per_min = s['da'] / 45
            if da_per_min > 1.2: base *= 1.25
            elif da_per_min > 0.8: base *= 1.1
            return base

        # Sečtení sil obou týmů a aplikace koeficientu pro 2. poločas (0.9 - 1.1)
        lam_2h = (get_team_intensity(stats_h) + get_team_intensity(stats_a)) * 0.95
        
        # Úprava pro červené karty (otevření prostorů na hřišti)
        red_cards = stats_h['red'] + stats_a['red']
        if red_cards > 0:
            lam_2h *= (1 + (0.2 * red_cards))
            
        return round(lam_2h, 2)

# --- STREAMLIT FRONTEND ---

st.set_page_config(page_title="WORLDWIDE HT SCANNER", layout="wide")

st.title("🌎 Worldwide Football HT Goal Prediction Engine")
st.markdown("---")

if st.button("🚀 SKENOVAT CELÝ SVĚT (Zápasy v poločase)", type="primary"):
    # 1. Stažení všech live zápasů světa bez filtru na ligy
    with st.spinner("Stahuji data o všech aktuálně hraných zápasech..."):
        url_live = f"{BASE_URL}/fixtures?live=all"
        try:
            live_fixtures = requests.get(url_live, headers=HEADERS).json().get('response', [])
        except Exception as e:
            st.error(f"Chyba spojení s API: {e}")
            live_fixtures = []

    # 2. Filtrace na stav "HT" (Halftime)
    ht_matches = [m for m in live_fixtures if m['fixture']['status']['short'] == 'HT']

    if not ht_matches:
        st.warning("Aktuálně se nikde na světě nehraje poločasová pauza. Zkuste to za 10-15 minut.")
    else:
        st.success(f"Nalezeno {len(ht_matches)} zápasů v poločase. Provádím hloubkovou analýzu...")
        
        results = []
        progress_bar = st.progress(0)
        
        for i, match in enumerate(ht_matches):
            fid = match['fixture']['id']
            stats = GlobalHtScanner.fetch_statistics(fid)
            
            if stats:
                # Výpočet predikce
                lam = GlobalHtScanner.calculate_2h_lambda(stats['home'], stats['away'])
                
                # Výpočet pravděpodobností pomocí Poissonovy distribuce
                # P(alespoň 1 gól ve 2. poločase)
                p_0_goals = poisson.pmf(0, lam)
                prob_1_plus = round((1 - p_0_goals) * 100, 1)
                
                # P(alespoň 2 góly ve 2. poločase)
                p_0_or_1_goal = poisson.pmf(0, lam) + poisson.pmf(1, lam)
                prob_2_plus = round((1 - p_0_or_1_goal) * 100, 1)

                results.append({
                    "Liga": match['league']['name'],
                    "Země": match['league']['country'],
                    "Zápas": f"{match['teams']['home']['name']} vs {match['teams']['away']['name']}",
                    "Skóre (HT)": f"{match['goals']['home']}:{match['goals']['away']}",
                    "Očekávané góly λ (2H)": lam,
                    "Šance na gól (2H)": f"{prob_1_plus}%",
                    "Šance na 2+ góly (2H)": f"{prob_2_plus}%",
                    "Signál": "🔥 HIGH" if prob_1_plus > 75 else "⚠️ MEDIUM" if prob_1_plus > 55 else "🧊 LOW"
                })
            
            progress_bar.progress((i + 1) / len(ht_matches))
        
        if results:
            df = pd.DataFrame(results).sort_values(by="Očekávané góly λ (2H)", ascending=False)
            
            # Stylování tabulky
            def color_signal(val):
                if val == "🔥 HIGH": return 'background-color: #ffcccc; color: black; font-weight: bold;'
                if val == "⚠️ MEDIUM": return 'background-color: #fff4cc; color: black;'
                if val == "🧊 LOW": return 'background-color: #e6f7ff; color: grey;'
                return ''

            st.dataframe(
                df.style.applymap(color_signal, subset=['Signál']),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.error("Nepodařilo se získat detailní statistiky pro nalezené zápasy.")
