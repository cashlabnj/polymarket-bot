# Add 'Session' to your imports at the top (keep your other imports)
import requests
# ... other imports

# --- STEALTH FETCHING (Bypasses Simple Firewalls) ---

def fetch_polymarket_list():
    print("Fetching Polymarket (Stealth Mode)...")
    try:
        # Create a session to persist headers
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://polymarket.com/"
        })
        
        url = "https://gamma-api.polymarket.com/markets?active=true&order=volume_24h&limit=30"
        r = session.get(url, timeout=15) # Increased timeout
        
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
        print(f"✅ Polymarket Success: {len(markets)} markets")
        return markets
    except Exception as e:
        print(f"❌ Poly Error: {e}")
        return []

def fetch_kalshi_list():
    print("Fetching Kalshi (Stealth Mode)...")
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://www.kalshi.com/"
        })

        url = "https://trading-api.kalshi.com/v1/markets?limit=30"
        r = session.get(url, timeout=15) # Increased timeout
        
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
            print(f"✅ Kalshi Success: {len(markets)} markets")
            return markets
        else:
            print(f"❌ Kalshi Blocked/Failed: {r.status_code}")
            return []
    except Exception as e:
        print(f"❌ Kalshi Error: {e}")
        return []
