import streamlit as st
import requests
import pandas as pd
import numpy as np
from scipy.stats import poisson

# --- KONFIGURACE ---
try:
    API_KEY = st.secrets["API_KEY"]
except:
    API_KEY = "VÁŠ_API_KLÍČ_ZDE" 

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {'x-rapidapi-host': "v3.football.api-sports.io", 'x-rapidapi-key': API_KEY}

# Váhy pro live intenzitu
WEIGHTS = {'SOT': 0.45, 'SIB': 0.35, 'CORNERS': 0.20}

class LiveWorldwideScanner:
    @staticmethod
    def fetch_stats(fixture_id):
        url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
        try:
            res = requests.get(url, headers=HEADERS).json().get('response', [])
            stats = {'home': {'sot':0, 'sib':0, 'corners':0, 'da':0, 'red':0},
                     'away': {'sot':0, 'sib':0, 'corners':0, 'da':0, 'red':0}}
            if not res: return stats
            for i, side in enumerate(['home', 'away']):
                if i < len(res):
                    r = {item['type']: item['value'] for item in res[i]['statistics']}
                    s = stats[side]
                    s['sot'] = int(r.get('Shots on Goal') or 0)
                    s['sib'] = int(r.get('Shots insidebox') or 0)
                    s['corners'] = int(r.get('Corner Kicks') or 0)
                    s['da'] = int(r.get('Dangerous Attacks') or 0)
                    s['red'] = int(r.get('Red Cards') or 0)
            return stats
        except: return None

    @staticmethod
    def calculate_live_lambda(h, a, elapsed):
        """Vypočítá λ pro ZBÝVAJÍCÍ čas zápasu."""
        remaining_time = 90 - elapsed
        if remaining_time <= 0: return 0.01
        
        def get_intensity(s):
            # Výpočet aktivity na minutu, kterou tým doposud předvedl
            base_perf = (s['sot'] * WEIGHTS['SOT']) + (s['sib'] * WEIGHTS['SIB']) + (s['corners'] * WEIGHTS['CORNERS'])
            perf_per_min = base_perf / elapsed
            
            # Projekce této intenzity do zbývajícího času
            projected_val = perf_per_min * remaining_time
            
            # Bonus za nebezpečné útoky (tlak)
            da_per_min = s['da'] / elapsed
            if da_per_min > 1.2: projected_val *= 1.2
            return projected_val

        # Součet projekcí obou týmů
        total_lambda = (get_intensity(h) + get_intensity(a)) * 0.8 # Konzervativní koeficient
        
        # Korekce na červené karty
        if (h['red'] + a['red']) > 0: total_lambda *= 1.2
            
        return round(total_lambda, 2)

# --- STREAMLIT UI ---
st.set_page_config(page_title="LIVE WORLDWIDE SCANNER", layout="wide")
st.title("⚽ Live Global Match Scanner")
st.caption("Sledování všech probíhajících zápasů na světě v reálném čase.")

# Filtry v sidebar
st.sidebar.header("⚙️ Live Filtry")
min_minute = st.sidebar.slider("Minimální minuta zápasu", 0, 90, 15)
max_minute = st.sidebar.slider("Maximální minuta zápasu", 0, 90, 85)

if st.button("🚀 SKENOVAT ŽIVÉ ZÁPASY", type="primary"):
    with st.spinner("Stahuji globální live data..."):
        url_live = f"{BASE_URL}/fixtures?live=all"
        all_live = requests.get(url_live, headers=HEADERS).json().get('response', [])
    
    # Filtrace zápasů v aktivním čase
    active_matches = [
        m for m in all_live 
        if m['fixture']['status']['short'] in ['1H', '2H', 'HT'] 
        and min_minute <= (m['fixture']['status']['elapsed'] or 0) <= max_minute
    ]
    
    if not active_matches:
        st.warning("Žádné zápasy neodpovídají nastavenému časovému filtru.")
    else:
        st.success(f"Analyzuji {len(active_matches)} probíhajících zápasů...")
        results = []
        progress_bar = st.progress(0)
        
        for i, m in enumerate(active_matches):
            fid = m['fixture']['id']
            elapsed = m['fixture']['status']['elapsed']
            stats = LiveWorldwideScanner.fetch_stats(fid)
            
            if stats and elapsed > 0:
                lam = LiveWorldwideScanner.calculate_live_lambda(stats['home'], stats['away'], elapsed)
                
                # Poisson: Šance na alespoň 1 další gól do konce zápasu
                prob_goal = round((1 - poisson.pmf(0, lam)) * 100, 1)

                results.append({
                    "Min": f"{elapsed}'",
                    "Liga": m['league']['name'],
                    "Zápas": f"{m['teams']['home']['name']} vs {m['teams']['away']['name']}",
                    "Skóre": f"{m['goals']['home']}:{m['goals']['away']}",
                    "Zbývá λ": lam,
                    "Šance na DALŠÍ GÓL": f"{prob_goal}%",
                    "Status": "🔥 TLAK" if prob_goal > 70 else "⚖️ VYROVNANÉ" if prob_goal > 40 else "🧊 KLID"
                })
            progress_bar.progress((i + 1) / len(active_matches))
        
        if results:
            df = pd.DataFrame(results).sort_values(by="Zbývá λ", ascending=False)
            st.dataframe(df, use_container_width=True, hide_index=True)
