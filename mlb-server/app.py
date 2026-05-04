"""
MLB Edge Backend Server - yksinkertainen versio
"""

from flask import Flask, jsonify
from flask_cors import CORS
import sqlite3
import requests
import threading
import time
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

ODDS_API_KEY = '7fa8ca447db0c0c4be1a38719aec7486'
DB_PATH = 'mlb_data.db'

TEAM_MAP = {
    'New York Yankees':147,'Yankees':147,'Boston Red Sox':111,'Red Sox':111,
    'Toronto Blue Jays':141,'Blue Jays':141,'Baltimore Orioles':110,'Orioles':110,
    'Tampa Bay Rays':139,'Rays':139,'Cleveland Guardians':114,'Guardians':114,
    'Detroit Tigers':116,'Tigers':116,'Kansas City Royals':118,'Royals':118,
    'Minnesota Twins':142,'Twins':142,'Chicago White Sox':145,'White Sox':145,
    'Houston Astros':117,'Astros':117,'Los Angeles Angels':108,'Angels':108,
    'Oakland Athletics':133,'Athletics':133,'Seattle Mariners':136,'Mariners':136,
    'Texas Rangers':140,'Rangers':140,'Atlanta Braves':144,'Braves':144,
    'Miami Marlins':146,'Marlins':146,'New York Mets':121,'Mets':121,
    'Philadelphia Phillies':143,'Phillies':143,'Washington Nationals':120,'Nationals':120,
    'Chicago Cubs':112,'Cubs':112,'Cincinnati Reds':113,'Reds':113,
    'Milwaukee Brewers':158,'Brewers':158,'Pittsburgh Pirates':134,'Pirates':134,
    'St. Louis Cardinals':138,'Cardinals':138,'Arizona Diamondbacks':109,'Diamondbacks':109,
    'Colorado Rockies':115,'Rockies':115,'Los Angeles Dodgers':119,'Dodgers':119,
    'San Diego Padres':135,'Padres':135,'San Francisco Giants':137,'Giants':137,
}

def find_team_id(name):
    if not name: return None
    if name in TEAM_MAP: return TEAM_MAP[name]
    for k,v in TEAM_MAP.items():
        if name in k or k in name: return v
    return None

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS games (
        id TEXT PRIMARY KEY, date TEXT, commence TEXT,
        home_team TEXT, away_team TEXT, home_id INTEGER, away_id INTEGER,
        open_home REAL, open_away REAL, open_time TEXT,
        close_home REAL, close_away REAL, close_time TEXT,
        model_p_home REAL, model_p_away REAL,
        result TEXT, home_score INTEGER, away_score INTEGER
    )''')
    conn.commit()
    conn.close()

def fetch_odds():
    print(f"[{datetime.now().strftime('%H:%M')}] Haetaan kertoimet...")
    try:
        r = requests.get(
            'https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/',
            params={'apiKey':ODDS_API_KEY,'regions':'eu','markets':'h2h',
                   'bookmakers':'pinnacle','oddsFormat':'decimal'},
            timeout=30
        )
        if not r.ok:
            print(f"  API virhe: {r.status_code}")
            return
        
        games = r.json()
        remaining = r.headers.get('x-requests-remaining','?')
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        new_n = upd_n = 0

        for g in games:
            pk = g['id']
            pinn = next((b for b in g.get('bookmakers',[]) if b['key']=='pinnacle'), None)
            if not pinn: continue
            h2h = next((m for m in pinn.get('markets',[]) if m['key']=='h2h'), None)
            if not h2h: continue
            ho = next((o for o in h2h.get('outcomes',[]) if o['name']==g['home_team']), None)
            ao = next((o for o in h2h.get('outcomes',[]) if o['name']==g['away_team']), None)
            if not ho or not ao: continue

            game_time = datetime.fromisoformat(g['commence_time'].replace('Z','+00:00'))
            is_started = datetime.now().astimezone() >= game_time

            exists = c.execute('SELECT id FROM games WHERE id=?',(pk,)).fetchone()
            if not exists:
                c.execute('''INSERT INTO games 
                    (id,date,commence,home_team,away_team,home_id,away_id,
                     open_home,open_away,open_time)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (pk, g['commence_time'][:10], g['commence_time'],
                     g['home_team'], g['away_team'],
                     find_team_id(g['home_team']), find_team_id(g['away_team']),
                     ho['price'], ao['price'], now))
                new_n += 1
            elif not is_started:
                c.execute('UPDATE games SET close_home=?,close_away=?,close_time=? WHERE id=?',
                    (ho['price'], ao['price'], now, pk))
                upd_n += 1

        conn.commit()
        conn.close()
        print(f"  ✓ {new_n} uutta, {upd_n} päivitetty. API jäljellä: {remaining}")
    except Exception as e:
        print(f"  Virhe: {e}")

def fetch_results():
    print(f"[{datetime.now().strftime('%H:%M')}] Haetaan tulokset...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d')
    pending = c.execute(
        'SELECT id,home_id,date FROM games WHERE result IS NULL AND date IN (?,?)',
        (today,yesterday)
    ).fetchall()
    updated = 0
    for game in pending:
        try:
            r = requests.get(
                'https://statsapi.mlb.com/api/v1/schedule',
                params={'sportId':1,'teamId':game['home_id'],'date':game['date'],'gameType':'R'},
                timeout=15
            )
            if not r.ok: continue
            for dt in r.json().get('dates',[]):
                for gm in dt.get('games',[]):
                    if gm.get('status',{}).get('abstractGameState')=='Final':
                        hs = gm['teams']['home'].get('score',0)
                        as_ = gm['teams']['away'].get('score',0)
                        c.execute('UPDATE games SET result=?,home_score=?,away_score=? WHERE id=?',
                            ('home' if hs>as_ else 'away', hs, as_, game['id']))
                        updated += 1
        except: pass
    conn.commit()
    conn.close()
    print(f"  ✓ {updated} tulosta päivitetty")

def scheduler():
    last_odds = 0
    last_results = 0
    while True:
        now = datetime.now()
        h, m = now.hour, now.minute
        # Hae kertoimet klo 10, 19, 02
        if h in [10,19,2] and m == 0:
            if time.time() - last_odds > 3600:
                fetch_odds()
                last_odds = time.time()
        # Hae tulokset 15min välein
        if time.time() - last_results > 900:
            fetch_results()
            last_results = time.time()
        time.sleep(60)

@app.route('/')
def index():
    return jsonify({'status':'ok','message':'MLB Edge Server'})

@app.route('/api/all')
def get_all():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    games = conn.execute('SELECT * FROM games ORDER BY date DESC LIMIT 300').fetchall()
    conn.close()
    return jsonify([dict(g) for g in games])

@app.route('/api/games')
def get_games():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d')
    games = conn.execute(
        'SELECT * FROM games WHERE date IN (?,?) ORDER BY commence',
        (today,tomorrow)
    ).fetchall()
    conn.close()
    return jsonify([dict(g) for g in games])

@app.route('/api/results')
def get_results():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    games = conn.execute(
        'SELECT * FROM games WHERE result IS NOT NULL ORDER BY date DESC LIMIT 100'
    ).fetchall()
    conn.close()
    return jsonify([dict(g) for g in games])

@app.route('/api/status')
def get_status():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute('SELECT COUNT(*) FROM games').fetchone()[0]
    with_result = conn.execute('SELECT COUNT(*) FROM games WHERE result IS NOT NULL').fetchone()[0]
    conn.close()
    return jsonify({'status':'ok','total_games':total,'with_results':with_result,
                   'server_time':datetime.now().strftime('%H:%M')})

@app.route('/api/fetch', methods=['POST','GET'])
def manual_fetch():
    fetch_odds()
    fetch_results()
    return jsonify({'status':'ok'})

if __name__ == '__main__':
    import os
    init_db()
    fetch_odds()
    fetch_results()
    t = threading.Thread(target=scheduler, daemon=True)
    t.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
