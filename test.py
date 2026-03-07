import websocket
import json
import threading
import time
import sys

API_KEY = '5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e'
ws_url = f"wss://api.geops.io/realtime-ws/v1/?key={API_KEY}"
counter = 0
def on_message(ws, msg):
    global counter
    data = json.loads(msg)
    print(json.dumps(data, indent=4))
    if counter > 1000:
        sys.exit()
    else:
        counter += 1
    # print(f"[{time.strftime('%H:%M:%S')}] {data.get('source', 'unknown')}")
    if data.get('source') == 'trajectory':
        line = data['content']['properties'].get('line', {}).get('name', '?')
        train_id = data['content']['properties']
        # coords_len = len(data['content']['geometry']['coordinates'])
    #     print(f"  🚂 {line}: {coords_len} GPS points!")

def on_error(ws, error):
    print(f"❌ {error}")

def on_open(ws):
    print("✅ Connected")
    
    ws.send("BUFFER 60000 1000")  # 60s buffer, 1000 vehicles [page:1]
    time.sleep(1)
    
    # Zurich from docs (should work)
    # ws.send("BBOX 837468 5963148 915383 6033720 11")
    
    # Munich wide
    # ws.send("BBOX 1269000 6087000 1350000 6200000 5 tenant=sbm")
    # ws.send("GET station")
    ws.send("GET stopsequence_sbm_140511618865616")
    # Ping loop
    def ping():
        while ws.sock and ws.sock.connected:
            ws.send("PING")
            time.sleep(25)
    threading.Thread(target=ping, daemon=True).start()

ws = websocket.WebSocketApp(ws_url, on_message=on_message, on_open=on_open, on_error=on_error)
ws.run_forever(ping_interval=30)
