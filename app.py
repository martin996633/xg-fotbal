import streamlit as st
import requests
import pandas as pd

# ================= KONFIGURACE =================
# Získání klíče bezpečně ze serveru (Secrets) nebo lokálně
try:
    API_KEY = st.secrets["API_KEY"]
except FileNotFoundError:
    # Pokud běžíte lokálně a nemáte secrets nastavené
    API_KEY = "ZDE_MUZETE_DAT_KLIC_PRO_LOKALNI_TEST" 

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io",
    'x-rapidapi-key': API_KEY
}

# Top 5 Lig: PL (39), La Liga (140), Bundesliga (78), Serie A (135), Ligue 1 (61)
LEAGUE_IDS = [39, 140, 78, 135, 61]

# ================= FUNKCE =================
def get_live_matches():
    ids_string = "-".join(map(str, LEAGUE_IDS))
    # Parametr live=all-ids nefunguje vzdy spolehlive pro filtr, 
    # proto stahneme vsechny live zapasy techto lig
    url = f"{BASE_URL}/fixtures?live={ids_string}"
    try:
        response = requests.get(url, headers=HEADERS)
        return response.json().get('response', [])
    except Exception as e:
        st.error(f"Chyba API: {e}")
        return []

def get_match_xg(fixture_id):
    url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        data = response.json().get('response', [])
        if not data: return 0.0, 0.0
        
        home_xg, away_xg = 0.0, 0.0
        for stat in data[0]['statistics']:
            if stat['type'] == 'expected_goals': home_xg = float(stat['value'] or 0)
        for stat in data[1]['statistics']:
            if stat['type'] == 'expected_goals': away_xg = float(stat['value'] or 0)
        return home_xg, away_xg
    except:
        return 0.0, 0.0

def analyze_match(match):
    fixture = match['fixture']
    goals = match['goals']
    teams = match['teams']
    
    home = teams['home']['name']
    away = teams['away']['name']
    s_home = goals['home'] or 0
    s_away = goals['away'] or 0
    
    xg_h, xg_a = get_match_xg(fixture['id'])
    total_g = s_home + s_away
    total_xg = xg_h + xg_a
    diff = total_xg - total_g
    
    pred = "No Bet"
    if diff > 1.2: pred = "🔥 OVER GÓLY"
    elif diff > 0.6: pred = "⚡ OVER GÓLY"
    elif diff < -1.5: pred = "🧊 UNDER"

    return {
        "Minuta": f"{fixture['status']['elapsed']}'",
        "Zápas": f"{home} - {away}",
        "Skóre": f"{s_home}:{s_away}",
        "xG": f"{total_xg:.2f}",
        "Rozdíl": round(diff, 2),
        "Tip": pred
    }

# ================= FRONTEND =================
st.set_page_config(page_title="xG Scanner", layout="centered") # layout centered je lepsi pro mobil
st.title("⚽ Live xG Scanner")

if st.button("🔄 AKTUALIZOVAT DATA", type="primary"):
    with st.spinner('Analyzuji zápasy...'):
        matches = get_live_matches()
        if not matches:
            st.warning("V Top 5 ligách se právě nic nehraje.")
        else:
            data = []
            bar = st.progress(0)
            for i, m in enumerate(matches):
                data.append(analyze_match(m))
                bar.progress((i + 1) / len(matches))
            
            df = pd.DataFrame(data)
            
            # Barevné stylování
            def color_rows(val):
                color = ''
                if '🔥' in str(val): color = 'background-color: #ffcccc'
                elif '⚡' in str(val): color = 'background-color: #ffffcc'
                return color

            st.dataframe(df.style.applymap(color_rows, subset=['Tip']), hide_index=True)
