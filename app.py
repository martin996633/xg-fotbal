import streamlit as st
import requests
import pandas as pd

# ================= 1. KONFIGURACE A API =================
# Zkusi načíst klíč ze secrets, jinak použije natvrdo vložený
try:
    API_KEY = st.secrets["API_KEY"]
except FileNotFoundError:
    # 👇👇👇 ZDE VLOŽ SVŮJ API KLÍČ 👇👇👇
    API_KEY = "VÁŠ_API_KLÍČ_ZDE" 

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io",
    'x-rapidapi-key': API_KEY
}

# Definice lig
LEAGUES = {
    "⚡ TOP 5 MIX (Vše najednou)": "top5",
    "🇬🇧 Premier League": 39,
    "🇪🇸 La Liga": 140,
    "🇩🇪 Bundesliga": 78,
    "🇮🇹 Serie A": 135,
    "🇫🇷 Ligue 1": 61
}
TOP5_IDS = [39, 140, 78, 135, 61]

# ================= 2. STAHOVÁNÍ DAT =================

def get_live_matches(league_selection):
    """Stáhne live zápasy a vyfiltruje top 5 lig."""
    try:
        url = f"{BASE_URL}/fixtures?live=all"
        if league_selection != "top5":
            url = f"{BASE_URL}/fixtures?live={league_selection}"
        
        response = requests.get(url, headers=HEADERS)
        matches = response.json().get('response', [])
        
        # Filtr jen na TOP 5 lig, pokud je vybrán MIX
        if league_selection == "top5":
            matches = [m for m in matches if m['league']['id'] in TOP5_IDS]
        return matches
    except Exception as e:
        st.error(f"Chyba při stahování zápasů: {e}")
        return []

def get_stats(fixture_id):
    """Stáhne detailní statistiky pro konkrétní zápas."""
    url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        data = response.json().get('response', [])
        
        # Inicializace struktury (aby se nestalo, že chybí klíč)
        stats = {
            'home': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'blocked': 0, 'da': 0, 'corners': 0, 'poss': 50, 'saves': 0, 'fouls': 0, 'yc': 0, 'rc': 0},
            'away': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'blocked': 0, 'da': 0, 'corners': 0, 'poss': 50, 'saves': 0, 'fouls': 0, 'yc': 0, 'rc': 0}
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
            
        return stats
    except:
        return None

# ================= 3. ANALÝZA A LOGIKA BOOKMAKERA =================

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
    
    # --- VÝPOČTY POKROČILÝCH METRIK ---
    
    # 1. DA/min (Intenzita nebezpečných útoků)
    da_min_h = round(s_h['da'] / elapsed, 2) if elapsed > 0 else 0
    da_min_a = round(s_a['da'] / elapsed, 2) if elapsed > 0 else 0
    
    # 2. Luck Factor (Rozdíl mezi Góly a xG) - Záporné číslo = Tým měl dát gól, ale nedal
    luck_h = round(g_h - s_h['xg'], 2)
    luck_a = round(g_a - s_a['xg'], 2)
    
    # 3. Shot Quality (xG na jednu střelu)
    qual_h = round(s_h['xg'] / s_h['shots'], 2) if s_h['shots'] > 0 else 0
    qual_a = round(s_a['xg'] / s_a['shots'], 2) if s_a['shots'] > 0 else 0

    # --- ALGORITMUS PREDIKCÍ (Hledání anomálií) ---
    tip = ""
    algo_color = ""
    strength = 0 # Pro řazení tabulky

    # A. BRANKÁŘ V OHNI (Underdog se drží zuby nehty)
    if (s_h['saves'] >= 5 and g_a <= 1) or (s_a['saves'] >= 5 and g_h <= 1):
        tip = "🧱 ZÁMEK (GK v ohni)"
        algo_color = "🔴" # Červená = Vysoké riziko gólu
        strength = 3

    # B. FALEŠNÁ DOMINANCE (Hodně střel, ale z dálky - Past na sázkaře)
    elif (s_h['shots'] > 12 and qual_h < 0.05 and g_h == 0):
        tip = "⚠️ JALOVÝ TLAK (Dom)"
        algo_color = "⚪" # Šedá/Bílá = Pozor, neznamená to gól
        strength = 2
    elif (s_a['shots'] > 12 and qual_a < 0.05 and g_a == 0):
        tip = "⚠️ JALOVÝ TLAK (Host)"
        algo_color = "⚪"
        strength = 2

    # C. EXTRÉMNÍ SMŮLA (Vysoké xG, žádné góly - Gól visí)
    elif (luck_h < -1.2) or (luck_a < -1.2):
        tip = "🔥 SMŮLA V KONCOVCE"
        algo_color = "🔥" 
        strength = 3

    # D. OTEVŘENÁ PARTIE (Oba týmy útočí ve vlnách)
    elif da_min_h > 1.0 and da_min_a > 1.0 and (s_h['sot'] + s_a['sot'] > 8):
        tip = "⚡ SHOOTOUT (Nahoru-Dolů)"
        algo_color = "⚡"
        strength = 1

    # --- FORMÁTOVÁNÍ PRO HTML TABULKU ---
    
    # Formátování střel na bránu (Tučně pokud je tlak)
    sot_h_disp = f"<b>{s_h['sot']}</b>" if s_h['sot'] >= 6 else f"{s_h['sot']}"
    sot_a_disp = f"<b>{s_a['sot']}</b>" if s_a['sot'] >= 6 else f"{s_a['sot']}"
    
    # Formátování střel celkem + (vápno)
    shots_h_disp = f"{s_h['shots']} <span style='color:grey; font-size:0.8em'>({s_h['sib']})</span>"
    shots_a_disp = f"{s_a['shots']} <span style='color:grey; font-size:0.8em'>({s_a['sib']})</span>"
    
    # Formátování barvy xG Luck (Červená pro smůlu)
    luck_h_fmt = f"<span style='color:red'>{luck_h}</span>" if luck_h < -0.8 else f"{luck_h}"
    luck_a_fmt = f"<span style='color:red'>{luck_a}</span>" if luck_a < -0.8 else f"{luck_a}"

    return {
        "strength": strength, # Skrytý sloupec pro řazení
        "Min": f"{elapsed}'",
        "Zápas": f"{teams['home']['name']} vs {teams['away']['name']}",
        "Skóre": f"<b>{g_h}:{g_a}</b>",
        "PREDIKCE": f"{algo_color} {tip}" if tip else "",
        
        # Sekce STŘELY (Nový layout)
        "🎯 Na bránu": f"{sot_h_disp} - {sot_a_disp}", 
        "💥 Celkem (Box)": f"{shots_h_disp} vs {shots_a_disp}",
        
        # Sekce KVALITA
        "xG (Luck)": f"{s_h['xg']}({luck_h_fmt}) / {s_a['xg']}({luck_a_fmt})",
        "DA/min": f"{da_min_h} / {da_min_a}",
        
        # Sekce DEFENZIVA
        "Bloky": f"{s_h['blocked']} - {s_a['blocked']}",
        "Saves (GK)": f"{s_h['saves']} - {s_a['saves']}",
        "Fauly": f"{s_h['fouls']} - {s_a['fouls']}",
        "Karty": f"{s_h['yc']} / {s_a['yc']}"
    }

# ================= 4. FRONTEND (STREAMLIT) =================
st.set_page_config(page_title="PRO BOOKIE DASHBOARD", layout="wide")

# CSS úpravy pro zhutnění tabulky a lepší čitelnost
st.markdown("""
<style>
    .main {background-color: #f5f5f5;}
    table {font-size: 0.9rem !important;}
    th {background-color: #0e1117 !important; color: white !important; text-align: center !important;}
    td {text-align: center !important; vertical-align: middle !important;}
    tr:hover {background-color: #e6f7ff !important;}
</style>
""", unsafe_allow_html=True)

# Boční panel
st.sidebar.header("⚙️ Nastavení Dashboardu")
sel_league = st.sidebar.selectbox("Vyber ligu:", list(LEAGUES.keys()))
sel_id = LEAGUES[sel_league]
min_min = st.sidebar.slider("Minuta zápasu (od):", 0, 90, 15)

# Hlavní hlavička
st.title("📊 PRO BOOKIE DASHBOARD v4.2")
st.markdown("""
**Legenda pro sázkaře:**
* **🎯 Na bránu:** Pokud je číslo **tučné**, tým má velký tlak (>6 střel na bránu).
* **💥 Celkem (Box):** Číslo v závorce jsou střely z pokutového území (nejvyšší kvalita).
* **Luck (xG):** Záporné červené číslo (např. <span style='color:red'>-1.5</span>) znamená, že tým měl dát góly, ale má smůlu.
* **Jalový tlak:** Hodně střel, ale nízká kvalita (xG/shot). Pozor na sázky.
""", unsafe_allow_html=True)

# Tlačítko pro spuštění
if st.button("🚀 SKENOVAT TRH (LIVE)", type="primary"):
    with st.spinner(f'Analyzuji data pro {sel_league}...'):
        matches = get_live_matches(sel_id)
        
        # Filtr podle minuty
        matches = [m for m in matches if m['fixture']['status']['elapsed'] >= min_min]
        
        if not matches:
            st.warning("⚠️ Žádné aktivní zápasy splňující podmínky.")
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
                
                # Řazení: Nejdřív nejsilnější predikce, pak podle času
                df = df.sort_values(by=['strength', 'Min'], ascending=[False, False])
                # Odstraníme pomocný sloupec strength z vizuálu
                df = df.drop(columns=['strength'])
                
                # Barvení řádků podle typu predikce
                def highlight_rows(val):
                    if '🔥' in str(val): return 'background-color: #ffcccc; color: black;' # Smůla/Tlak
                    if '🧱' in str(val): return 'background-color: #e6f7ff; color: black;' # Zámek
                    if '⚡' in str(val): return 'background-color: #ffffcc; color: black;' # Přestřelka
                    if '⚠️' in str(val): return 'background-color: #f2f2f2; color: grey;' # Past
                    return ''

                # Vykreslení HTML tabulky (umožní bold text, barvy atd.)
                st.write(df.style.applymap(highlight_rows, subset=['PREDIKCE']).hide(axis="index").to_html(escape=False), unsafe_allow_html=True)
                
            else:
                st.info("ℹ️ Zápasy běží, ale API zatím nedodalo statistiky (čeká se na update dat).")
