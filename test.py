import websocket
import json
import threading
import time

API_KEY = '5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e'
ws_url = f"wss://api.geops.io/realtime-ws/v1/?key={API_KEY}"

def on_message(ws, msg):
    data = json.loads(msg)
    print(f"[{time.strftime('%H:%M:%S')}] {data.get('source', 'unknown')}")
    if data.get('source') == 'trajectory':
        line = data['content']['properties'].get('line', {}).get('name', '?')
        coords_len = len(data['content']['geometry']['coordinates'])
        print(f"  🚂 {line}: {coords_len} GPS points!")

def on_error(ws, error):
    print(f"❌ {error}")

def on_open(ws):
    print("✅ Connected")
    
    ws.send("BUFFER 60000 1000")  # 60s buffer, 1000 vehicles [page:1]
    time.sleep(1)
    
    # Zurich from docs (should work)
    ws.send("BBOX 837468 5963148 915383 6033720 11")
    
    # Munich wide
    ws.send("BBOX 1100000 6300000 1200000 6400000 9 mots=rail")
    
    # Ping loop
    def ping():
        while ws.sock and ws.sock.connected:
            ws.send("PING")
            time.sleep(25)
    threading.Thread(target=ping, daemon=True).start()

ws = websocket.WebSocketApp(ws_url, on_message=on_message, on_open=on_open, on_error=on_error)
ws.run_forever(ping_interval=30)
