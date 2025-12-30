import os
import json
import requests
import re
import asyncio
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

# --- IMPORT OFFICIAL CLIENTS ---
from kalshi_python import KalshiApi
from openai import OpenAI
from telegram import Bot

load_dotenv()

app = Flask(__name__)
CORS(app) 

SCOUT_PROMPT = """
You are an Arbitrage Scout. 
I will provide a JSON list of active markets.
1. Determine Topic: 'geo', 'crypto', or 'mention'.
2. Return TOP 5 markets sorted by 'Confidence'.
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

# --- 1. POLYMARKET FETCHER ---
def fetch_polymarket_list():
    print("🌐 Fetching Polymarket...")
    try:
        # Stealth Headers
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://polymarket.com/"
        })
        
        # Fetching 30 markets
        url = "https://gamma-api.polymarket.com/markets?active=true&order=volume_24h&limit=30"
        r = session.get(url, timeout=15)
        
        if r.status_code != 200:
            print(f"❌ POLY HTTP ERROR: {r.status_code}")
            return []
            
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
        print(f"✅ POLY SUCCESS: {len(markets)} markets")
        return markets
        
    except Exception as e:
        print(f"❌ POLY CRASH: {e}")
        return []

# --- 2. KALSHI FETCHER ---
def fetch_kalshi_list():
    print("🌐 Fetching Kalshi (Official API)...")
    try:
        key_id = os.getenv("KALSHI_KEY")
        secret = os.getenv("KALSHI_SECRET")
        
        if not key_id or not secret:
            print("❌ KALSHI ERROR: KEYS MISSING IN RENDER ENV VARS")
            return []

        # Initialize Official Client
        api = KalshiApi(key_id=key_id, key_secret=secret)
        
        # Fetch Markets
        response = api.get_markets(limit=30)
        
        if not response or 'markets' not in response:
            print(f"❌ KALSHI ERROR: INVALID RESPONSE OR AUTH FAILED. CHECK KEYS.")
            return []
            
        markets = []
        for m in response['markets']:
            # Convert 1-100 to 0-1
            price = m.get('last_price', m.get('p_yes', 50)) / 100
            markets.append({
                "source": "Kalshi",
                "title": m.get('title', "Unknown"),
                "current_price": price,
                "link": f"https://www.kalshi.com/markets/{m.get('ticker', '')}"
            })
        print(f"✅ KALSHI SUCCESS: {len(markets)} markets")
        return markets
        
    except Exception as e:
        print(f"❌ KALSHI CRASH: {e}")
        # If this prints "Unauthorized", your keys are wrong.
        return []

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

# --- 3. MAIN ROUTE ---
@app.route('/api/discover', methods=['POST'])
def discover_markets():
    print("🚀 --- STARTING LIVE SCAN ---")
    
    try:
        # 1. Fetch Data
        poly = fetch_polymarket_list()
        kalshi = fetch_kalshi_list()
        
        all_markets = poly + kalshi
        
        # NO FALLBACK. If APIs fail, we return [].
        if not all_markets:
            print("❌ CRITICAL: ALL APIs RETURNED EMPTY.")
            return jsonify([])

        print(f"🤖 Total Markets Found: {len(all_markets)}. Sending to AI...")
        
        # 2. Analyze with AI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SCOUT_PROMPT},
                {"role": "user", "content": json.dumps(all_markets[:30])}
            ],
            temperature=0.3
        )
        
        content = response.choices[0].message.content
        print(f"🧠 AI Response Received.")
        
        # 3. Parse JSON
        try:
            content = content.replace("```json", "").replace("```", "")
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                content = match.group(0)
            picks = json.loads(content)
        except Exception as e:
            print(f"❌ JSON PARSE ERROR: {e}")
            return jsonify([])
        
        # 4. Format Results
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
            
        print(f"✅ --- SCAN COMPLETE. {len(final_results)} RESULTS ---")
        return jsonify(final_results)

    except Exception as e:
        print(f"❌ SERVER CRASH: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
