import os
import json
import requests
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

# --- UPDATED PROMPT WITH TOPIC DETECTION ---
SCOUT_PROMPT = """
You are an Arbitrage Scout. 
I will provide a JSON list of active markets. Each item has a 'title', 'source' (Kalshi or Polymarket), and 'current_price'.
1. Analyze the Title to determine the Topic: 'geo' (Geopolitics/Elections/Trade), 'crypto' (Blockchain/Price Action), or 'mention' (Social Media/Celebrity specific).
2. Identify the top 3-5 markets that are UNDERPRICED (Safe Bets).

Return ONLY a JSON list with this structure:
[
    {
        "title": "Market Name",
        "current_price": 0.XX,
        "fair_value": 0.XX,
        "confidence": 85,
        "rationale": "Reasoning...",
        "topic": "geo" // Must be one of: 'geo', 'crypto', 'mention'
    }
]
Ignore markets with confidence below 70%.
"""

# --- DATA FETCHING ---

def fetch_polymarket_list():
    try:
        url = "https://gamma-api.polymarket.com/markets?active=true&order=volume_24h&limit=30"
        r = requests.get(url)
        data = r.json()
        
        markets = []
        for m in data:
            price = m.get('prices', {}).get('mid', 0.5)
            markets.append({
                "source": "Polymarket", # Explicitly tag the source
                "title": m.get('question', m.get('title')),
                "current_price": price,
                "link": f"https://polymarket.com/event/{m.get('slug')}"
            })
        return markets
    except Exception as e:
        print(f"Poly Fetch Error: {e}")
        return []

def fetch_kalshi_list():
    try:
        url = "https://trading-api.kalshi.com/v1/markets?limit=30"
        headers = {"User-Agent": "Mozilla/5.0"} 
        r = requests.get(url, headers=headers)
        
        if r.status_code == 200:
            data = r.json()
            markets_data = data.get('markets', data) if isinstance(data, dict) else data
            markets = []
            for m in markets_data:
                price = m.get('last_price', m.get('p_yes', 50)) / 100
                markets.append({
                    "source": "Kalshi", # Explicitly tag the source
                    "title": m.get('title', "Unknown"),
                    "current_price": price,
                    "link": f"https://www.kalshi.com/markets/{m.get('ticker', '')}"
                })
            return markets
    except Exception as e:
        print(f"Kalshi Fetch Error: {e}")
        return []

async def send_telegram_alert(market_title, edge, confidence, source):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    bot = Bot(token=token)
    msg = f"🚨 *ALERT [{source}]*\n{market_title}\nEdge: {edge:.1%}\nConf: {confidence}%"
    try:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except: pass

# --- SCANNER ROUTE ---

@app.route('/api/discover', methods=['POST'])
def discover_markets():
    print("🔍 Scanning...")
    
    poly = fetch_polymarket_list()
    kalshi = fetch_kalshi_list()
    all_markets = poly + kalshi
    
    if not all_markets: return jsonify([])

    scan_list = all_markets[:30] 
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SCOUT_PROMPT},
                {"role": "user", "content": json.dumps(scan_list)}
            ],
            temperature=0.3
        )
        
        content = response.choices[0].message.content
        if "```json" in content: content = content.replace("```json", "").replace("```", "")
        picks = json.loads(content)
        
        final_results = []
        for pick in picks:
            edge = pick['fair_value'] - pick['current_price']
            confidence = pick['confidence']
            
            if confidence > 75 and edge > 0:
                asyncio.run(send_telegram_alert(pick['title'], edge, confidence, "AI Scout"))

            final_results.append({
                "title": pick['title'],
                "source": pick.get('source', "Unknown"), # Preserve source
                "topic": pick.get('topic', "geo"),       # Get AI topic
                "current_price": pick['current_price'],
                "fair_value": pick['fair_value'],
                "edge": edge,
                "confidence": confidence,
                "rationale": pick['rationale'],
                "link": "https://polymarket.com" 
            })
            
        print(f"✅ Found {len(final_results)} picks.")
        return jsonify(final_results)

    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify([])

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
