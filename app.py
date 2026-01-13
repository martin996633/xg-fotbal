import streamlit as st
import requests
import pandas as pd
import time

# --- CONFIGURATION & API SETUP ---
API_KEY = "TVŮJ_RAPIDAPI_KLÍČ"  # Nahraď svým klíčem
BASE_URL = "https://api-football-beta.p.rapidapi.com"
HEADERS = {
    "X-RapidAPI-Key": API_KEY,
    "X-RapidAPI-Host": "api-football-beta.p.rapidapi.com"
}

class LiveMatchData:
    def __init__(self, api_key):
        self.headers = HEADERS

    def fetch_live_matches(self):
        """Získá zápasy, které jsou aktuálně v poločase (HT)."""
        url = f"{BASE_URL}/fixtures"
        querystring = {"live": "all"} # V produkci lze filtrovat konkrétní ligy
        response = requests.get(url, headers=self.headers, params=querystring)
        
        if response.status_code == 200:
            data = response.json().get('response', [])
            # Filtrace pouze na poločas (HT)
            ht_matches = [m for m in data if m['fixture']['status']['short'] == 'HT']
            return ht_matches
        return []

    def fetch_stats(self, fixture_id):
        url = f"{BASE_URL}/fixtures/statistics"
        response = requests.get(url, headers=self.headers, params={"fixture": fixture_id})
        return response.json().get('response', []) if response.status_code == 200 else []

    def fetch_events(self, fixture_id):
        url = f"{BASE_URL}/fixtures/events"
        response = requests.get(url, headers=self.headers, params={"fixture": fixture_id})
        return response.json().get('response', []) if response.status_code == 200 else []

# --- ANALYTICAL ENGINE ---
def calculate_proxy_xg(stats, events_list):
    W_PENALTY = 0.79
    W_SHOT_INSIDE = 0.13
    W_SHOT_OUTSIDE = 0.03
    W_SHOT_ON_TARGET_BONUS = 0.15
    
    # Bezpečné parsování statistik (ošetření null hodnot)
    s = {item['type']: item['value'] if item['value'] is not None else 0 for item in stats}
    
    # Pomocné extrakce
    sib = s.get('Shots insidebox', 0)
    sob = s.get('Shots outsidebox', 0)
    sog = s.get('Shots on Goal', 0)
    
    # Penalty count z eventů
    penalties = sum(1 for e in events_list if e.get('type') == 'Penalty')
    
    raw_xg = (sib * W_SHOT_INSIDE) + (sob * W_SHOT_OUTSIDE)
    accuracy_bonus = sog * W_SHOT_ON_TARGET_BONUS
    penalty_xg = penalties * W_PENALTY
    
    return round(raw_xg + accuracy_bonus + penalty_xg, 2)

def calculate_pressure_index(stats):
    s = {item['type']: (item['value'] if item['value'] is not None else 0) for item in stats}
    
    # Ošetření držení míče (string "55%" -> float 0.55)
    possession_str = str(s.get('Ball Possession', '50%')).replace('%', '')
    possession = float(possession_str) / 100
    pos_diff = (possession * 100) - 50
    
    # Pokud API neposkytuje Dangerous Attacks, použijeme náhradní metriku (Total Shots + Corners)
    da = s.get('Dangerous Attacks', 0)
    corners = s.get('Corner Kicks', 0)
    sog = s.get('Shots on Goal', 0)
    
    pi = (da * 1.0) + (corners * 3.0) + (sog * 5.0) + (pos_diff * 0.5)
    return round(pi, 2)

def predict_final_goals(home_xg, away_xg, home_pi, away_pi, score_home, score_away, has_red_card):
    lambda_prior = 1.35  # Standard league avg for 2H
    
    # 3.2 Live Performance Likelihood
    lambda_live_home = (home_xg * 1.1) + (home_pi / 100)
    lambda_live_away = (away_xg * 1.1) + (away_pi / 100)
    
    # 3.3 Game State Multipliers
    m_h, m_a = 1.0, 1.0
    diff = score_home - score_away
    
    if score_home == 0 and score_away == 0:
        m_h, m_a = 1.10, 1.10
    elif diff == -1: # Home losing by 1
        m_h, m_a = 1.35, 0.90
    elif abs(diff) >= 3: # Blowout
        m_h, m_a = 0.60, 0.60
    
    if has_red_card: # Zjednodušeně pro celý tým
        m_h *= 0.7 
        
    # 3.4 Final Calculation (Bayesian Fusion)
    home_exp = ((lambda_prior * 0.3) + (lambda_live_home * 0.7)) * m_h
    away_exp = ((lambda_prior * 0.3) + (lambda_live_away * 0.7)) * m_a
    
    return round(home_exp + away_exp, 2)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Pro-Bet 2H Engine", layout="wide")
st.title("⚽ Live Football Goal Prediction Engine (HT Strategy)")
st.write("Analyzuje probíhající zápasy v poločase a predikuje počet gólů ve 2. polovině.")

if st.button('Refresh Live Data'):
    engine = LiveMatchData(API_KEY)
    with st.spinner('Stahuji data z API...'):
        matches = engine.fetch_live_matches()
        
        if not matches:
            st.warning("Aktuálně nejsou žádné zápasy v poločase (HT).")
        else:
            results = []
            for match in matches:
                f_id = match['fixture']['id']
                home_name = match['teams']['home']['name']
                away_name = match['teams']['away']['name']
                score_h = match['score']['halftime']['home']
                score_a = match['score']['halftime']['away']
                
                # Fetch Stats & Events
                stats_data = engine.fetch_stats(f_id)
                events_data = engine.fetch_events(f_id)
                
                if len(stats_data) < 2: continue # Přeskočit pokud nejsou statistiky
                
                # Předpokládáme index 0 = Home, 1 = Away (nutno ověřit v API odpovědi)
                h_stats = stats_data[0]['statistics']
                a_stats = stats_data[1]['statistics']
                
                # Výpočty
                h_xg = calculate_proxy_xg(h_stats, events_data)
                a_xg = calculate_proxy_xg(a_stats, events_data)
                h_pi = calculate_pressure_index(h_stats)
                a_pi = calculate_pressure_index(a_stats)
                
                has_red = any(e['type'] == 'Card' and 'Red' in e['detail'] for e in events_data)
                
                exp_2h = predict_final_goals(h_xg, a_xg, h_pi, a_pi, score_h, score_a, has_red)
                
                # Signalizační logika
                signal = "NO SIGNAL"
                total_pi = h_pi + a_pi
                total_xg = h_xg + a_xg
                
                if score_h == 0 and score_a == 0 and total_pi > 80 and total_xg > 1.5:
                    signal = "🔥 OVER 0.5 GOALS (2H)"
                elif (score_h < score_a) and (h_pi > a_pi * 2):
                    signal = "⭐ LATE GOAL FAVORITE (HOME)"
                elif (h_pi + a_pi < 40) and (h_xg + a_xg < 0.5):
                    signal = "❄️ DEAD GAME (UNDER)"

                results.append({
                    "Match": f"{home_name} vs {away_name}",
                    "HT Score": f"{score_h}-{score_a}",
                    "Home xG": h_xg,
                    "Away xG": a_xg,
                    "Total PI": total_pi,
                    "Exp. 2H Goals": exp_2h,
                    "Signal": signal
                })

            df = pd.DataFrame(results)
            st.table(df)

st.sidebar.info("Tento systém používá Bayesian Poisson model kombinovaný s Pressure Indexem (PI) pro live trading.")
