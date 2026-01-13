import streamlit as st
import requests
import pandas as pd

# ================= KONFIGURACE =================
try:
    API_KEY = st.secrets["API_KEY"]
except FileNotFoundError:
    # ⚠️ ZDE VLOŽ SVŮJ API KLÍČ
    API_KEY = "VÁŠ_API_KLÍČ_ZDE"

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io",
    'x-rapidapi-key': API_KEY
}

# Definice TOP 5 lig (ID)
TOP5_IDS = [39, 140, 78, 135, 61]

LEAGUES = {
    "⚡ TOP 5 MIX (Vše najednou)": "top5",
    "Premier League 🇬🇧": 39,
    "La Liga 🇪🇸": 140,
    "Bundesliga 🇩🇪": 78,
    "Serie A 🇮🇹": 135,
    "Ligue 1 🇫🇷": 61
}

# ================= LOGIKA A VÝPOČTY =================

def get_live_matches(league_selection):
    """
    Stáhne live zápasy. Pokud je vybráno 'top5', stáhne vše a vyfiltruje jen TOP 5 lig.
    """
    try:
        if league_selection == "top5":
            # Stáhneme vše, filtrování proběhne v Pythonu
            url = f"{BASE_URL}/fixtures?live=all"
        else:
            # Stáhneme konkrétní ligu
            url = f"{BASE_URL}/fixtures?live={league_selection}"
        
        response = requests.get(url, headers=HEADERS)
        matches = response.json().get('response', [])
        
        # Pokud chceme TOP 5 MIX, musíme vyfiltrovat ostatní ligy (např. Uzbekistán atd.)
        if league_selection == "top5":
            matches = [m for m in matches if m['league']['id'] in TOP5_IDS]
            
        return matches
    except Exception as e:
        st.error(f"Chyba API: {e}")
        return []

def get_stats(fixture_id):
    url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        data = response.json().get('response', [])
        
        stats = {
            'home': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'corners': 0, 'poss': 50},
            'away': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'corners': 0, 'poss': 50}
        }
        
        if not data: return stats

        for i, team in enumerate(['home', 'away']):
            if i >= len(data): break
            t_stats = {item['type']: item['value'] for item in data[i]['statistics']}
            
            def get_val(key, type_cast=int):
                val = t_stats.get(key)
                if val is None: return 0
                try: 
                    return type_cast(str(val).replace('%', ''))
                except: return 0

            stats[team]['xg'] = get_val('expected_goals', float)
            stats[team]['shots'] = get_val('Total Shots')
            stats[team]['sot'] = get_val('Shots on Goal')
            stats[team]['sib'] = get_val('Shots insidebox')
            stats[team]['corners'] = get_val('Corner Kicks')
            stats[team]['poss'] = get_val('Ball Possession')
            
        return stats
    except:
        return None

def calculate_pressure_index(s):
    # Vážený index tlaku
    idx = (s['xg'] * 10) + (s['sot'] * 3) + (s['sib'] * 2) + s['corners']
    if s['poss'] > 65: idx += 5
    return round(idx, 1)

def analyze_match(match):
    fix = match['fixture']
    goals = match['goals']
    teams = match['teams']
    league_name = match['league']['name']
    
    stats = get_stats(fix['id'])
    if not stats: return None

    s_home = stats['home']
    s_away = stats['away']
    
    g_h = goals['home'] or 0
    g_a = goals['away'] or 0
    
    p_home = calculate_pressure_index(s_home)
    p_away = calculate_pressure_index(s_away)
    
    total_xg_diff = (s_home['xg'] + s_away['xg']) - (g_h + g_a)

    # === PREDIKCE ===
    tip = ""
    strength = 0
    
    # 1. Tlak (Gól visí ve vzduchu)
    if (p_home > 35 and g_h == 0) or (p_away > 35 and g_a == 0):
        tip = "🔥 GÓL VISÍ (Vysoký tlak)"
        strength = 3
    # 2. xG Value (Skóre neodpovídá šancím)
    elif total_xg_diff > 1.5:
        tip = "⚡ OVER (xG Value)"
        strength = 2
    # 3. Otevřený zápas (Hodně střel na bránu)
    elif (s_home['sot'] + s_away['sot']) >= 12 and (g_h + g_a) <= 1:
        tip = "⚽ SHOOTOUT (Hodně střel)"
        strength = 1
    # 4. Under (Nuda)
    elif total_xg_diff < -1.5 and (p_home + p_away) < 20:
        tip = "🧊 UNDER"
        strength = 1

    return {
        "strength": strength,
        "Liga": league_name,
        "Min": f"{fix['status']['elapsed']}'",
        "Zápas": f"{teams['home']['name']} vs {teams['away']['name']}",
        "Skóre": f"{g_h} - {g_a}",
        "xG": f"{s_home['xg']} / {s_away['xg']}",
        "Tlak": f"{p_home} / {p_away}",
        "Střely (brána)": f"{s_home['shots']}({s_home['sot']}) / {s_away['shots']}({s_away['sot']})",
        "Rohy": f"{s_home['corners']} / {s_away['corners']}",
        "PREDIKCE": tip
    }

# ================= FRONTEND =================
st.set_page_config(page_title="PRO xG Scanner (TOP 5)", layout="wide")

st.sidebar.header("⚙️ Nastavení")
selected_league_name = st.sidebar.selectbox("Vyber ligu:", list(LEAGUES.keys()))
selected_league_id = LEAGUES[selected_league_name]

only_ht = st.sidebar.checkbox("Jen Poločas (HT)", value=False)
min_minute = st.sidebar.slider("Minimální minuta zápasu", 0, 90, 0)

st.title("⚽ Live xG Scanner (TOP 5 Lig)")
st.caption("Sleduje pouze: Premier League, La Liga, Bundesliga, Serie A, Ligue 1")

if st.button("🔄 ANALYZOVAT TRH", type="primary"):
    with st.spinner(f'Stahuji live data pro: {selected_league_name}...'):
        matches = get_live_matches(selected_league_id)
        
        # Filtrace podle minuty
        matches = [m for m in matches if m['fixture']['status']['elapsed'] >= min_minute]

        if only_ht:
            matches = [m for m in matches if m['fixture']['status']['short'] == 'HT']
            
        if not matches:
            st.warning("Právě se nehrají žádné zápasy v této kategorii.")
        else:
            data = []
            progress_text = "Analyzuji detailní statistiky (xG, střely, tlak)..."
            bar = st.progress(0, text=progress_text)
            
            for i, m in enumerate(matches):
                res = analyze_match(m)
                if res: data.append(res)
                bar.progress((i + 1) / len(matches), text=progress_text)
            
            bar.empty()
            
            if data:
                df = pd.DataFrame(data)
                # Řazení: Nejdřív nejsilnější tipy, pak podle minuty
                df = df.sort_values(by=['strength', 'Min'], ascending=[False, False]).drop(columns=['strength'])
                
                # Barvení
                def highlight_rows(val):
                    color = ''
                    if '🔥' in str(val): color = 'background-color: #ffcccc; color: black;'
                    elif '⚡' in str(val): color = 'background-color: #fff4cc; color: black;'
                    elif '🧊' in str(val): color = 'background-color: #e6f7ff; color: black;'
                    return color

                st.dataframe(
                    df.style.applymap(highlight_rows, subset=['PREDIKCE']),
                    use_container_width=True,
                    hide_index=True,
                    height=600
                )
            else:
                st.info("Zápasy běží, ale API zatím neposkytlo detailní statistiky (střely/xG). Zkus to za pár minut.")
