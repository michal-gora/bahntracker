# Station Display Controller - PSoC6 (CY8CPROTO-062-4343W)

This script runs on a PSoC6 microcontroller with an LCD1602 display and LEDs to show upcoming S-Bahn stations.

## Hardware Requirements

- **CY8CPROTO-062-4343W** (PSoC6 development board with WiFi)
- **LCD1602** with I2C backpack (16x2 character display, PCF8574 I2C interface)
- 2x LEDs (green and red) with current-limiting resistors (220Ω - 1kΩ)
- USB cable for programming
- WiFi connection (2.4GHz)

## Pin Configuration

Default pin configuration for CY8CPROTO-062-4343W (can be modified in `station_display_controller.py`):

```
I2C (LCD1602):
- SDA: P6_0
- SCL: P6_1

LEDs:
- Green LED (valid station): P5_0
- Red LED (invalid/next stop): P5_1
```

## LCD Library

This project uses the **standard MicroPython I2C LCD library** by Dave Hylands, which is widely used and tested. The library supports LCD1602/LCD2004 displays with the PCF8574 I2C backpack.

**Required files:**
- `lcd_api.py` - Base LCD API
- `i2c_lcd.py` - I2C implementation for PCF8574

These files are included in the `/micropython` folder.

## I2C LCD1602 Address

The default I2C address is `0x27`. If your LCD doesn't work, try changing `LCD_ADDR` to `0x3F` in the configuration section.

To find your LCD's I2C address, the script will print detected I2C devices on startup.

## Setup Instructions

### 1. Configure WiFi

Edit `wifi_config.json` with your WiFi credentials:

```json
{
    "ssid": "your_wifi_name",
    "password": "your_wifi_password"
}
```

### 2. Configure Server IP

Edit the `SERVER_IP` variable in `station_display_controller.py`:

```python
SERVER_IP = "192.168.178.26"  # Change to your server's IP
```

### 3. Upload Files to CY8CPROTO-062-4343W

Upload these files to your PSoC6:
- `station_display_controller.py` - Main application
- `wifi.py` - WiFi connection helper
- `wifi_config.json` - WiFi credentials
- `lcd_api.py` - LCD API library (required)
- `i2c_lcd.py` - I2C LCD driver (required)

**Upload method:** Use Thonny IDE, rshell, ampy, or your preferred MicroPython file transfer tool.

### 4. Run on Boot (Optional)

To automatically start the display on boot, create or edit `main.py`:

```python
import station_display_controller
station_display_controller.main()
```

### 5. Start the Server

On your PC, integrate the TCP station server into your main script:

```python
from tcp_station_output import TcpStationOutput, tcp_station_server

# Create station output
station_output = TcpStationOutput()

# Start TCP server (in your async main function)
await tcp_station_server(station_output)

# Use station_output in your TrainStateMachine
state_machine = TrainStateMachine(
    model=model_output,
    station=station_output,  # This is the TCP output
    route=route
)
```

## Protocol

The station display implements a simple TCP protocol with newline-terminated messages:

### Station → Server:
- `HELLO:STATION\n` - Initial handshake on connection
- `PING\n` - Heartbeat every 10 seconds

### Server → Station:
- `ACK\n` - Acknowledgment after HELLO
- `PONG\n` - Response to PING
- `STATION:name:valid\n` - Display station name with green LED (arriving)
- `STATION:name:invalid\n` - Display station name with red LED (next stop)
- `STATION:clear\n` - Clear display and turn off all LEDs

## Display Behavior

### Valid Station (Green LED):
```
  Marienplatz
  Arriving...
```

### Invalid/Next Station (Red LED):
```
  Marienplatz
  Next stop...
```

### Long Station Names:
Long station names are automatically split across two lines:
```
  München
  Hauptbahnhof
```

### Waiting State:
```
  Waiting...
  
```

## Troubleshooting

### LCD Not Working
1. Check I2C wiring (SDA/SCL)
2. Verify I2C address - try `0x27` or `0x3F`
3. Check power supply to LCD (5V or 3.3V depending on module)
4. Ensure backlight jumper is set on LCD module
5. Check the I2C device list printed on startup

### LEDs Not Working
1. Verify LED polarity (long leg = anode/positive)
2. Check resistor values (220Ω - 1kΩ recommended)
3. Verify pin assignments match your wiring

### WiFi Connection Failed
1. Double-check WiFi credentials in `wifi_config.json`
2. Ensure WiFi is 2.4GHz (most microcontrollers don't support 5GHz)
3. Check if WiFi network is in range

### Cannot Connect to Server
1. Verify server IP address is correct
2. Ensure server is running and listening on port 8081
3. Check that both devices are on the same network
4. Try pinging the server from your PC

### Connection Drops
- Check WiFi signal strength
- Verify firewall isn't blocking port 8081
- Ensure PING/PONG watchdog timers match between client and server

## Testing Without Server

You can test the hardware by modifying the `main()` function:

```python
def main():
    lcd = init_hardware()
    
    # Test display
    display_station(lcd, "Test Station", True)
    time.sleep(3)
    display_station(lcd, "Another Test", False)
    time.sleep(3)
    clear_display(lcd)
```

## Integration with Main Server

The station display is designed to work with the `TrainStateMachine` from the main Bahntracker project. The state machine automatically sends station updates based on the train's position and route.

See `tcp_station_output.py` for the server-side implementation.
