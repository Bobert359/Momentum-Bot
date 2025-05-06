# === IMPORTS ===
import ccxt
import pandas as pd
import time
import threading
from datetime import datetime, timedelta, timezone
import requests
from flask import Flask, jsonify, render_template_string

# === TELEGRAM KONFIGURATION ===
telegram_token = '7793055320:AAFhsfKiAsK766lBL4olwGamBA8q6HCFtqk'
telegram_chat_id = '591018668'

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {'chat_id': telegram_chat_id, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram Fehler: {e}")

# === BOT KONFIGURATION ===
order_size_usdt = 10
trigger_pct = 2.0
profit_target = 10.0
stop_loss = 3.0
max_hold_minutes = 720
max_open_trades = 12

# === BYBIT TESTNET KONFIGURATION ===
api_key = 'srmnTEwzus9Qm3OXcB'
api_secret = 'RCnswq9OLJuCq9Y4N4JioZHSbjH5eR8IY3UW'
testnet_url = 'https://testnet.bybit.com/'

# === EXCHANGE SETUP ===
exchange = ccxt.bybit({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'linear'},
    'urls': {
        'api': {
            'public': 'https://api-testnet.bybit.com',
            'private': 'https://api-testnet.bybit.com'
        }
    }
})

markets = exchange.load_markets()
symbol = next((m for m in markets if 'BTC/USDT' in m), None)
if not symbol:
    raise ValueError("❌ BTC/USDT Symbol nicht gefunden – bitte überprüfe den Markt-Typ!")

# === FLASK ===
app = Flask(__name__)
open_trades = []
last_status_update = datetime.now(timezone.utc)

@app.route('/')
def home():
    return '✅ Trading Bot is running!'

@app.route('/ping')
def ping():
    return jsonify({"status": "success", "message": "Bot is running!"}), 200

@app.route('/status')
def get_status():
    try:
        current_price = get_current_price()
        long_trades = len([t for t in open_trades if t['side'] == 'long'])
        short_trades = len([t for t in open_trades if t['side'] == 'short'])
        trade_info = [
            {"side": t['side'], "entry_price": t['entry_price'], "entry_time": t['entry_time']}
            for t in open_trades
        ]
        return jsonify({
            "current_price": current_price,
            "open_trades": len(open_trades),
            "long_trades": long_trades,
            "short_trades": short_trades,
            "trade_info": trade_info
        }), 200
    except Exception as e:
        print(f"Fehler beim Statusabruf: {e}")
        return jsonify({"error": "Statusfehler"}), 500

@app.route('/dashboard')
def dashboard():
    try:
        current_price = get_current_price()
        long_trades = len([t for t in open_trades if t['side'] == 'long'])
        short_trades = len([t for t in open_trades if t['side'] == 'short'])

        if len(open_trades) == 0:
            table_rows = "<tr><td colspan='4'>Keine offenen Trades</td></tr>"
        else:
            table_rows = ""
            for t in open_trades:
                table_rows += f"""
                    <tr>
                        <td>{t['side'].upper()}</td>
                        <td>{t['entry_price']:.2f}</td>
                        <td>{t['entry_time'].strftime('%Y-%m-%d %H:%M')}</td>
                        <td>{t['amount']}</td>
                    </tr>
                """

        unrealized_pnl = 0
        for t in open_trades:
            entry = t['entry_price']
            qty = t['amount']
            side = t['side']
            pnl = (current_price - entry) * qty if side == 'long' else (entry - current_price) * qty
            unrealized_pnl += pnl

        html = f"""
        <html>
        <head>
            <title>Trading Bot Dashboard</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ font-family: Arial; background: #f4f4f4; }}
                h1 {{ color: #333; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ padding: 10px; border: 1px solid #ccc; text-align: center; }}
                th {{ background-color: #eee; }}
            </style>
        </head>
        <body>
            <h1>📊 Trading Bot Dashboard</h1>
            <div id="tradingview_chart" style="height: 500px;"></div>
            <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
            <script type="text/javascript">
              new TradingView.widget({{
                "width": "100%",
                "height": 500,
                "symbol": "BYBIT:BTCUSDT",
                "interval": "1",
                "timezone": "Etc/UTC",
                "theme": "light",
                "style": "1",
                "locale": "de",
                "container_id": "tradingview_chart"
              }});
            </script>
            <p>Aktueller Preis: <strong>{current_price:.2f} USDT</strong></p>
            <p>Offene Trades: {len(open_trades)} (Long: {long_trades} / Short: {short_trades})</p>
            <p>📈 Unrealized PnL: <strong>{unrealized_pnl:.2f} USDT</strong></p>
            <table>
                <thead>
                    <tr>
                        <th>Richtung</th>
                        <th>Eintrittspreis</th>
                        <th>Zeit</th>
                        <th>Menge</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </body>
        </html>
        """
        return render_template_string(html)
    except Exception as e:
        return f"<p>❌ Fehler beim Laden des Dashboards: {e}</p>"

# === BOT FUNKTIONEN ===
def fetch_ohlcv(timeframe, limit=100):
    candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def get_current_price():
    df = fetch_ohlcv('2h', limit=1)
    return df['close'].iloc[-1]

def place_market_order(side, amount):
    try:
        return exchange.create_market_order(symbol, side, amount)
    except Exception as e:
        print(f"Orderfehler: {e}")
        return None

def run_bot():
    global open_trades, last_status_update
    send_telegram_message("📢 Backtest-Strategie aktiviert ✅ (2h-Breakout)")

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Hole 2h-Daten der letzten 100 Kerzen
            df_2h = fetch_ohlcv('2h', limit=100)
            current_price = df_2h['close'].iloc[-1]

            # Verwende bisherigen Tiefst- und Höchstkurs (ohne aktuelle Kerze)
            lowest = df_2h['low'][:-1].min()
            highest = df_2h['high'][:-1].max()

            change_up = (current_price - lowest) / lowest * 100
            change_down = (current_price - highest) / highest * 100

            qty = round(order_size_usdt / current_price, 3)

            # Long Entry
            if change_up >= trigger_pct and len(open_trades) < max_open_trades:
                if place_market_order('buy', qty):
                    open_trades.append({
                        'side': 'long', 'entry_price': current_price,
                        'entry_time': now, 'amount': qty
                    })
                    send_telegram_message(f"🟢 LONG @ {current_price:.2f} | Menge: {qty}")

            # Short Entry
            if change_down <= -trigger_pct and len(open_trades) < max_open_trades:
                if place_market_order('sell', qty):
                    open_trades.append({
                        'side': 'short', 'entry_price': current_price,
                        'entry_time': now, 'amount': qty
                    })
                    send_telegram_message(f"🔴 SHORT @ {current_price:.2f} | Menge: {qty}")

            # Offene Trades prüfen
            updated_trades = []
            for t in open_trades:
                price_now = get_current_price()
                pnl = ((price_now - t['entry_price']) / t['entry_price']) * 100 if t['side'] == 'long' else ((t['entry_price'] - price_now) / t['entry_price']) * 100
                hold_minutes = (now - t['entry_time']).total_seconds() / 60
                exit_side = 'sell' if t['side'] == 'long' else 'buy'

                reason = None
                if pnl >= 8.0:
                    reason = f"🎯 TP erreicht (+{pnl:.2f}%)"
                elif pnl <= -2.0:
                    reason = f"🛑 SL ausgelöst ({pnl:.2f}%)"
                elif hold_minutes >= max_hold_minutes and pnl < 0:
                    reason = f"⏰ Zeitlimit ({pnl:.2f}%)"

                if reason:
                    place_market_order(exit_side, t['amount'])
                    send_telegram_message(f"{reason}\nExit: {exit_side.upper()} @ {price_now:.2f}")
                else:
                    updated_trades.append(t)

            open_trades = updated_trades

            # Status-Update alle 15 Minuten
            if (now - last_status_update) >= timedelta(minutes=15):
                msg = f"📊 STATUS-UPDATE\nPreis: {current_price:.2f} USDT\nOpen Trades: {len(open_trades)}\nLong: {len([t for t in open_trades if t['side'] == 'long'])} | Short: {len([t for t in open_trades if t['side'] == 'short'])}"
                send_telegram_message(msg)
                last_status_update = now

            time.sleep(60)

        except Exception as e:
            print(f"⚠️ Botfehler: {e}")
            time.sleep(10)


# === BOT + FLASK PARALLEL STARTEN ===
if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=5000)
