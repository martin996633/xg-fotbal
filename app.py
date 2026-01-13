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

# ================= LOGIKA BOOKMAKERA =================

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
    except Exception:
        return []

def get_stats(fixture_id):
    url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        data = response.json().get('response', [])
        
        # Inicializace s nulami
        stats = {
            'home': {'xg': 0.0, 'shots': 0, 'sot': 0, 'da': 0, 'attacks': 0, 'corners': 0, 'poss': 50, 'saves': 0},
            'away': {'xg': 0.0, 'shots': 0, 'sot': 0, 'da': 0, 'attacks': 0, 'corners': 0, 'poss': 50, 'saves': 0}
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
            s['da'] = get_val('Dangerous Attacks') # Klíčová metrika
            s['attacks'] = get_val('Attacks')
            s['corners'] = get_val('Corner Kicks')
            s['poss'] = get_val('Ball Possession')
            s['saves'] = get_val('Goalkeeper Saves')
            
        return stats
    except:
        return None

def calculate_field_tilt(h_da, a_da):
    """Výpočet náklonu hřiště (Kdo ovládá nebezpečné zóny)"""
    total = h_da + a_da
    if total == 0: return 50
    return round((h_da / total) * 100, 1)

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
    
    # === VÝPOČTY PROFI METRIK ===
    
    # 1. Field Tilt (Kdo tlačí v nebezpečné zóně)
    home_tilt = calculate_field_tilt(s_h['da'], s_a['da'])
    
    # 2. Dangerous Attacks per Minute (Intenzita)
    da_per_min_h = round(s_h['da'] / elapsed, 2) if elapsed > 0 else 0
    da_per_min_a = round(s_a['da'] / elapsed, 2) if elapsed > 0 else 0
    
    # 3. xG Diff (Spravedlnost výsledku)
    xg_diff = (s_h['xg'] - g_h) + (s_a['xg'] - g_a) # Kladné = mělo padnout víc gólů
    
    # 4. Shot Quality (Průměrné xG na střelu)
    qual_h = round(s_h['xg'] / s_h['shots'], 2) if s_h['shots'] > 0 else 0
    qual_a = round(s_a['xg'] / s_a['shots'], 2) if s_a['shots'] > 0 else 0

    # === LOGIKA PREDICÍ (ALGORITMUS) ===
    tip = ""
    sub_tip = ""
    strength = 0
    
    # A. SCÉNÁŘ: TOTÁLNÍ OBLÉHÁNÍ (Late Game Siege)
    # Tým prohrává nebo remizuje, je konec zápasu a má obrovský Field Tilt
    if elapsed > 70 and (g_h <= g_a) and home_tilt > 75 and da_per_min_h > 1.2:
        tip = "💣 TOTAL SIEGE (Domácí)"
        sub_tip = "Extrémní Field Tilt + Tlak"
        strength = 3
    elif elapsed > 70 and (g_a <= g_h) and home_tilt < 25 and da_per_min_a > 1.2:
        tip = "💣 TOTAL SIEGE (Hosté)"
        sub_tip = "Extrémní Field Tilt + Tlak"
        strength = 3

    # B. SCÉNÁŘ: FALEŠNÁ DOMINANCE (Value Trap)
    # Tým má hodně střel, ale mizernou kvalitu. Trh sází Over, my jdeme Under/Remíza.
    elif (s_h['shots'] > 12 and g_h == 0 and qual_h < 0.05):
        tip = "⚠️ FALEŠNÁ DOMINANCE (Dom)"
        sub_tip = "Mnoho střel, nulová kvalita"
        strength = 2
    elif (s_a['shots'] > 12 and g_a == 0 and qual_a < 0.05):
        tip = "⚠️ FALEŠNÁ DOMINANCE (Host)"
        sub_tip = "Mnoho střel, nulová kvalita"
        strength = 2
        
    # C. SCÉNÁŘ: SMRTELNÝ BREJK (Counter Attack)
    # Tým nemá míč, ale má velké šance
    elif (s_a['poss'] < 35 and s_a['xg'] > 1.2 and g_a < 2):
        tip = "⚔️ SMRTELNÝ BREJK (Host)"
        sub_tip = "Málo míče, obří šance"
        strength = 3
        
    # D. SCÉNÁŘ: XG VALUE (Klasika)
    elif xg_diff > 1.6:
        tip = "💎 VALUE OVER"
        sub_tip = f"Chybí {round(xg_diff, 1)} gólu do spravedlnosti"
        strength = 2

    return {
        "strength": strength,
        "Min": f"{elapsed}'",
        "Zápas": f"{teams['home']['name']} vs {teams['away']['name']}",
        "Skóre": f"<b>{g_h}:{g_a}</b>",
        "Field Tilt": f"{home_tilt}% - {100-home_tilt}%",
        "DA/min": f"{da_per_min_h} - {da_per_min_a}",
        "xG (Kvalita)": f"{s_h['xg']} ({qual_h}) - {s_a['xg']} ({qual_a})",
        "PREDIKCE": tip,
        "Info": sub_tip
    }

# ================= FRONTEND =================
st.set_page_config(page_title="PRO Bookie Scanner v3", layout="wide")

st.sidebar.header("⚙️ Nastavení")
sel_league = st.sidebar.selectbox("Liga", list(LEAGUES.keys()))
sel_id = LEAGUES[sel_league]
min_min = st.sidebar.slider("Minuta zápasu od:", 0, 90, 20)

st.title("🧠 PRO Bookie Scanner v3.0")
st.markdown("""
<style>
.small-font {font-size:12px !important; color: grey;}
</style>
**Legenda:** * **Field Tilt:** Kdo ovládá území (nad 70% = drtivá převaha).
* **DA/min:** Počet nebezpečných útoků za minutu (nad 1.0 = vysoké tempo).
* **Falešná dominance:** Tým střílí, ale z dálky (nízké xG/střelu).
""", unsafe_allow_html=True)

if st.button("🔎 ANALYZOVAT JAKO BOOKMAKER", type="primary"):
    with st.spinner(f'Načítám live data a počítám Field Tilt...'):
        matches = get_live_matches(sel_id)
        matches = [m for m in matches if m['fixture']['status']['elapsed'] >= min_min]
        
        if not matches:
            st.warning("Žádné vhodné live zápasy.")
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
                df = df.sort_values(by=['strength', 'Min'], ascending=[False, False]).drop(columns=['strength'])
                
                # Stylování tabulky
                def style_df(val):
                    if '💣' in str(val): return 'background-color: #ffb3b3; color: black; font-weight: bold;' # Siege
                    if '⚔️' in str(val): return 'background-color: #ffffb3; color: black; font-weight: bold;' # Counter
                    if '⚠️' in str(val): return 'background-color: #e6e6e6; color: #555;' # Trap
                    if '💎' in str(val): return 'background-color: #b3ffb3; color: black; font-weight: bold;' # Value
                    return ''

                # HTML renderování pro tučné písmo ve skóre
                st.write(df.style.applymap(style_df, subset=['PREDIKCE']).to_html(escape=False), unsafe_allow_html=True)
            else:
                st.info("Data jsou dostupná, ale žádný zápas nesplňuje kritéria pro anomálii.")
