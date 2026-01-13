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

# Top ligy + Další zajímavé (Eredivisie, Portugal, Championship)
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
        
        # Inicializace prázdných statistik
        stats = {
            'home': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'corners': 0, 'poss': 50, 'saves': 0},
            'away': {'xg': 0.0, 'shots': 0, 'sot': 0, 'sib': 0, 'corners': 0, 'poss': 50, 'saves': 0}
        }
        
        if not data: return stats

        for i, team in enumerate(['home', 'away']):
            if i >= len(data): break
            t_stats = {item['type']: item['value'] for item in data[i]['statistics']}
            
            # Bezpečné načtení hodnot (API občas vrací None nebo stringy)
            def get_val(key, type_cast=int):
                val = t_stats.get(key)
                if val is None: return 0
                try: 
                    return type_cast(str(val).replace('%', ''))
                except: return 0

            stats[team]['xg'] = get_val('expected_goals', float)
            stats[team]['shots'] = get_val('Total Shots')
            stats[team]['sot'] = get_val('Shots on Goal')
            stats[team]['sib'] = get_val('Shots insidebox') # Střely z vápna
            stats[team]['corners'] = get_val('Corner Kicks')
            stats[team]['poss'] = get_val('Ball Possession')
            stats[team]['saves'] = get_val('Goalkeeper Saves')
            
        return stats
    except:
        return None

def calculate_pressure_index(s):
    """
    Vlastní metrika pro určení tlaku týmu.
    Váhy: xG (x10), Střely na bránu (x3), Střely z vápna (x2), Rohy (x1)
    """
    idx = (s['xg'] * 10) + (s['sot'] * 3) + (s['sib'] * 2) + s['corners']
    # Bonus za drtivé držení míče (>65%)
    if s['poss'] > 65: idx += 5
    return round(idx, 1)

def analyze_match(match):
    fix = match['fixture']
    goals = match['goals']
    teams = match['teams']
    
    # Stáhneme stats
    stats = get_stats(fix['id'])
    if not stats: return None # Pokud nejsou statistiky, přeskočíme

    s_home = stats['home']
    s_away = stats['away']
    
    # Skóre
    g_h = goals['home'] or 0
    g_a = goals['away'] or 0
    
    # Tlakové indexy
    p_home = calculate_pressure_index(s_home)
    p_away = calculate_pressure_index(s_away)
    
    # Rozdíl xG vs Góly (Underperformance)
    xg_diff_h = s_home['xg'] - g_h
    xg_diff_a = s_away['xg'] - g_a
    total_xg_diff = (s_home['xg'] + s_away['xg']) - (g_h + g_a)

    # === ALGORITMUS PREDIKCE (THE BRAIN) ===
    tip = ""
    tip_strength = 0 # 0 = nic, 1 = zajímavé, 2 = strong, 3 = BOMBA
    
    # 1. Scénář: "The Siege" (Jeden tým drtí druhého, ale nedal gól)
    # Podmínka: Tlak > 30, Střely z vápna > 5, gólů < 1
    if (p_home > 30 and g_h == 0) or (p_away > 30 and g_a == 0):
        tip = "🔥 GÓL VISÍ VE VZDUCHU (Tlak)"
        tip_strength = 3
    
    # 2. Scénář: "xG Underperformer" (Vytvořili si šance na 2 góly, dali 0)
    elif total_xg_diff > 1.3:
        tip = "⚡ OVER VALUE (xG)"
        tip_strength = 2
        
    # 3. Scénář: "Open Game" (Oba týmy střílí, brankáři čarují)
    elif (s_home['sot'] + s_away['sot']) >= 10 and (g_h + g_a) <= 1:
        tip = "⚽ OTEVŘENÝ ZÁPAS"
        tip_strength = 1
        
    # 4. Scénář: "Lucky Lead" (Vedou, ale soupeř je lepší)
    elif (g_h > g_a and p_away > p_home * 1.5) or (g_a > g_h and p_home > p_away * 1.5):
        tip = "⚠️ MOŽNÉ SROVNÁNÍ"
        tip_strength = 2

    return {
        "strength": tip_strength, # Pro řazení
        "Čas": f"{fix['status']['elapsed']}'",
        "Týmy": f"{teams['home']['name']}\n{teams['away']['name']}",
        "Skóre": f"{g_h}\n{g_a}",
        "xG": f"{s_home['xg']}\n{s_away['xg']}",
        "Tlak Index": f"{p_home}\n{p_away}",
        "Střely (Vápno)": f"{s_home['shots']}({s_home['sib']})\n{s_away['shots']}({s_away['sib']})",
        "Rohy": f"{s_home['corners']}\n{s_away['corners']}",
        "Držení %": f"{s_home['poss']}%\n{s_away['poss']}%",
        "Brankář": f"{s_home['saves']}\n{s_away['saves']}", # Zákroky
        "PREDIKCE": tip
    }

# ================= FRONTEND =================
st.set_page_config(page_title="PRO xG Scanner", layout="wide", page_icon="⚽")

# Sidebar - Filtry
st.sidebar.header("⚙️ Nastavení")
selected_league_name = st.sidebar.selectbox("Vyber ligu", list(LEAGUES.keys()))
selected_league_id = LEAGUES[selected_league_name]

only_ht = st.sidebar.checkbox("Jen Poločas (HT)", value=False)
min_pressure = st.sidebar.slider("Minimální Tlak Index", 0, 50, 0)

# Hlavní okno
st.title("⚽ PRO Live Scanner & Predictor")
st.markdown(f"**Liga:** {selected_league_name} | **Status:** Live")

if st.button("🔄 ANALYZOVAT TRH", type="primary"):
    with st.spinner('Stahuji data, počítám indexy tlaku...'):
        matches = get_live_matches(selected_league_id)
        
        # Filtrace HT
        if only_ht:
            matches = [m for m in matches if m['fixture']['status']['short'] == 'HT']
            
        if not matches:
            st.warning("Žádné zápasy neodpovídají filtrům.")
        else:
            data = []
            prog = st.progress(0)
            
            for i, m in enumerate(matches):
                res = analyze_match(m)
                if res:
                    # Filtrace podle tlaku (pokud uživatel chce jen high pressure)
                    p_h = float(res['Tlak Index'].split('\n')[0])
                    p_a = float(res['Tlak Index'].split('\n')[1])
                    if p_h >= min_pressure or p_a >= min_pressure:
                        data.append(res)
                prog.progress((i + 1) / len(matches))
            
            if data:
                # Seřadit podle síly tipu (nejlepší nahoře)
                df = pd.DataFrame(data)
                df = df.sort_values(by='strength', ascending=False).drop(columns=['strength'])
                
                # Stylování tabulky
                st.success(f"Nalezeno {len(df)} analyzovaných zápasů.")
                
                def highlight_rows(val):
                    if '🔥' in str(val): return 'background-color: #ffcccc; color: black; font-weight: bold;' # Červená
                    if '⚡' in str(val): return 'background-color: #fff4cc; color: black;' # Oranžová
                    if '⚠️' in str(val): return 'background-color: #e6f7ff; color: black;' # Modrá
                    return ''

                # Zobrazit tabulku s povoleným HTML (pro řádkování v buňkách)
                st.write(df.style.applymap(highlight_rows, subset=['PREDIKCE']).to_html().replace('\\n', '<br>'), unsafe_allow_html=True)
                st.caption("Legenda: Tlak Index = (xG*10 + Střely na bránu*3 + Střely z vápna*2 + Rohy). Nad 30 je extrém.")
            else:
                st.info("Zápasy běží, ale nemají dostupné detailní statistiky (nebo nesplňují min. tlak).")
