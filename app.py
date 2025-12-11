# app.py
import streamlit as st
import pandas as pd
from datetime import datetime
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from twilio.rest import Client
import re
import time
import math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import numpy as np

# ==========================================
# 0. CONFIGURATION & SECRETS
# ==========================================
st.set_page_config(page_title="StockPulse", page_icon="Lightning", layout="wide")

try:
    SENDER_EMAIL = st.secrets["SENDER_EMAIL"]
    SENDER_PASSWORD = st.secrets["SENDER_PASSWORD"]
    TWILIO_SID = st.secrets["TWILIO_ACCOUNT_SID"]
    TWILIO_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
    TWILIO_FROM = st.secrets["TWILIO_PHONE_NUMBER"]
    GCP_SECRETS = st.secrets["gcp_service_account"]
except Exception:
    st.error("Error loading secrets. Check secrets.toml")
    st.stop()

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SHEET_ID = "18GROVu8c2Hx5n4H2FiZrOeLXgH9xJG0miPqfgdb-V9w"

# ==========================================
# 1. DATABASE FUNCTIONS
# ==========================================
def get_db_connection():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(GCP_SECRETS, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        return sheet
    except Exception as e:
        st.error(f"DB Connection Error: {e}")
        return None

def load_data_from_db():
    sheet = get_db_connection()
    if not sheet: return pd.DataFrame()
    try:
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        expected = ["ticker","target_price","current_price","direction","notes","created_at","status","triggered_at"]
        for col in expected:
            if col not in df.columns: df[col] = ""
        return df
    except:
        return pd.DataFrame(columns=expected)

def sync_db(df):
    sheet = get_db_connection()
    if not sheet: return
    df_save = df.copy().astype(str)
    try:
        sheet.clear()
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())
    except Exception as e:
        st.error(f"Save Error: {e}")

# ==========================================
# 2. LOGIC HELPERS
# ==========================================
def is_duplicate_alert(ticker, target, direction):
    if st.session_state.alert_db.empty: return False
    active = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
    if active.empty: return False
    try:
        dup = active[(active['ticker'] == ticker) & 
                     (active['target_price'].astype(float) == float(target)) & 
                     (active['direction'] == direction)]
        return not dup.empty
    except:
        return False

def get_market_status():
    tickers = {'S&P 500': '^GSPC', 'Nasdaq': '^IXIC', 'VIX': '^VIX', 'Bitcoin': 'BTC-USD'}
    results = {}
    for name, symbol in tickers.items():
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="5d")
            if hist.empty or len(hist) < 2:
                results[name] = (0.0, 0.0); continue
            price = float(hist['Close'].iloc[-1])
            prev = float(hist['Close'].iloc[-2])
            delta = (price - prev) / prev * 100
            results[name] = (price, delta)
        except:
            results[name] = (0.0, 0.0)
    return results

# ==========================================
# 3. ANALYSIS & NOTIFICATIONS
# ==========================================
def calculate_smart_sl(ticker, buy_price):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if len(hist) < 150: return None, "Not enough data"
        hist['MA150'] = hist['Close'].rolling(150).mean()
        tr = pd.concat([
            hist['High'] - hist['Low'],
            (hist['High'] - hist['Close'].shift()).abs(),
            (hist['Low'] - hist['Close'].shift()).abs()
        ], axis=1).max(axis=1)
        hist['ATR'] = tr.rolling(14).mean()
        latest = hist.iloc[-1]
        ma150, atr = latest['MA150'], latest['ATR']
        curr = latest['Close']
        entry = buy_price if buy_price > 0 else curr

        sl = entry - 2*atr
        reason = "2×ATR"

        if sl < entry * 0.88:
            sl = entry * 0.88
            reason = "Max 12% Loss"
        if curr > ma150 and sl < ma150:
            sl = ma150
            reason = "MA150 Support"
        if sl >= curr:
            sl = curr * 0.99
            reason = "Immediate Exit"

        trend = "UP" if curr > ma150 else "DOWN"
        return {"ma150": ma150, "atr": atr, "trend": trend, "sl_price": sl,
                "current_price": curr, "reason": reason, "entry": entry}, None
    except Exception as e:
        return None, str(e)

def send_email_alert(to_email, ticker, price, target, direction, notes):
    if not SENDER_EMAIL: return False, "No email"
    try:
        msg = MIMEMultipart()
        msg['From'], msg['To'] = SENDER_EMAIL, to_email
        msg['Subject'] = f"StockPulse: {ticker} → ${price:,.2f}"
        body = f"{ticker}\nPrice: ${price:,.2f}\nTarget: ${target}\n{direction}\n{notes}\n{datetime.now()}"
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
        return True, "Sent"
    except Exception as e:
        return False, str(e)

def send_whatsapp_alert(to_number, ticker, price, target, direction):
    if not TWILIO_SID: return False, "No Twilio"
    clean = re.sub(r'\D', '', str(to_number))
    if clean.startswith("0"): clean = "972" + clean[1:]
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            from_=TWILIO_FROM,
            body=f"*{ticker}* Alert!\nPrice: ${price:.2f}\nTarget: ${target}\n{direction}",
            to=f"whatsapp:+{clean}"
        )
        return True, "Sent"
    except Exception as e:
        return False, str(e)

def check_alerts():
    if st.session_state.alert_db.empty: return
    active = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
    if active.empty: return

    tickers = active['ticker'].unique()
    try:
        data = yf.download(tickers, period="1d", progress=False)['Close']
        if len(tickers) == 1:
            prices = {tickers[0]: data.iloc[-1].item()}
        else:
            prices = data.iloc[-1].to_dict()
    except:
        return

    changed = False
    for idx, row in active.iterrows():
        price = prices.get(row['ticker'], 0)
        if price <= 0: continue
        st.session_state.alert_db.at[idx, 'current_price'] = price

        target = float(row['target_price'])
        if (row['direction'] == "Up" and price >= target) or (row['direction'] == "Down" and price <= target):
            if st.session_state.user_email:
                send_email_alert(st.session_state.user_email, row['ticker'], price, target, row['direction'], row['notes'])
            if st.session_state.user_phone:
                send_whatsapp_alert(st.session_state.user_phone, row['ticker'], price, target, row['direction'])
            st.session_state.alert_db.at[idx, 'status'] = 'Completed'
            st.session_state.alert_db.at[idx, 'triggered_at'] = str(datetime.now())
            st.toast(f"Triggered: {row['ticker']}")
            changed = True

    if changed:
        sync_db(st.session_state.alert_db)
        st.rerun()

# ==========================================
# 4. UI & CSS – עיצוב מושלם ורספונסיבי
# ==========================================
def apply_custom_ui():
    st.markdown("""
    <style>
        .stApp { background: #0a0a0a; color: #e0e0e0; }
        h1,h2,h3 { color: #FFC107 !important; margin: 0.5rem 0; }
        .market-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 14px;
            margin: 20px 8px;
        }
        @media (min-width: 640px) {
            .market-grid { grid-template-columns: repeat(4, 1fr); gap: 18px; margin: 24px 12px; }
        }
        .market-card {
            background: linear-gradient(135deg, #1e1e1e, #2d2d2d);
            border-radius: 16px;
            padding: 16px;
            text-align: center;
            border: 1px solid #333;
            box-shadow: 0 6px 16px rgba(0,0,0,0.4);
            transition: all 0.3s ease;
        }
        .market-card:hover {
            transform: translateY(-6px);
            border-color: #FFC107;
            box-shadow: 0 12px 24px rgba(255,193,7,0.15);
        }
        .market-title { font-size: 0.8rem; color: #aaa; letter-spacing: 1px; margin-bottom: 8px; }
        .market-value { font-size: 1.7rem; font-weight: 800; color: #fff; }
        .market-delta { font-size: 1rem; font-weight: bold; margin-top: 4px; }
        .alert-row {
            background: #1a1a1a;
            padding: 14px;
            border-radius: 12px;
            margin: 10px 0;
            border-left: 5px solid #333;
        }
        .ticker-big { font-size: 1.5rem; font-weight: 900; color: #FFC107; }
        .target-big { font-size: 1.3rem; font-weight: bold; color: #00E676; }
        div.stButton > button { height: 38px !important; border-radius: 10px !important; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 5. MAIN APP
# ==========================================
def main():
    apply_custom_ui()

    # Session state
    for key in ['user_email','user_phone','processed_msgs','alert_db','edit_ticker','edit_price','edit_note']:
        if key not in st.session_state:
            if key == 'processed_msgs': st.session_state[key] = set()
            elif key == 'alert_db': st.session_state[key] = load_data_from_db()
            else: st.session_state[key] = "" if "email" in key or "phone" in key or "note" in key else 0.0

    # Header
    col1, col2 = st.columns([3,1])
    with col1:
        st.markdown("<h2 style='margin:0;'>StockPulse</h2>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div style='text-align:right; color:#888;'>{datetime.now():%d/%m %H:%M}</div>", unsafe_allow_html=True)

    # Market Dashboard
    with st.container():
        st.markdown("### Market Overview")
        market = get_market_status()
        cards = ""
        for label, key in [("S&P 500","S&P 500"), ("Nasdaq","Nasdaq"), ("VIX","VIX"), ("Bitcoin","BTC")]:
            val, delta = market.get(key, (0,0))
            if val == 0:
                vstr, dstr, col = "—", "0.00%", "#888"
            else:
                vstr = f"{val:,.0f}" if key != "VIX" else f"{val:.2f}"
                if key == "BTC": vstr = f"{val:,.0f}"
                dstr = f"{delta:+.2f}%"
                col = "#FF4B4B" if (key=="VIX" and delta>=0) or (key!="VIX" and delta<0) else "#00E676"
            cards += f"""
            <div class="market-card">
                <div class="market-title">{label}</div>
                <div class="market-value">{vstr}</div>
                <div class="market-delta" style="color:{col}">{dstr}</div>
            </div>"""
        st.markdown(f'<div class="market-grid">{cards}</div>', unsafe_allow_html=True)
        st.markdown("---")

    # Settings
    with st.expander("Connection Settings", expanded=False):
        c1, c2 = st.columns(2)
        with c1: email = st.text_input("Email", value=st.session_state.user_email)
        with c2: phone = st.text_input("WhatsApp", value=st.session_state.user_phone)
        if st.button("Save Settings", type="primary"):
            st.session_state.user_email, st.session_state.user_phone = email, phone
            st.success("Saved!")

    # Tabs
    tab1, tab2, tab3 = st.tabs(["Active Alerts", "Smart SL Calc", "History"])

    with tab1:
        col_list, col_add = st.columns([2.5, 1])
        active = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']

        with col_list:
            view = st.radio("View", ["Table", "Cards"], horizontal=True, label_visibility="collapsed")
            if active.empty:
                st.info("No active alerts")
            else:
                if view == "Table":
                    for idx, row in active.iterrows():
                        curr = float(row['current_price'] or 0)
                        tgt = float(row['target_price'])
                        diff = (curr - tgt)/tgt*100 if tgt else 0
                        bar_color = "#00E676" if row['direction']=="Up" else "#FF4B4B"
                        st.markdown(f"""
                        <div class="alert-row" style="border-left-color:{bar_color}">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <div>
                                    <span class="ticker-big">{row['ticker']}</span>
                                    <span style="margin:0 10px; color:#888;">→</span>
                                    <span class="target-big">${tgt:.2f}</span>
                                </div>
                                <div style="text-align:right;">
                                    <div style="color:#aaa; font-size:0.9rem;">Now ${curr:.2f}</div>
                                    <div style="color:{'#00E676' if diff>=0 else '#FF4B4B'}">{diff:+.2f}%</div>
                                </div>
                            </div>
                            <div style="margin-top:8px; color:#aaa; font-size:0.9rem;">
                                {row['direction']} • {row['notes'] or "No note"}
                            </div>
                            <div style="margin-top:12px; display:flex; gap:8px;">
                                {st.button("Edit", key=f"e{idx}")}
                                {st.button("Delete", key=f"d{idx}")}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                                if st.session_state.get(f"e{idx}"):
                                    st.session_state.edit_ticker = row['ticker']
                                    st.session_state.edit_price = tgt
                                    st.session_state.edit_note = row['notes']
                                    st.session_state.alert_db.drop(idx, inplace=True)
                                    sync_db(st.session_state.alert_db)
                                    st.rerun()
                                if st.session_state.get(f"d{idx}"):
                                    st.session_state.alert_db.drop(idx, inplace=True)
                                    sync_db(st.session_state.alert_db)
                                    st.rerun()

        with col_add:
            st.markdown("### Add Alert")
            with st.form("add_form"):
                t = st.text_input("Ticker", value=st.session_state.edit_ticker).upper()
                p = st.number_input("Target Price", value=float(st.session_state.edit_price or 0), step=0.1)
                d = st.selectbox("Direction", ["Up", "Down"], index=0 if st.session_state.get("direction","Up")=="Up" else 1)
                n = st.text_input("Note", value=st.session_state.edit_note)
                if st.form_submit_button("Save", type="primary"):
                    if is_duplicate_alert(t, p, d):
                        st.error("Already exists!")
                    else:
                        new = {"ticker":t, "target_price":p, "current_price":0.0, "direction":d,
                               "notes":n, "created_at":str(datetime.now()), "status":"Active", "triggered_at":""}
                        st.session_state.alert_db = pd.concat([st.session_state.alert_db, pd.DataFrame([new])], ignore_index=True)
                        sync_db(st.session_state.alert_db)
                        st.session_state.edit_ticker = st.session_state.edit_price = st.session_state.edit_note = ""
                        st.success(f"{t} added!")
                        st.rerun()

    with tab2:
        st.markdown("### Smart Stop-Loss Calculator")
        ticker = st.text_input("Ticker", placeholder="AAPL").upper()
        price = 0.0
        if ticker:
            try:
                price = float(yf.Ticker(ticker).history(period='1d')['Close'].iloc[-1])
            except: pass
        buy = st.slider("Entry Price", 0.0, price*2 if price else 1000.0, price or 100.0, 0.1)
        if st.button("Calculate SL", type="primary"):
            with st.spinner("Analyzing..."):
                res, err = calculate_smart_sl(ticker, buy)
                if err: st.error(err)
                else: st.session_state.calc = res; st.session_state.calc_ticker = ticker
        if 'calc' in st.session_state:
            r = st.session_state.calc
            t = st.session_state.calc_ticker
            st.markdown(f"""
            <div style="background:#1e1e1e; padding:20px; border-radius:12px; border-left:5px solid #FFC107;">
                <h3>{t} • Smart SL</h3>
                <h2 style="color:#00E676;">${r['sl_price']:.2f}</h2>
                <p><b>Reason:</b> {r['reason']} • <b>Trend:</b> {r['trend']}</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Set Alert at this SL"):
                if is_duplicate_alert(t, r['sl_price'], "Down"):
                    st.warning("Already active")
                else:
                    new = {"ticker":t, "target_price":round(r['sl_price'],2), "current_price":r['current_price'],
                           "direction":"Down", "notes":"Smart SL", "created_at":str(datetime.now()),
                           "status":"Active", "triggered_at":""}
                    st.session_state.alert_db = pd.concat([st.session_state.alert_db, pd.DataFrame([new])], ignore_index=True)
                    sync_db(st.session_state.alert_db)
                    st.success("SL Alert Created!")
                    st.rerun()

    with tab3:
        st.markdown("### History Log")
        done = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Completed']
        if done.empty:
            st.caption("No completed alerts")
        else:
            for _, row in done[::-1].iterrows():
                st.success(f"{row['ticker']} → ${float(row['target_price']):.2f} @ {row['triggered_at'][:16]}")
            if st.button("Clear History"):
                st.session_state.alert_db = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
                sync_db(st.session_state.alert_db)
                st.rerun()

    # Auto-check every 60s if enabled
    if st.toggle("Auto-refresh (60s)"):
        check_alerts()
        time.sleep(60)
        st.rerun()

if __name__ == "__main__":
    main()
