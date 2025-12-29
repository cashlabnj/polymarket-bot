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

# --- BATCH SCANNER AGENT PROMPT ---
SCOUT_PROMPT = """
You are a high-speed Arbitrage Scout for Prediction Markets. 
I will provide a JSON list of active markets with their titles and current prices (0.0 - 1.0).
Analyze them ALL. Identify the top 3-5 markets that are UNDERPRICED (Safe Bets).
For the top picks, return ONLY a JSON list with this structure:
[
    {
        "title": "Market Name",
        "current_price": 0.XX,
        "fair_value": 0.XX,
        "confidence": 85,
        "rationale": "Reasoning..."
    }
]
Ignore markets with confidence below 70%.
"""

# --- DATA FETCHING ---

def fetch_polymarket_list():
    """Fetches top active markets from Polymarket (Public API)"""
    try:
        # Fetch high liquidity markets
        url = "https://gamma-api.polymarket.com/markets?active=true&order=volume_24h&limit=30"
        r = requests.get(url)
        data = r.json()
        
        markets = []
        for m in data:
            price = m.get('prices', {}).get('mid', 0.5)
            title = m.get('question', m.get('title'))
            
            markets.append({
                "source": "Polymarket",
                "title": title,
                "current_price": price,
                "link": f"https://polymarket.com/event/{m.get('slug')}"
            })
        return markets
    except Exception as e:
        print(f"Poly Fetch Error: {e}")
        return []

def fetch_kalshi_list():
    """Fetches top active markets from Kalshi (Using Requests directly to avoid SDK issues)"""
    try:
        # We hit the public endpoint. Note: Kalshi public endpoints sometimes require user-agent headers.
        url = "https://trading-api.kalshi.com/v1/markets?limit=30"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        r = requests.get(url, headers=headers)
        
        if r.status_code == 200:
            data = r.json()
            markets = []
            
            # Handle both list and wrapped list responses
            markets_data = data.get('markets', data) if isinstance(data, dict) else data
            
            for m in markets_data:
                # Kalshi prices are 1-100. Convert to 0-1.
                # Looking for 'last_price' or 'p_yes'
                price = m.get('last_price', m.get('p_yes', 50)) / 100
                
                markets.append({
                    "source": "Kalshi",
                    "title": m.get('title', "Unknown Market"),
                    "current_price": price,
                    "link": f"https://www.kalshi.com/markets/{m.get('ticker', '')}"
                })
            return markets
        else:
            print(f"Kalshi Error Status: {r.status_code}")
            return []
            
    except Exception as e:
        print(f"Kalshi Fetch Error: {e}")
        return []

async def send_telegram_alert(market_title, edge, confidence):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    bot = Bot(token=token)
    msg = f"🚨 *NEW ARBITRAGE ALERT*\n{market_title}\nEdge: {edge:.1%}\nConf: {confidence}%"
    try:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except: pass

# --- NEW SCANNER ROUTE ---

@app.route('/api/discover', methods=['POST'])
def discover_markets():
    """
    1. Fetches all active markets from Poly/Kalshi.
    2. Sends list to AI for batch analysis.
    3. Returns the best bets.
    """
    print("🔍 Starting Scan...")
    
    # 1. Gather Data
    poly_markets = fetch_polymarket_list()
    kalshi_markets = fetch_kalshi_list()
    
    all_markets = poly_markets + kalshi_markets
    
    if not all_markets:
        return jsonify([])

    # 2. Ask AI (Batch Analysis)
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
        
        # 3. Format results
        final_results = []
        for pick in picks:
            edge = pick['fair_value'] - pick['current_price']
            confidence = pick['confidence']
            
            if confidence > 75 and edge > 0:
                asyncio.run(send_telegram_alert(pick['title'], edge, confidence))

            final_results.append({
                "title": pick['title'],
                "source": "Mixed", 
                "current_price": pick['current_price'],
                "fair_value": pick['fair_value'],
                "edge": edge,
                "confidence": confidence,
                "rationale": pick['rationale'],
                "link": "https://polymarket.com" 
            })
            
        print(f"✅ Scan complete. Found {len(final_results)} picks.")
        return jsonify(final_results)

    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify([])

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
