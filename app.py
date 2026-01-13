import streamlit as st
import requests
import pandas as pd

# ================= KONFIGURACE =================
try:
    API_KEY = st.secrets["API_KEY"]
except FileNotFoundError:
    API_KEY = "VÁŠ_API_KLÍČ_ZDE"

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io",
    'x-rapidapi-key': API_KEY
}

# Top ligy + Další zajímavé
LEAGUES = {
    "Všechny ligy": "all",
    "Premier League": 39,
    "La Liga": 140,
    "Bundesliga": 78,
    "Serie A": 135,
    "Ligue 1": 61,
    "Championship": 40,
    "Eredivisie": 88,
    "Primeira Liga": 94
}

# ================= LOGIKA A VÝPOČTY =================

def get_live_matches(league_id=None):
    url = f"{BASE_URL}/fixtures?live=all"
    if league_id and league_id != "all":
        url = f"{BASE_URL}/fixtures?live={league_id}"
        
    try:
        response = requests.get(url, headers=HEADERS)
        return response.json().get('response', [])
    except Exception as e:
        st.error(f"Chyba API: {e}")
        return []

def get_stats(fixture_id):
    url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        data = response.json().get('response', [])
        
        stats = {
            'home': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'corners': 0, 'poss': 50, 'saves': 0},
            'away': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'corners': 0, 'poss': 50, 'saves': 0}
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
            stats[team]['saves'] = get_val('Goalkeeper Saves')
            
        return stats
    except:
        return None

def calculate_pressure_index(s):
    idx = (s['xg'] * 10) + (s['sot'] * 3) + (s['sib'] * 2) + s['corners']
    if s['poss'] > 65: idx += 5
    return round(idx, 1)

def analyze_match(match):
    fix = match['fixture']
    goals = match['goals']
    teams = match['teams']
    
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
    if (p_home > 30 and g_h == 0) or (p_away > 30 and g_a == 0):
        tip = "🔥 GÓL VISÍ (Tlak)"
        strength = 3
    # 2. xG Value
    elif total_xg_diff > 1.3:
        tip = "⚡ OVER (xG)"
        strength = 2
    # 3. Otevřený zápas
    elif (s_home['sot'] + s_away['sot']) >= 10 and (g_h + g_a) <= 1:
        tip = "⚽ SHOOTOUT"
        strength = 1
    # 4. Under
    elif total_xg_diff < -1.5:
        tip = "🧊 UNDER"
        strength = 1

    # Formátování s lomítkem (bezpečné pro Streamlit)
    return {
        "strength": strength,
        "Min": f"{fix['status']['elapsed']}'",
        "Zápas": f"{teams['home']['name']} vs {teams['away']['name']}",
        "Skóre": f"{g_h} - {g_a}",
        "xG": f"{s_home['xg']} / {s_away['xg']}",
        "Tlak Index": f"{p_home} / {p_away}",
        "Střely (brána)": f"{s_home['shots']}({s_home['sot']}) / {s_away['shots']}({s_away['sot']})",
        "Rohy": f"{s_home['corners']} / {s_away['corners']}",
        "PREDIKCE": tip
    }

# ================= FRONTEND =================
st.set_page_config(page_title="PRO xG Scanner", layout="wide")

st.sidebar.header("⚙️ Filtry")
selected_league_name = st.sidebar.selectbox("Liga", list(LEAGUES.keys()))
selected_league_id = LEAGUES[selected_league_name]
only_ht = st.sidebar.checkbox("Jen Poločas (HT)", value=False)

st.title("⚽ PRO Live Scanner")

if st.button("🔄 ANALYZOVAT TRH", type="primary"):
    with st.spinner('Stahuji data...'):
        matches = get_live_matches(selected_league_id)
        
        if only_ht:
            matches = [m for m in matches if m['fixture']['status']['short'] == 'HT']
            
        if not matches:
            st.warning("Žádné zápasy.")
        else:
            data = []
            bar = st.progress(0)
            for i, m in enumerate(matches):
                res = analyze_match(m)
                if res: data.append(res)
                bar.progress((i + 1) / len(matches))
            
            if data:
                df = pd.DataFrame(data)
                # Řazení podle síly tipu
                df = df.sort_values(by='strength', ascending=False).drop(columns=['strength'])
                
                # Funkce pro barvení řádků
                def highlight_rows(val):
                    color = ''
                    if '🔥' in str(val): color = 'background-color: #ffcccc'
                    elif '⚡' in str(val): color = 'background-color: #fff4cc'
                    elif '🧊' in str(val): color = 'background-color: #e6f7ff'
                    return color

                # Zobrazení tabulky (bez HTML hacků)
                st.dataframe(
                    df.style.applymap(highlight_rows, subset=['PREDIKCE']),
                    use_container_width=True,
                    hide_index=True,
                    height=600
                )
            else:
                st.info("Zápasy běží, ale chybí detailní stats.")
