from fastapi import FastAPI, Request
import threading
import uvicorn
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
import uuid
import os

# --- 1. FastAPI Webhook Arka Plan Sunucusu ---
app = FastAPI()

def init_db():
    conn = sqlite3.connect('trading_sim.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id TEXT, timestamp TEXT, symbol TEXT, side TEXT, qty INTEGER, price REAL)''')
    conn.commit()
    conn.close()

init_db()

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    data = await request.json()
    conn = sqlite3.connect('trading_sim.db', check_same_thread=False)
    c = conn.cursor()
    order_id = f"TV_{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", 
              (order_id, timestamp, data.get("symbol"), data.get("side"), data.get("qty"), data.get("price")))
    conn.commit()
    conn.close()
    return {"status": "success", "order_id": order_id}

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8000)

if not os.environ.get("FASTAPI_STARTED"):
    os.environ["FASTAPI_STARTED"] = "true"
    threading.Thread(target=run_fastapi, daemon=True).start()

# --- 2. Streamlit Arayüzü ---
import streamlit as st

st.set_page_config(page_title="Algo-Trading OMS", page_icon="🤖", layout="wide")

def get_orders():
    try:
        conn = sqlite3.connect('trading_sim.db', check_same_thread=False)
        df = pd.read_sql_query("SELECT * FROM orders", conn)
        conn.close()
        return df
    except:
        return pd.DataFrame(columns=["id", "timestamp", "symbol", "side", "qty", "price"])

def calculate_portfolio(orders_df):
    cash = 100000.0
    portfolio = {}
    avg_costs = {}
    for _, row in orders_df.iterrows():
        sym, side, qty, price = row['symbol'], row['side'], row['qty'], row['price']
        cost = qty * price
        if sym not in portfolio:
            portfolio[sym] = 0
            avg_costs[sym] = 0.0
        cur_qty = portfolio[sym]
        if side == "AL (BUY)":
            if cash >= cost:
                old_cost = cur_qty * avg_costs[sym]
                avg_costs[sym] = (old_cost + cost) / (cur_qty + qty)
                portfolio[sym] += qty
                cash -= cost
        elif side == "SAT (SELL)":
            if cur_qty >= qty:
                portfolio[sym] -= qty
                cash += cost
                if portfolio[sym] == 0:
                    avg_costs[sym] = 0.0
    return cash, portfolio, avg_costs

st.title("🤖 Ücretsiz Bulut Algo-Trading Terminali")
symbol = st.sidebar.text_input("Görüntülenen Hisse", value="THYAO.IS")

orders_df = get_orders()
cash, portfolio, avg_costs = calculate_portfolio(orders_df)

try:
    market_data = yf.download(symbol, period="1d", interval="1m", progress=False)
    market_data.columns = [col[0] if isinstance(col, tuple) else col for col in market_data.columns]
    last_price = float(market_data['Close'].iloc[-1])
except:
    market_data = None
    last_price = 0.0

if market_data is not None and not market_data.empty:
    current_qty = portfolio.get(symbol, 0)
    avg_cost = avg_costs.get(symbol, 0.0)
    portfolio_val = last_price * current_qty
    unrealized_pnl = portfolio_val - (avg_cost * current_qty)
    pnl_pct = (unrealized_pnl / (avg_cost * current_qty) * 100) if (avg_cost * current_qty) > 0 else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Toplam Nakit Bakiye", f"{cash:,.2f} TL")
    col2.metric(f"Pozisyon ({symbol})", f"{current_qty} Adet", f"Maliyet: {avg_cost:.2f}")
    col3.metric("Açık PnL", f"{unrealized_pnl:+.2f} TL", f"%{pnl_pct:+.2f}")

    st.divider()
    fig = go.Figure(data=[go.Candlestick(x=market_data.index, open=market_data['Open'], high=market_data['High'], low=market_data['Low'], close=market_data['Close'])])
    fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0, r=0, t=0, b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("📡 Sistem Emir Logları")
    if not orders_df.empty:
        st.dataframe(orders_df.iloc[::-1].set_index("timestamp"), use_container_width=True)
    else:
        st.info("Sistemde henüz emir yok.")