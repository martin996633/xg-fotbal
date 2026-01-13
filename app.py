import streamlit as st
import requests
import pandas as pd

# --- CONFIGURATION ---
# Načtení ze secrets s ošetřením chyb
try:
    API_KEY = st.secrets["api_key"].strip()
except Exception:
    st.error("Chybí 'api_key' v Streamlit Secrets! Prosím přidej ho do nastavení.")
    st.stop()

BASE_URL = "https://api-football-beta.p.rapidapi.com"
HEADERS = {
    "X-RapidAPI-Key": API_KEY,
    "X-RapidAPI-Host": "api-football-beta.p.rapidapi.com"
}

class LiveMatchData:
    def __init__(self):
        self.headers = HEADERS

    def fetch_live_matches(self):
        url = f"{BASE_URL}/fixtures"
        # Hledáme všechny live zápasy, filtrovat HT budeme až v logice
        params = {"live": "all"}
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get('response', [])
            # Filtrace na poločas (HT)
            return [m for m in data if m['fixture']['status']['short'] == 'HT']
        except Exception as e:
            st.error(f"Chyba při volání API (Fixtures): {e}")
            return []

    def fetch_stats(self, fixture_id):
        url = f"{BASE_URL}/fixtures/statistics"
        try:
            resp = requests.get(url, headers=self.headers, params={"fixture": fixture_id}, timeout=10)
            return resp.json().get('response', [])
        except:
            return []

    def fetch_events(self, fixture_id):
        url = f"{BASE_URL}/fixtures/events"
        try:
            resp = requests.get(url, headers=self.headers, params={"fixture": fixture_id}, timeout=10)
            return resp.json().get('response', [])
        except:
            return []

# --- MATH FUNCTIONS (Heuristic xG & PI) ---
def get_stat(stats_list, stat_name):
    """Bezpečně vytáhne hodnotu statistiky z listu slovníků API."""
    for s in stats_list:
        if s['type'] == stat_name:
            val = s['value']
            if val is None: return 0
            if isinstance(val, str) and "%" in val:
                return float(val.replace('%', '')) / 100
            return float(val)
    return 0

def run_analysis(match, engine):
    f_id = match['fixture']['id']
    stats_data = engine.fetch_stats(f_id)
    events_data = engine.fetch_events(f_id)

    if len(stats_data) < 2:
        return None

    # Rozdělení statistik
    h_s = stats_data[0]['statistics']
    a_s = stats_data[1]['statistics']

    # Výpočet xG Proxy
    def calc_xg(s, evts):
        penalties = sum(1 for e in evts if e.get('type') == 'Penalty')
        return round((get_stat(s, 'Shots insidebox') * 0.13) + 
                     (get_stat(s, 'Shots outsidebox') * 0.03) + 
                     (get_stat(s, 'Shots on Goal') * 0.15) + 
                     (penalties * 0.79), 2)

    # Výpočet Pressure Indexu
    def calc_pi(s):
        pos_diff = (get_stat(s, 'Ball Possession') * 100) - 50
        return round((get_stat(s, 'Corner Kicks') * 3.0) + 
                     (get_stat(s, 'Shots on Goal') * 5.0) + 
                     (pos_diff * 0.5), 2)

    h_xg, a_xg = calc_xg(h_s, events_data), calc_xg(a_s, events_data)
    h_pi, a_pi = calc_pi(h_s), calc_pi(a_s)
    
    # Bayesovská predikce 2H gólů
    score_h = match['goals']['home'] or 0
    score_a = match['goals']['away'] or 0
    
    # Základní lambda + live performance
    l_live = ((h_xg + a_xg) * 1.1) + ((h_pi + a_pi) / 150)
    exp_2h = (1.35 * 0.3) + (l_live * 0.7)
    
    # Signalizace
    signal = "Brak analýzy"
    if score_h == 0 and score_a == 0 and (h_pi + a_pi) > 80:
        signal = "🔥 OVER 0.5 GOALS (2H)"
    elif (score_h < score_a) and (h_pi > a_pi * 1.8):
        signal = "⭐ LATE GOAL FAVORITE"
    elif (h_pi + a_pi) < 30:
        signal = "❄️ DEAD GAME"

    return {
        "Zápas": f"{match['teams']['home']['name']} vs {match['teams']['away']['name']}",
        "Skóre HT": f"{score_h}:{score_a}",
        "Total xG": round(h_xg + a_xg, 2),
        "Total PI": round(h_pi + a_pi, 2),
        "Predikce 2H": round(exp_2h, 2),
        "SIGNÁL": signal
    }

# --- UI ---
st.set_page_config(page_title="2H Goal Engine", layout="wide")
st.title("📊 Senior Quant: Live 2H Strategy")

if st.button("Analyzovat HT zápasy"):
    engine = LiveMatchData()
    ht_matches = engine.fetch_live_matches()
    
    if not ht_matches:
        st.info("Momentálně nejsou v systému žádné zápasy ve fázi HT (poločas).")
    else:
        results = []
        progress_bar = st.progress(0)
        for idx, m in enumerate(ht_matches):
            res = run_analysis(m, engine)
            if res:
                results.append(res)
            progress_bar.progress((idx + 1) / len(ht_matches))
        
        if results:
            df = pd.DataFrame(results)
            st.dataframe(df.style.highlight_max(subset=['Total PI'], color='lightgreen'))
        else:
            st.warning("Nepodařilo se získat dostatek statistik pro analýzu.")
