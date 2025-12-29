import os
import json
import random
import asyncio
from flask import Flask, jsonify, request
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Bot

# --- CONFIGURATION ---
load_dotenv()

app = Flask(__name__)
# Enable CORS so your HTML dashboard can talk to this server
CORS(app) 

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- AGENT PROMPTS ---
GEO_PROMPT = """
You are a Master Geopolitics and Trade Analyst. 
Return ONLY a valid JSON object with keys: fair_value (float), confidence (int 0-100), rationale (string).
"""

MENTION_PROMPT = """
You are a Social Sentiment Expert in 'Mention Markets' (Trump, Musk, etc.).
Return ONLY a valid JSON object with keys: fair_value (float), confidence (int 0-100), rationale (string).
"""

CRYPTO_PROMPT = """
You are a Crypto Technical and Fundamental Analyst.
Return ONLY a valid JSON object with keys: fair_value (float), confidence (int 0-100), rationale (string).
"""

# --- HELPER FUNCTIONS ---

def ask_agent(agent_type, market_title, current_price):
    # Select prompt based on agent type
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
        # Clean markdown
        if "```json" in content: content = content.replace("```json", "").replace("```", "")
        return json.loads(content)
        
    except Exception as e:
        print(f"Error: {e}")
        return {"fair_value": current_price, "confidence": 0, "rationale": "Error"}

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
    
    # 1. Get Inputs
    market_title = data.get('title')
    agent_type = data.get('agent')
    
    # 2. Mock Current Price (You can replace this with real API calls later)
    current_price = round(random.uniform(0.1, 0.8), 2)
    
    # 3. Ask AI Agent
    ai_result = ask_agent(agent_type, market_title, current_price)
    
    # 4. Calculate
    fair_value = ai_result['fair_value']
    confidence = ai_result['confidence']
    edge = fair_value - current_price
    rationale = ai_result['rationale']

    # 5. Send Telegram Alert if it's a good bet
    if confidence > 70 and edge > 0:
        asyncio.run(send_telegram_alert(market_title, edge, confidence))

    # 6. Return Data
    return jsonify({
        "current_price": current_price,
        "fair_value": fair_value,
        "edge": edge,
        "confidence": confidence,
        "rationale": rationale
    })

# --- START SERVER ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
