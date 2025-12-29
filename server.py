import os
import json
import requests
import re 
import asyncio
from flask import Flask, jsonify, request
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

app = Flask(__name__)
CORS(app) 

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SCOUT_PROMPT = """
You are an Arbitrage Scout. 
I will provide a JSON list of active markets.
1. Determine Topic: 'geo', 'crypto', or 'mention'.
2. Return TOP 3 markets sorted by 'Confidence'.
3. Return ONLY JSON.

Format:
[
    {
        "title": "Market Name",
        "current_price": 0.XX,
        "fair_value": 0.XX,
        "confidence": 85,
        "rationale": "Reasoning...",
        "topic": "geo"
    }
]
"""

# --- IMPROVED FETCHING ---

def fetch_polymarket_list():
    print("Fetching Polymarket...")
    try:
        # User-Agent is critical
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        url = "https://gamma-api.polymarket.com/markets?active=true&order=volume_24h&limit=10"
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        markets = []
        for m in data:
            price = m.get('prices', {}).get('mid', 0.5)
            markets.append({
                "source": "Polymarket",
                "title": m.get('question', m.get('title')),
                "current_price": price,
                "link": f"https://polymarket.com/event/{m.get('slug')}"
            })
        print(f"✅ Polymarket OK ({len(markets)} markets)")
        return markets
    except Exception as e:
        print(f"❌ Poly Error: {e}")
        return []

def fetch_kalshi_list():
    print("Fetching Kalshi...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        url = "https://trading-api.kalshi.com/v1/markets?limit=10"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            markets_data = data.get('markets', data) if isinstance(data, dict) else data
            markets = []
            for m in markets_data:
                if not isinstance(m, dict): continue
                price = m.get('last_price', m.get('p_yes', 50)) / 100
                markets.append({
                    "source": "Kalshi",
                    "title": m.get('title', "Unknown"),
                    "current_price": price,
                    "link": f"https://www.kalshi.com/markets/{m.get('ticker', '')}"
                })
            print(f"✅ Kalshi OK ({len(markets)} markets)")
            return markets
        else:
            print(f"❌ Kalshi HTTP Error: {r.status_code}")
            return []
    except Exception as e:
        print(f"❌ Kalshi Error: {e}")
        return []

# --- FALLBACK MARKETS (If APIs are blocked) ---
FALLBACK_MARKETS = [
    {"source": "Polymarket", "title": "Winner of 2024 US Presidential Election", "current_price": 0.55, "link": "https://polymarket.com/event/winner-of-2024-us-presidential-election"},
    {"source": "Polymarket", "title": "Will Bitcoin exceed $100,000 in 2024?", "current_price": 0.35, "link": "https://polymarket.com/event/will-bitcoin-exceed-100000-in-2024"},
    {"source": "Kalshi", "title": "Federal Reserve target rate after Nov 2024 meeting", "current_price": 0.20, "link": "https://www.kalshi.com/markets/interest-rate-fed-funds-nov-2024"},
    {"source": "Polymarket", "title": "Will Trump tweet about Crypto in July?", "current_price": 0.40, "link": "#"}
]

async def send_telegram_alert(market_title, edge, confidence, source):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    if confidence < 80: return 
    bot = Bot(token=token)
    msg = f"🚨 *HOT ALERT [{source}]*\n{market_title}\nEdge: {edge:.1%}\nConf: {confidence}%"
    try:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except: pass

@app.route('/api/discover', methods=['POST'])
def discover_markets():
    print("🔍 --- STARTING SCAN ---")
    
    try:
        poly = fetch_polymarket_list()
        kalshi = fetch_kalshi_list()
        
        # --- STRATEGY: Use Fallback if APIs fail ---
        all_markets = poly + kalshi
        
        if not all_markets:
            print("⚠️ APIs Blocked. Using Fallback List (Manual Markets).")
            all_markets = FALLBACK_MARKETS

        scan_list = all_markets[:10] 
        print(f"🤖 Sending {len(scan_list)} markets to AI...")
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SCOUT_PROMPT},
                {"role": "user", "content": json.dumps(scan_list)}
            ],
            temperature=0.3
        )
        
        content = response.choices[0].message.content
        print(f"🧠 AI Response Received.")
        
        try:
            content = content.replace("```json", "").replace("```", "")
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                content = match.group(0)
            picks = json.loads(content)
        except Exception as e:
            print(f"❌ JSON Parse Error: {e}")
            return jsonify([])
        
        final_results = []
        for pick in picks:
            if 'fair_value' not in pick or 'confidence' not in pick:
                continue
                
            edge = pick['fair_value'] - pick['current_price']
            confidence = pick['confidence']
            
            if confidence > 80 and edge > 0:
                asyncio.run(send_telegram_alert(pick['title'], edge, confidence, pick.get('source','Unknown')))

            final_results.append({
                "title": pick['title'],
                "source": pick.get('source', "Unknown"),
                "topic": pick.get('topic', "geo"),
                "current_price": pick['current_price'],
                "fair_value": pick['fair_value'],
                "edge": edge,
                "confidence": confidence,
                "rationale": pick['rationale'],
                "link": "https://polymarket.com"
            })
            
        print(f"✅ Scan Complete.")
        return jsonify(final_results)

    except Exception as e:
        print(f"❌ SERVER ERROR: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
