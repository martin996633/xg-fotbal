import streamlit as st
import requests
import pandas as pd
import numpy as np
from scipy.stats import poisson
import time

# ==============================================================================
# 1. KONFIGURACE A LIGOVÉ STANDARDY
# ==============================================================================
try:
    API_KEY = st.secrets["API_KEY"]
except:
    API_KEY = "VÁŠ_API_KLÍČ_ZDE" 

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {'x-rapidapi-host': "v3.football.api-sports.io", 'x-rapidapi-key': API_KEY}

# Průměrný počet gólů ve 2. poločase (Baseline Correlation)
LEAGUE_2H_AVGS = {
    39: 1.55, 140: 1.42, 78: 1.62, 135: 1.45, 61: 1.38, 0: 1.45
}

# Váhy pro xG Proxy
WEIGHTS = {'SOT': 0.35, 'SIB': 0.25, 'SOFF': 0.05, 'CORNERS': 0.10}

# ==============================================================================
# 2. DATA & QUANT ENGINE CLASSES
# ==============================================================================

class LiveMatchData:
    def __init__(self, api_key):
        self.headers = {'x-rapidapi-host': "v3.football.api-sports.io", 'x-rapidapi-key': api_key}
    
    def fetch_ht_fixtures(self):
        url = f"{BASE_URL}/fixtures?live=all"
        res = requests.get(url, headers=self.headers).json().get('response', [])
        return [m for m in res if m['fixture']['status']['short'] == 'HT']

    def fetch_stats(self, fid):
        res = requests.get(f"{BASE_URL}/fixtures/statistics?fixture={fid}", headers=self.headers).json().get('response', [])
        stats = {'home': self._zero(), 'away': self._zero()}
        if not res: return stats
        for i, side in enumerate(['home', 'away']):
            if i < len(res):
                r = {item['type']: item['value'] for item in res[i]['statistics']}
                s = stats[side]
                s.update({
                    'sot': self._i(r.get('Shots on Goal')), 'soff': self._i(r.get('Shots off Goal')),
                    'sib': self._i(r.get('Shots insidebox')), 'corners': self._i(r.get('Corner Kicks')),
                    'red': self._i(r.get('Red Cards')), 'poss': self._p(r.get('Ball Possession'))
                })
        return stats

    def _zero(self): return {'sot':0, 'soff':0, 'sib':0, 'corners':0, 'poss':0.5, 'red':0}
    def _i(self, v): return int(v) if v is not None else 0
    def _p(self, v): return float(str(v).replace('%',''))/100 if v else 0.5

class QuantEngine:
    @staticmethod
    def calculate_xg_proxy(s):
        xg = (s['sot']*WEIGHTS['SOT']) + (s['sib']*WEIGHTS['SIB']) + (s['soff']*WEIGHTS['SOFF']) + (s['corners']*WEIGHTS['CORNERS'])
        return xg * 1.1 if s['poss'] > 0.6 else xg

    @staticmethod
    def get_2h_projection(h_xg, a_xg, league_id, red_cards, current_goals):
        l_avg = LEAGUE_2H_AVGS.get(league_id, LEAGUE_2H_AVGS[0])
        match_intensity = h_xg + a_xg
        
        # Korelační model (Regression to the Mean)
        # 65% váha aktuální zápas, 35% váha průměr ligy
        lambda_2h = (match_intensity * 0.65) + (l_avg * 0.35)
        
        # Úpravy (červená karta, smůla v 1. poločase)
        if red_cards > 0: lambda_2h *= 1.25
        if current_goals == 0 and match_intensity > 1.5: lambda_2h += 0.4
        
        return round(lambda_2h, 2)

    @staticmethod
    def get_poisson_probs(lam):
        # Pravděpodobnost 1+ gólu: 1 - P(0)
        p1 = (1 - poisson.pmf(0, lam)) * 100
        # Pravděpodobnost 2+ gólů: 1 - (P(0) + P(1))
        p2 = (1 - (poisson.pmf(0, lam) + poisson.pmf(1, lam))) * 100
        return round(p1, 1), round(p2, 1)

# ==============================================================================
# 3. FRONTEND - DASHBOARD
# ==============================================================================

st.set_page_config(page_title="QUANT GOAL ENGINE v6.0", layout="wide")
st.title("🤖 Quant Football Engine (HT Strategy)")
st.markdown("---")

data_layer = LiveMatchData(API_KEY)
engine = QuantEngine()

if st.button("🚀 ANALYZOVAT POLOČASY", type="primary"):
    matches = data_layer.fetch_ht_fixtures()
    if not matches:
        st.info("Žádné zápasy právě nejsou v poločase (HT).")
    else:
        results = []
        bar = st.progress(0)
        for i, m in enumerate(matches):
            fid = m['fixture']['id']
            stats = data_layer.fetch_stats(fid)
            
            h_xg = engine.calculate_xg_proxy(stats['home'])
            a_xg = engine.calculate_xg_proxy(stats['away'])
            reds = stats['home']['red'] + stats['away']['red']
            curr_g = (m['goals']['home'] or 0) + (m['goals']['away'] or 0)
            
            lam = engine.get_2h_projection(h_xg, a_xg, m['league']['id'], reds, curr_g)
            p1, p2 = engine.get_poisson_probs(lam)
            
            # Signal Logic
            signal = "HOLD"
            if p1 > 80: signal = "🔥 OVER 0.5 (9/10)"
            elif p1 > 65: signal = "⚡ NEXT GOAL"
            elif p1 < 35: signal = "🧊 UNDER"

            results.append({
                "Zápas": f"{m['teams']['home']['name']} vs {m['teams']['away']['name']}",
                "Skóre": f"{m['goals']['home']}-{m['goals']['away']}",
                "HT xG Proxy": f"{round(h_xg,2)} - {round(a_xg,2)}",
                "Projected λ 2H": lam,
                "P(Over 0.5 2H)": f"{p1}%",
                "P(Over 1.5 2H)": f"{p2}%",
                "SIGNAL": signal,
                "Conf": p1
            })
            bar.progress((i+1)/len(matches))
        
        df = pd.DataFrame(results).sort_values(by="Conf", ascending=False).drop(columns="Conf")
        
        def color_signal(val):
            if '🔥' in str(val): return 'background-color: #ffcccc; font-weight: bold;'
            if '⚡' in str(val): return 'background-color: #fff4cc;'
            if '🧊' in str(val): return 'background-color: #e6f7ff; color: #555;'
            return ''

        st.dataframe(df.style.applymap(color_signal, subset=['SIGNAL']), use_container_width=True, hide_index=True)
