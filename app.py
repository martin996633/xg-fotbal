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

LEAGUES = {
    "⚡ TOP 5 MIX": "top5",
    "Premier League 🇬🇧": 39,
    "La Liga 🇪🇸": 140,
    "Bundesliga 🇩🇪": 78,
    "Serie A 🇮🇹": 135,
    "Ligue 1 🇫🇷": 61
}
TOP5_IDS = [39, 140, 78, 135, 61]

# ================= DATA MINING =================

def get_live_matches(league_selection):
    try:
        url = f"{BASE_URL}/fixtures?live=all"
        if league_selection != "top5":
            url = f"{BASE_URL}/fixtures?live={league_selection}"
        
        response = requests.get(url, headers=HEADERS)
        matches = response.json().get('response', [])
        
        if league_selection == "top5":
            matches = [m for m in matches if m['league']['id'] in TOP5_IDS]
        return matches
    except:
        return []

def get_stats(fixture_id):
    url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        data = response.json().get('response', [])
        
        # Inicializace všech 14 metrik
        stats = {
            'home': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'blocked': 0, 'da': 0, 'corners': 0, 'poss': 50, 'saves': 0, 'fouls': 0, 'yc': 0, 'rc': 0, 'passes': 0},
            'away': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'blocked': 0, 'da': 0, 'corners': 0, 'poss': 50, 'saves': 0, 'fouls': 0, 'yc': 0, 'rc': 0, 'passes': 0}
        }
        
        if not data: return stats

        for i, team in enumerate(['home', 'away']):
            if i >= len(data): break
            t_stats = {item['type']: item['value'] for item in data[i]['statistics']}
            
            def get_val(key, type_cast=int):
                val = t_stats.get(key)
                if val is None: return 0
                try: return type_cast(str(val).replace('%', ''))
                except: return 0

            s = stats[team]
            s['xg'] = get_val('expected_goals', float)
            s['shots'] = get_val('Total Shots')
            s['sot'] = get_val('Shots on Goal')
            s['sib'] = get_val('Shots insidebox')
            s['blocked'] = get_val('Blocked Shots')
            s['da'] = get_val('Dangerous Attacks')
            s['corners'] = get_val('Corner Kicks')
            s['poss'] = get_val('Ball Possession')
            s['saves'] = get_val('Goalkeeper Saves')
            s['fouls'] = get_val('Fouls')
            s['yc'] = get_val('Yellow Cards')
            s['rc'] = get_val('Red Cards')
            s['passes'] = get_val('Passes %')
            
        return stats
    except:
        return None

def analyze_match(match):
    fix = match['fixture']
    goals = match['goals']
    teams = match['teams']
    
    elapsed = fix['status']['elapsed']
    if elapsed is None: return None
    
    stats = get_stats(fix['id'])
    if not stats: return None

    s_h = stats['home']
    s_a = stats['away']
    g_h = goals['home'] or 0
    g_a = goals['away'] or 0
    
    # === VÝPOČTY (BOOKIE METRIKY) ===
    
    # 1. Intensity (Dangerous Attacks per Minute)
    da_min_h = round(s_h['da'] / elapsed, 2) if elapsed > 0 else 0
    da_min_a = round(s_a['da'] / elapsed, 2) if elapsed > 0 else 0
    
    # 2. xG Diff (Actual - Expected) -> Záporné číslo = Smůla (Měli dát gól)
    luck_h = round(g_h - s_h['xg'], 2)
    luck_a = round(g_a - s_a['xg'], 2)
    
    # 3. Shot Quality (xG/Shot)
    qual_h = round(s_h['xg'] / s_h['shots'], 2) if s_h['shots'] > 0 else 0
    qual_a = round(s_a['xg'] / s_a['shots'], 2) if s_a['shots'] > 0 else 0

    # === ALGORITMUS PREDIKCÍ ===
    tip = ""
    algo_color = ""
    
    # A. UNDER-DOG FIGHT (Brankář čaruje)
    if (s_h['saves'] >= 5 and g_a <= 1) or (s_a['saves'] >= 5 and g_h <= 1):
        tip = "🧱 ZÁMEK (GK Saves 5+)"
        algo_color = "🔴" # Riziko gólu vysoké

    # B. VALUE TRAP (Spousta střel, žádná kvalita)
    elif (s_h['shots'] > 12 and qual_h < 0.06 and g_h == 0):
        tip = "⚠️ JALOVÝ TLAK (Dom)"
        algo_color = "⚪" # Pozor na sázku
    elif (s_a['shots'] > 12 and qual_a < 0.06 and g_a == 0):
        tip = "⚠️ JALOVÝ TLAK (Host)"
        algo_color = "⚪"

    # C. HIGH xG VARIANCE (Gól musí padnout)
    elif (luck_h < -1.2) or (luck_a < -1.2):
        tip = "🔥 SMŮLA V KONCOVCE"
        algo_color = "🔥" # Value na gól

    # D. BUTCHER'S GAME (Hodně faulů)
    elif (s_h['fouls'] + s_a['fouls']) > 25:
        tip = "🥊 ŘEZNIČINA (Over Cards)"
        algo_color = "🟨"

    # E. INTENSITY OVERLOAD (Oba týmy útočí)
    elif da_min_h > 1.0 and da_min_a > 1.0:
        tip = "⚡ OTEVŘENÁ PARTIE"
        algo_color = "⚡"

    # FORMÁTOVÁNÍ TABULKY (Husté zobrazení dat)
    return {
        "Status": f"{elapsed}'",
        "Zápas": f"{teams['home']['name']} vs {teams['away']['name']}",
        "Skóre": f"<b>{g_h}:{g_a}</b>",
        "PREDIKCE": f"{algo_color} {tip}" if tip else "",
        
        # --- SEKCE ÚTOK ---
        "xG (Luck)": f"{s_h['xg']} ({luck_h}) / {s_a['xg']} ({luck_a})",
        "Střely (Box)": f"{s_h['shots']}({s_h['sib']}) / {s_a['shots']}({s_a['sib']})",
        "Kvalita (xG/S)": f"{qual_h} / {qual_a}",
        "Bloky": f"{s_h['blocked']} / {s_a['blocked']}",
        
        # --- SEKCE INTENZITA ---
        "DA/min": f"{da_min_h} / {da_min_a}",
        "Rohy": f"{s_h['corners']} / {s_a['corners']}",
        "Saves (GK)": f"{s_h['saves']} / {s_a['saves']}",
        
        # --- SEKCE DISCIPLÍNA & KONTROLA ---
        "Fauly": f"{s_h['fouls']} / {s_a['fouls']}",
        "Karty (Ž/Č)": f"{s_h['yc']}+{s_h['rc']} / {s_a['yc']}+{s_a['rc']}",
        "Poss %": f"{s_h['poss']}% / {s_a['poss']}%"
    }

# ================= FRONTEND =================
st.set_page_config(page_title="PRO BOOKIE DASHBOARD", layout="wide")

# CSS pro zhutnění tabulky (aby se tam vešlo 12 sloupců)
st.markdown("""
<style>
    div[data-testid="stDataFrame"] {font-size: 0.8rem;}
    th {text-align: center !important;}
    td {text-align: center !important;}
</style>
""", unsafe_allow_html=True)

st.sidebar.header("⚙️ Konfigurace")
sel_league = st.sidebar.selectbox("Liga", list(LEAGUES.keys()))
sel_id = LEAGUES[sel_league]
min_min = st.sidebar.slider("Filtrovat minutu (od):", 0, 90, 10)

st.title("📊 PRO BOOKIE DASHBOARD (14 Metrik)")
st.caption("Detailní analýza trhu. Hledáme neefektivitu kurzů.")

if st.button("🚀 SKENOVAT TRH", type="primary"):
    with st.spinner(f'Stahuji data pro {sel_league}...'):
        matches = get_live_matches(sel_id)
        # Filtr na minutu
        matches = [m for m in matches if m['fixture']['status']['elapsed'] >= min_min]
        
        if not matches:
            st.warning("Žádné aktivní zápasy splňující podmínky.")
        else:
            data = []
            bar = st.progress(0)
            for i, m in enumerate(matches):
                res = analyze_match(m)
                if res: data.append(res)
                bar.progress((i + 1) / len(matches))
            bar.empty()
            
            if data:
                df = pd.DataFrame(data)
                
                # Logika barvení řádků
                def highlight_algo(val):
                    if '🔥' in str(val): return 'background-color: #ffcccc; color: black; font-weight: bold;'
                    if '🧱' in str(val): return 'background-color: #e6f7ff; color: black;'
                    if '⚠️' in str(val): return 'background-color: #fff4cc; color: #444;'
                    if '⚡' in str(val): return 'background-color: #f0f0f0; color: black;'
                    if '🥊' in str(val): return 'background-color: #ffe6e6; color: black;'
                    return ''

                st.write(df.style.applymap(highlight_algo, subset=['PREDIKCE']).to_html(escape=False), unsafe_allow_html=True)
            else:
                st.info("Zápasy běží, ale API zatím nedodalo statistiky (obvykle zpoždění 2-3 minuty od výkopu).")
