"""
MLB Edge Backend Server
- Hakee Pinnacle-kertoimet automaattisesti
- Hakee MLB tulokset pelin jälkeen
- Tallentaa kaiken SQLite-tietokantaan
- Tarjoaa REST API mobiilisivulle
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import requests
import schedule
import threading
import time
import json
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)
CORS(app)  # Sallii mobiilisivun hakea dataa

ODDS_API_KEY = '7fa8ca447db0c0c4be1a38719aec7486'
FINLAND_TZ = pytz.timezone('Europe/Helsinki')
DB_PATH = 'mlb_data.db'

# ── TIETOKANTA ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS games (
        id TEXT PRIMARY KEY,
        date TEXT,
        commence TEXT,
        home_team TEXT,
        away_team TEXT,
        home_id INTEGER,
        away_id INTEGER,
        open_home REAL,
        open_away REAL,
        open_time TEXT,
        close_home REAL,
        close_away REAL,
        close_time TEXT,
        model_p_home REAL,
        model_p_away REAL,
        result TEXT,
        home_score INTEGER,
        away_score INTEGER,
        updated TEXT
    )''')
    conn.commit()
    conn.close()
    print("Tietokanta alustettu ✓")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── TEAM MAP ───────────────────────────────────────────
TEAM_MAP = {
    'New York Yankees': 147, 'Yankees': 147,
    'Boston Red Sox': 111, 'Red Sox': 111,
    'Toronto Blue Jays': 141, 'Blue Jays': 141,
    'Baltimore Orioles': 110, 'Orioles': 110,
    'Tampa Bay Rays': 139, 'Rays': 139,
    'Cleveland Guardians': 114, 'Guardians': 114,
    'Detroit Tigers': 116, 'Tigers': 116,
    'Kansas City Royals': 118, 'Royals': 118,
    'Minnesota Twins': 142, 'Twins': 142,
    'Chicago White Sox': 145, 'White Sox': 145,
    'Houston Astros': 117, 'Astros': 117,
    'Los Angeles Angels': 108, 'Angels': 108,
    'Oakland Athletics': 133, 'Athletics': 133,
    'Seattle Mariners': 136, 'Mariners': 136,
    'Texas Rangers': 140, 'Rangers': 140,
    'Atlanta Braves': 144, 'Braves': 144,
    'Miami Marlins': 146, 'Marlins': 146,
    'New York Mets': 121, 'Mets': 121,
    'Philadelphia Phillies': 143, 'Phillies': 143,
    'Washington Nationals': 120, 'Nationals': 120,
    'Chicago Cubs': 112, 'Cubs': 112,
    'Cincinnati Reds': 113, 'Reds': 113,
    'Milwaukee Brewers': 158, 'Brewers': 158,
    'Pittsburgh Pirates': 134, 'Pirates': 134,
    'St. Louis Cardinals': 138, 'Cardinals': 138,
    'Arizona Diamondbacks': 109, 'Diamondbacks': 109,
    'Colorado Rockies': 115, 'Rockies': 115,
    'Los Angeles Dodgers': 119, 'Dodgers': 119,
    'San Diego Padres': 135, 'Padres': 135,
    'San Francisco Giants': 137, 'Giants': 137,
}

def find_team_id(name):
    if not name:
        return None
    if name in TEAM_MAP:
        return TEAM_MAP[name]
    for k, v in TEAM_MAP.items():
        if name in k or k in name:
            return v
    return None

# ── ODDS FETCH ─────────────────────────────────────────
def fetch_odds():
    print(f"[{datetime.now().strftime('%H:%M')}] Haetaan Pinnacle-kertoimet...")
    try:
        url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'eu',
            'markets': 'h2h',
            'bookmakers': 'pinnacle',
            'oddsFormat': 'decimal'
        }
        resp = requests.get(url, params=params, timeout=30)
        remaining = resp.headers.get('x-requests-remaining', '?')
        
        if not resp.ok:
            print(f"  Virhe: {resp.status_code}")
            return
        
        games = resp.json()
        conn = get_db()
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        new_count = 0
        upd_count = 0

        for g in games:
            pk = g['id']
            date = g['commence_time'][:10]
            commence = g['commence_time']

            pinn = next((b for b in g.get('bookmakers', []) if b['key'] == 'pinnacle'), None)
            if not pinn:
                continue

            h2h = next((m for m in pinn.get('markets', []) if m['key'] == 'h2h'), None)
            if not h2h:
                continue

            ho = next((o for o in h2h.get('outcomes', []) if o['name'] == g['home_team']), None)
            ao = next((o for o in h2h.get('outcomes', []) if o['name'] == g['away_team']), None)
            if not ho or not ao:
                continue

            home_id = find_team_id(g['home_team'])
            away_id = find_team_id(g['away_team'])

            # Tarkista onko peli alkanut
            game_time = datetime.fromisoformat(commence.replace('Z', '+00:00'))
            is_started = datetime.now(pytz.utc) >= game_time

            existing = c.execute('SELECT id, open_home FROM games WHERE id=?', (pk,)).fetchone()

            if not existing:
                c.execute('''INSERT INTO games 
                    (id, date, commence, home_team, away_team, home_id, away_id,
                     open_home, open_away, open_time, updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (pk, date, commence, g['home_team'], g['away_team'],
                     home_id, away_id, ho['price'], ao['price'], now, now))
                new_count += 1
            elif not is_started:
                # Päivitä sulkeutumiskerroin vain ennen pelin alkua
                c.execute('''UPDATE games SET 
                    close_home=?, close_away=?, close_time=?, updated=?
                    WHERE id=?''',
                    (ho['price'], ao['price'], now, now, pk))
                upd_count += 1

        conn.commit()
        conn.close()
        print(f"  ✓ {new_count} uutta, {upd_count} päivitetty. API jäljellä: {remaining}")

    except Exception as e:
        print(f"  Virhe: {e}")

# ── RESULTS FETCH ──────────────────────────────────────
def fetch_results():
    print(f"[{datetime.now().strftime('%H:%M')}] Haetaan tulokset...")
    conn = get_db()
    c = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    pending = c.execute(
        'SELECT id, home_id, date FROM games WHERE result IS NULL AND date IN (?,?)',
        (today, yesterday)
    ).fetchall()

    updated = 0
    for game in pending:
        try:
            url = f"https://statsapi.mlb.com/api/v1/schedule"
            params = {
                'sportId': 1,
                'teamId': game['home_id'],
                'date': game['date'],
                'gameType': 'R'
            }
            resp = requests.get(url, params=params, timeout=15)
            if not resp.ok:
                continue
            
            data = resp.json()
            for date_obj in data.get('dates', []):
                for gm in date_obj.get('games', []):
                    if gm.get('status', {}).get('abstractGameState') == 'Final':
                        h_score = gm['teams']['home'].get('score', 0)
                        a_score = gm['teams']['away'].get('score', 0)
                        result = 'home' if h_score > a_score else 'away'
                        
                        c.execute('''UPDATE games SET 
                            result=?, home_score=?, away_score=?, updated=?
                            WHERE id=?''',
                            (result, h_score, a_score, 
                             datetime.utcnow().isoformat(), game['id']))
                        updated += 1

        except Exception as e:
            print(f"  Virhe pelille {game['id']}: {e}")

    conn.commit()
    conn.close()
    if updated:
        print(f"  ✓ {updated} tulosta päivitetty")
    else:
        print(f"  Ei uusia tuloksia ({len(pending)} odottaa)")

# ── API ENDPOINTS ──────────────────────────────────────
@app.route('/api/games', methods=['GET'])
def get_games():
    """Hae tulevan päivän ja tämän päivän pelit"""
    conn = get_db()
    c = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    games = c.execute(
        'SELECT * FROM games WHERE date IN (?,?) ORDER BY commence',
        (today, tomorrow)
    ).fetchall()
    
    conn.close()
    return jsonify([dict(g) for g in games])

@app.route('/api/results', methods=['GET'])
def get_results():
    """Hae kaikki menneet pelit tuloksineen"""
    conn = get_db()
    c = conn.cursor()
    
    games = c.execute(
        'SELECT * FROM games WHERE result IS NOT NULL ORDER BY date DESC LIMIT 100'
    ).fetchall()
    
    conn.close()
    return jsonify([dict(g) for g in games])

@app.route('/api/all', methods=['GET'])
def get_all():
    """Hae kaikki pelit (tulemat + menneet)"""
    conn = get_db()
    c = conn.cursor()
    
    games = c.execute(
        'SELECT * FROM games ORDER BY date DESC LIMIT 200'
    ).fetchall()
    
    conn.close()
    return jsonify([dict(g) for g in games])

@app.route('/api/status', methods=['GET'])
def get_status():
    """Palvelimen tila"""
    conn = get_db()
    c = conn.cursor()
    total = c.execute('SELECT COUNT(*) FROM games').fetchone()[0]
    with_result = c.execute('SELECT COUNT(*) FROM games WHERE result IS NOT NULL').fetchone()[0]
    conn.close()
    
    return jsonify({
        'status': 'ok',
        'total_games': total,
        'with_results': with_result,
        'server_time': datetime.now(FINLAND_TZ).strftime('%H:%M FIN'),
        'next_fetch': get_next_fetch_time()
    })

@app.route('/api/fetch', methods=['POST'])
def manual_fetch():
    """Manuaalinen haku"""
    fetch_odds()
    fetch_results()
    return jsonify({'status': 'ok', 'message': 'Haku suoritettu'})

def get_next_fetch_time():
    """Laske seuraava automaattinen hakuaika"""
    now = datetime.now(FINLAND_TZ)
    h = now.hour
    targets = [10, 19, 2]
    for t in targets:
        if h < t:
            return f"klo {t:02d}:00 FIN"
    return "klo 02:00 FIN (huomenna)"

# ── AJASTUS ────────────────────────────────────────────
def setup_schedule():
    """Ajasta automaattiset haut"""
    # Avauskertoimet
    schedule.every().day.at("10:00").do(fetch_odds)
    # Sulkeutumiskertoimet itärannikko
    schedule.every().day.at("19:00").do(fetch_odds)
    # Sulkeutumiskertoimet länsirannikko
    schedule.every().day.at("02:00").do(fetch_odds)
    # Tulokset 15min välein yöllä
    schedule.every(15).minutes.do(fetch_results)
    
    print("Ajastus asetettu:")
    print("  Kertoimet: klo 10:00, 19:00, 02:00 (FIN)")
    print("  Tulokset: 15min välein")

def run_scheduler():
    """Pyöritä ajastinta taustalla"""
    while True:
        schedule.run_pending()
        time.sleep(60)

# ── KÄYNNISTYS ─────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    setup_schedule()
    
    # Hae heti käynnistyessä
    print("Haetaan aloitusdata...")
    fetch_odds()
    fetch_results()
    
    # Käynnistä ajastin taustalle
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    print("\nServeri käynnissä portissa 5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
