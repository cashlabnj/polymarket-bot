import os
import json
import requests
import asyncio
from flask import Flask, jsonify, request
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Bot
from kalshi_python import KalshiApi # Official SDK

load_dotenv()

app = Flask(__name__)
CORS(app) 

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- REAL DATA FETCHING ---

def get_kalshi_price(ticker):
    """Fetches latest price from Kalshi API"""
    try:
        # You need to get your Key ID and Secret from Kalshi dashboard
        kalshi_api = KalshiApi(
            key_id=os.getenv("KALSHI_KEY"), 
            key_secret=os.getenv("KALSHI_SECRET")
        )
        
        # Get market info
        response = kalshi_api.get_market(ticker=ticker)
        
        if 'market' in response and 'last_price' in response['market']:
            # Kalshi price is 1-100, we convert to 0.00-1.00
            return response['market']['last_price'] / 100
        return 0.5 # Fallback
    except Exception as e:
        print(f"Kalshi Error: {e}")
        return 0.5

def get_polymarket_price(market_id):
    """Fetches price from Polymarket Gamma API (Public)"""
    try:
        # Polymarket uses "slug" (URL-friendly ID) or internal ID
        url = f"https://gamma-api.polymarket.com/markets?slug={market_id}"
        
        headers = {
            "User-Agent": "Mozilla/5.0" 
        }
        
        r = requests.get(url, headers=headers)
        data = r.json()
        
        if data and 'markets' in data and len(data['markets']) > 0:
            # Returns probability between 0-1
            return data['markets'][0]['prices']['mid'] or 0.5
            
    except Exception as e:
        print(f"Poly Error: {e}")
    return 0.5 # Fallback

# --- AGENT LOGIC (Keep your existing prompts here) ---
GEO_PROMPT = """... (Keep your prompts) ..."""
MENTION_PROMPT = """... (Keep your prompts) ..."""
CRYPTO_PROMPT = """... (Keep your prompts) ..."""

def ask_agent(agent_type, market_title, current_price):
    # ... (Keep your existing ask_agent logic) ...
    # For brevity in this response, I am assuming you paste the existing ask_agent code back in here
    prompt = GEO_PROMPT
    if agent_type == "mention": prompt = MENTION_PROMPT
    if agent_type == "crypto": prompt = CRYPTO_PROMPT

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Market: {market_title}\nCurrent Price: {current_price}"}
            ],
            temperature=0.3
        )
        content = response.choices[0].message.content
        if "```json" in content: content = content.replace("```json", "").replace("```", "")
        return json.loads(content)
    except Exception as e:
        print(f"Error: {e}")
        return {"fair_value": current_price, "confidence": 0, "rationale": "Error"}

# Telegram Logic
async def send_telegram_alert(market_title, edge, confidence):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    bot = Bot(token=token)
    msg = f"🚨 *AI ALERT*\n{market_title}\nEdge: {edge:.1%}\nConf: {confidence}%"
    try:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        print("Alert sent to Telegram")
    except: pass

# --- MAIN ROUTE ---

@app.route('/api/analyze', methods=['POST'])
def analyze_market():
    data = request.json
    
    market_title = data.get('title')
    agent_type = data.get('agent')
    source = data.get('source').lower() # 'kalshi' or 'polymarket'
    
    # --- 1. FETCH REAL PRICE ---
    current_price = 0.5
    
    # We expect the HTML to send a 'ticker' field now
    ticker = data.get('ticker') 
    
    if ticker:
        if 'kalshi' in source:
            current_price = get_kalshi_price(ticker)
        elif 'polymarket' in source:
            current_price = get_polymarket_price(ticker)
    
    print(f"Fetched Real Price for {market_title}: {current_price}")

    # 2. Ask AI
    ai_result = ask_agent(agent_type, market_title, current_price)
    
    # 3. Calculate
    fair_value = ai_result['fair_value']
    confidence = ai_result['confidence']
    edge = fair_value - current_price
    rationale = ai_result['rationale']

    # 4. Alert
    if confidence > 70 and edge > 0:
        asyncio.run(send_telegram_alert(market_title, edge, confidence))

    return jsonify({
        "current_price": current_price,
        "fair_value": fair_value,
        "edge": edge,
        "confidence": confidence,
        "rationale": rationale
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
