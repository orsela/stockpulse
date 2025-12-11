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
st.set_page_config(page_title="StockPulse", page_icon="⚡", layout="wide")

try:
    SENDER_EMAIL = st.secrets.get("SENDER_EMAIL", "")
    SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD", "")
    TWILIO_SID = st.secrets.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_TOKEN = st.secrets.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM = st.secrets.get("TWILIO_PHONE_NUMBER", "")
    GCP_SECRETS = st.secrets["gcp_service_account"]
except Exception:
    st.error("❌ Error loading secrets. Please check your secrets.toml file.")
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
        st.error(f"❌ Database Connection Error: {e}")
        return None

def load_data_from_db():
    sheet = get_db_connection()
    if not sheet: return pd.DataFrame()
    try:
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        expected_cols = ["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status", "triggered_at"]
        if df.empty: return pd.DataFrame(columns=expected_cols)
        for col in expected_cols:
            if col not in df.columns: df[col] = ""
        return df
    except Exception as e:
        return pd.DataFrame(columns=["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status", "triggered_at"])

def sync_db(df):
    sheet = get_db_connection()
    if not sheet: return
    df_save = df.copy().astype(str)
    try:
        sheet.clear()
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())
    except Exception as e:
        st.error(f"Error saving to DB: {e}")

# ==========================================
# 2. LOGIC HELPERS
# ==========================================
def is_duplicate_alert(ticker, target, direction):
    if st.session_state.alert_db.empty: return False
    active_mask = st.session_state.alert_db['status'] == 'Active'
    df_active = st.session_state.alert_db[active_mask]
    if df_active.empty: return False
    try:
        target_float = float(target)
        check_df = df_active.copy()
        check_df['target_float'] = pd.to_numeric(check_df['target_price'], errors='coerce')
        duplicate = check_df[(check_df['ticker'] == ticker) & (check_df['target_float'] == target_float) & (check_df['direction'] == direction)]
        return not duplicate.empty
    except: return False

def get_market_status():
    tickers = {'S&P 500': '^GSPC', 'Nasdaq': '^IXIC', 'VIX': '^VIX', 'Bitcoin': 'BTC-USD'}
    results = {}
    for name, symbol in tickers.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if hist.empty:
                 results[name] = (0.0, 0.0)
                 continue
            price = hist['Close'].iloc[-1]
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                delta = ((price - prev_close) / prev_close) * 100
            else:
                delta = 0.0
             
            try: price = float(price) 
            except: price = 0.0
            if math.isnan(price): price = 0.0
            try: delta = float(delta) 
            except: delta = 0.0
            if math.isnan(delta): delta = 0.0
            results[name] = (price, delta)
        except Exception as e:
            results[name] = (0.0, 0.0)
    return results

# ==========================================
# 3. ANALYSIS & NOTIFICATIONS
# ==========================================
def calculate_smart_sl(ticker, buy_price):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if len(hist) < 150: return None, "Not enough data for MA150"
        hist['MA150'] = hist['Close'].rolling(window=150).mean()
        high_low = hist['High'] - hist['Low']
        high_close = (hist['High'] - hist['Close'].shift()).abs()
        low_close = (hist['Low'] - hist['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        hist['ATR'] = tr.rolling(window=14).mean()
        latest = hist.iloc[-1]
        ma150 = latest['MA150']
        atr = latest['ATR']
        curr_price = latest['Close']
        entry = buy_price if buy_price > 0 else curr_price
        
        sl_atr = entry - (2 * atr)
        final_sl = sl_atr
        reason = "Volatility (2x ATR)"
        sl_max_loss = entry * 0.88
        if final_sl < sl_max_loss: final_sl = sl_max_loss; reason = "Max Loss Limit (12%)"
        if curr_price > ma150 and final_sl < ma150: final_sl = ma150; reason = "MA150 Support Rule"
        if final_sl >= curr_price: final_sl = curr_price * 0.99; reason = "Immediate Exit (Price violated rules)"

        trend = "UP 🟢" if curr_price > ma150 else "DOWN 🔴"
        return {"ma150": ma150, "atr": atr, "trend": trend, "sl_price": final_sl, "current_price": curr_price, "reason": reason, "entry": entry}, None
    except Exception as e: return None, str(e)

def send_email_alert(to_email, ticker, current_price, target_price, direction, notes):
    if not SENDER_EMAIL or not SENDER_PASSWORD: return False, "Secrets missing"
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL; msg['To'] = to_email
        msg['Subject'] = f"🚀 StockPulse: {ticker} hit ${current_price:,.2f}"
        body = f"Ticker: {ticker}\nPrice: ${current_price}\nTarget: ${target_price}\nDirection: {direction}\nNote: {notes}\nTime: {datetime.now()}"
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls(); server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
        return True, "Email Sent"
    except Exception as e: return False, str(e)

def send_whatsapp_alert(to_number, ticker, current_price, target_price, direction):
    if not TWILIO_SID: return False, "Secrets missing"
    clean_digits = re.sub(r'\D', '', str(to_number))
    if clean_digits.startswith("0"): clean_digits = "972" + clean_digits[1:]
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg_body = f"🚀 *{ticker}* Alert!\nPrice: ${current_price:.2f}\nTarget: ${target_price}\nDirection: {direction}"
        client.messages.create(from_=TWILIO_FROM, body=msg_body, to=f"whatsapp:+{clean_digits}")
        return True, "WA Sent"
    except Exception as e: return False, str(e)

def process_incoming_whatsapp():
    if not TWILIO_SID: return
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        raw_phone = str(st.session_state.user_phone)
        digits_only = re.sub(r'\D', '', raw_phone)
        if digits_only.startswith("0"): digits_only = "972" + digits_only[1:]
        expected_sender = f"whatsapp:+{digits_only}"
        messages = client.messages.list(limit=5, to=TWILIO_FROM)
        changes = False
        for msg in messages:
            if msg.direction == 'inbound' and msg.from_ == expected_sender and msg.sid not in st.session_state.processed_msgs:
                st.session_state.processed_msgs.add(msg.sid)
                match = re.match(r"^([A-Z]+)\s+(\d+(\.\d+)?)$", msg.body.strip().upper())
                if match:
                    t, p = match.group(1), float(match.group(2))
                    if not is_duplicate_alert(t, p, "Up"):
                        new = {"ticker": t, "target_price": p, "current_price": 0.0, "direction": "Up", "notes": "WA Add", "created_at": str(datetime.now()), "status": "Active", "triggered_at": ""}
                        st.session_state.alert_db = pd.concat([st.session_state.alert_db, pd.DataFrame([new])], ignore_index=True)
                        changes = True
                        st.toast(f"✅ WA Added: {t}")
        if changes: sync_db(st.session_state.alert_db)
    except: pass

def check_alerts():
    process_incoming_whatsapp()
    if st.session_state.alert_db.empty: return
    active_indices = st.session_state.alert_db.index[st.session_state.alert_db['status'] == 'Active'].tolist()
    if not active_indices: return
    active_df = st.session_state.alert_db.loc[active_indices]
    tickers = active_df['ticker'].unique().tolist()
    if not tickers: return
    try:
        data = yf.download(tickers, period="1d", progress=False)['Close']
        if len(tickers) == 1:
            val = data.iloc[-1]
            current_prices = {tickers[0]: val.item() if hasattr(val, 'item') else val}
        else:
            current_prices = data.iloc[-1].to_dict()
    except: return

    changes_made = False
    for idx in active_indices:
        row = st.session_state.alert_db.loc[idx]
        tkr = row['ticker']
        price = current_prices.get(tkr, 0)
        if price > 0:
            st.session_state.alert_db.at[idx, 'current_price'] = price
            tgt = float(row['target_price'])
            direct = row['direction']
            triggered = (direct == "Up" and price >= tgt) or (direct == "Down" and price <= tgt)
            if triggered:
                if st.session_state.user_email: send_email_alert(st.session_state.user_email, tkr, price, tgt, direct, row['notes'])
                if st.session_state.user_phone: send_whatsapp_alert(st.session_state.user_phone, tkr, price, tgt, direct)
                st.session_state.alert_db.at[idx, 'status'] = 'Completed'
                st.session_state.alert_db.at[idx, 'triggered_at'] = str(datetime.now())
                st.toast(f"🔥 Triggered: {tkr}")
                changes_made = True
    if changes_made:
        sync_db(st.session_state.alert_db)
        st.rerun()

# ==========================================
# 5. UI & CSS (THE NUCLEAR "NO-WRAP" FIX)
# ==========================================
def apply_custom_ui():
    st.markdown("""
    <style>
        .stApp { background-color: #0e0e0e !important; color: #ffffff; }

        /* DASHBOARD GRID */
        .dashboard-grid {
            display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 20px;
        }
        @media (min-width: 768px) { .dashboard-grid { grid-template-columns: repeat(4, 1fr); } }
        
        .market-card { 
            background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 10px;
            display: flex; flex-direction: row; justify-content: space-between; align-items: center;
        }
        .market-title { font-size: 0.85rem; color: #ccc; font-weight: bold; }
        .market-value { font-size: 0.95rem; color: #fff; font-family: monospace; }
        .market-delta { font-size: 0.85rem; font-weight: bold; }

        /* INPUTS */
        input, textarea, select, div[data-baseweb="select"] > div {
            color: #fff !important; background-color: #262626 !important; border-color: #444 !important;
        }
        div[data-testid="stTextInput"] > div > div, div[data-testid="stNumberInput"] > div > div {
             background-color: #262626 !important;
        }
        label { color: #888 !important; }

        /* --- CRITICAL: FORCE ROW LAYOUT ON MOBILE --- */
        
        /* 1. FORCE FLEX DIRECTION ROW (Disable mobile stacking) */
        div[data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important; /* Forces row direction even on phone */
            flex-wrap: nowrap !important;   /* Disables wrapping */
            gap: 2px !important;
        }
        
        /* 2. ALLOW COLUMNS TO SHRINK INDEFINITELY */
        div[data-testid="column"] {
            min-width: 0px !important;      /* Override Streamlit's minimum width */
            width: auto !important;
            flex: 1 1 auto !important;      /* Grow and Shrink as needed */
            padding: 0px !important;
            overflow: hidden !important;    /* Clip content if needed, don't break layout */
        }
        
        /* Table Headers */
        .tbl-header { 
            font-size: 0.65rem; color: #888; font-weight: bold; text-transform: uppercase; 
            text-align: center; background: #161616; padding: 6px 0; border-bottom: 1px solid #333;
            white-space: nowrap;
        }
        
        /* Table Cells */
        .tbl-cell { 
            font-family: 'Roboto Mono', monospace; font-size: 0.8rem; color: #fff; 
            padding: 10px 0; text-align: center; height: 40px; display: flex; align-items: center; justify-content: center;
        }
        
        /* Buttons (Streamlit Native override - Minimalist) */
        div.stButton > button {
            padding: 0px !important; margin: 0px !important;
            font-size: 0.9rem !important; line-height: 1 !important;
            height: 40px !important; width: 100% !important;
            border: none !important; background: transparent !important;
            color: #666 !important; border-radius: 0 !important;
            border-left: 1px solid #222 !important;
            min-width: 0px !important; /* Allow button to be tiny */
        }
        div.stButton > button:hover { background: #222 !important; color: #fff !important; }
        
        /* Visual Row Separator */
        .row-border { height: 1px; width: 100%; margin: 0; }

    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 6. MAIN APP
# ==========================================
def main():
    apply_custom_ui()
    
    # Init Session
    if 'user_email' not in st.session_state: st.session_state.user_email = ""
    if 'user_phone' not in st.session_state: st.session_state.user_phone = ""
    if 'processed_msgs' not in st.session_state: st.session_state.processed_msgs = set()
    if 'alert_db' not in st.session_state: st.session_state.alert_db = load_data_from_db()
    if 'edit_ticker' not in st.session_state: st.session_state.edit_ticker = ""
    if 'edit_price' not in st.session_state: st.session_state.edit_price = 0.0
    if 'edit_note' not in st.session_state: st.session_state.edit_note = ""

    # HEADER
    c1, c2 = st.columns([3,1])
    with c1: st.markdown("<h3 style='margin:0; color:#FFC107;'>StockPulse</h3>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div style='text-align:right;color:#888;padding-top:8px;'>{datetime.now():%H:%M}</div>", unsafe_allow_html=True)

    # DASHBOARD
    market_data = get_market_status()
    # Linear HTML construction
    html_out = '<div class="dashboard-grid">'
    for label, key in [("S&P 500","S&P 500"),("Nasdaq","Nasdaq"),("VIX","VIX"),("Bitcoin","Bitcoin")]:
        v, d = market_data.get(key, (0,0))
        vs = f"{v:,.0f}" if key != "VIX" else f"{v:.2f}"
        ds = f"{d:+.2f}%"
        col = "#00E676" if (key != "VIX" and d >= 0) or (key == "VIX" and d < 0) else "#FF4B4B"
        html_out += f'<div class="market-card" style="border-left: 3px solid {col};"><div class="market-title">{label}</div><div class="market-value">{vs}</div><div class="market-delta" style="color:{col}">{ds}</div></div>'
    html_out += '</div>'
    st.markdown(html_out, unsafe_allow_html=True)

    # SETTINGS
    with st.expander("⚙️ Connection", expanded=False):
        c1, c2 = st.columns(2)
        with c1: st.text_input("Email", key="temp_email", value=st.session_state.user_email)
        with c2: st.text_input("WhatsApp", key="temp_phone", value=st.session_state.user_phone)
        if st.button("Save Settings", type="primary"):
            st.session_state.user_email = st.session_state.temp_email
            st.session_state.user_phone = st.session_state.temp_phone
            st.success("Saved!")
        if st.toggle("🔄 Auto-Poll (60s)"):
            check_alerts()
            time.sleep(60)
            st.rerun()

    # TABS
    tab_alerts, tab_calc, tab_hist = st.tabs(["🔔 Active", "🛡️ Calc", "📂 Log"])
    
    # 1. ALERTS TAB
    with tab_alerts:
        active = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
        if active.empty:
            st.info("No active alerts")
        else:
            # HEADER (Fixed Ratios for Mobile)
            # Ratios tuned to squeeze everything in
            cols_cfg = [1.5, 1.2, 1.2, 0.6, 0.6]
            
            h1, h2, h3, h4, h5 = st.columns(cols_cfg)
            h1.markdown("<div class='tbl-header'>TICKER</div>", unsafe_allow_html=True)
            h2.markdown("<div class='tbl-header'>TGT</div>", unsafe_allow_html=True)
            h3.markdown("<div class='tbl-header'>CUR</div>", unsafe_allow_html=True)
            h4.markdown("<div class='tbl-header'></div>", unsafe_allow_html=True)
            h5.markdown("<div class='tbl-header'></div>", unsafe_allow_html=True)

            # ROWS
            for idx, row in active.iterrows():
                curr = float(row.get('current_price', 0) or 0)
                tgt = float(row['target_price'])
                row_col = "#FF4B4B" if curr > tgt else "#00E676"
                
                # Top Border
                st.markdown(f"<div class='row-border' style='background:{row_col}; opacity:0.6;'></div>", unsafe_allow_html=True)
                
                c1, c2, c3, c4, c5 = st.columns(cols_cfg)
                
                c1.markdown(f"<div class='tbl-cell' style='color:#FFC107; font-weight:900;'>{row['ticker']}</div>", unsafe_allow_html=True)
                c2.markdown(f"<div class='tbl-cell'>{tgt:.1f}</div>", unsafe_allow_html=True)
                c3.markdown(f"<div class='tbl-cell' style='color:#aaa;'>{curr:.1f}</div>", unsafe_allow_html=True)
                
                with c4:
                    if st.button("✏️", key=f"e_{idx}"):
                        st.session_state.edit_ticker = row['ticker']
                        st.session_state.edit_price = tgt
                        st.session_state.edit_note = row['notes']
                        st.session_state.alert_db.drop(idx, inplace=True); st.session_state.alert_db.reset_index(drop=True, inplace=True); sync_db(st.session_state.alert_db); st.rerun()
                with c5:
                    if st.button("🗑️", key=f"d_{idx}"):
                        st.session_state.alert_db.drop(idx, inplace=True); st.session_state.alert_db.reset_index(drop=True, inplace=True); sync_db(st.session_state.alert_db); st.rerun()

        st.markdown("---")
        with st.expander("➕ Add Alert", expanded=True):
            with st.form("add_form"):
                t = st.text_input("Ticker", st.session_state.edit_ticker).upper()
                p = st.number_input("Target", float(st.session_state.edit_price or 0.0), step=0.1)
                d = st.selectbox("Dir", ["Up", "Down"])
                n = st.text_input("Note", st.session_state.edit_note)
                
                if st.form_submit_button("Save", use_container_width=True):
                    if is_duplicate_alert(t, p, d):
                        st.error("Duplicate!")
                    else:
                        new = {"ticker": t, "target_price": p, "current_price": 0.0, "direction": d, "notes": n, "created_at": str(datetime.now()), "status": "Active", "triggered_at": ""}
                        st.session_state.alert_db = pd.concat([st.session_state.alert_db, pd.DataFrame([new])], ignore_index=True)
                        sync_db(st.session_state.alert_db)
                        st.session_state.edit_ticker = ""; st.session_state.edit_price = 0.0; st.session_state.edit_note = ""
                        st.success("Saved!")
                        st.rerun()

    # 2. CALCULATOR TAB (FULL)
    with tab_calc:
        st.markdown("### 🧠 Smart SL")
        calc_ticker = st.text_input("Stock Ticker", placeholder="Ticker...", key="calc_t").upper()
        current_val = 0.0
        if calc_ticker:
            try:
                data = yf.Ticker(calc_ticker).history(period='1d')['Close']
                if not data.empty: current_val = float(data.iloc[-1])
            except: pass
        max_rng = current_val * 2 if current_val > 0 else 1000.0
        val_default = current_val if current_val > 0 else 0.0
        buy_price = st.slider("Buy Price ($)", min_value=0.0, max_value=max_rng, value=val_default, step=0.1)
        if st.button("Calculate", type="primary"):
            if calc_ticker:
                with st.spinner("Analyzing..."):
                    res, err = calculate_smart_sl(calc_ticker, buy_price)
                    if err: st.error(err)
                    else: st.session_state.calc_res = res; st.session_state.calc_ticker = calc_ticker
        if 'calc_res' in st.session_state:
            res = st.session_state.calc_res; tkr = st.session_state.calc_ticker
            st.markdown(f"""<div style="background:#262730; padding:15px; border-radius:10px; border-left:5px solid #FFC107;"><h3 style="margin-top:0;">{tkr} Analysis</h3><div style="font-size:1.5rem; font-weight:bold; color:#FFC107;">SL: ${res['sl_price']:,.2f}</div><div>Reason: {res['reason']}</div><div>Trend: {res['trend']}</div></div>""", unsafe_allow_html=True)
            if st.button(f"🔔 Set Alert"):
                sl_target = round(res['sl_price'], 2)
                if is_duplicate_alert(tkr, sl_target, "Down"): st.warning("Active!")
                else:
                    new = {"ticker": tkr, "target_price": sl_target, "current_price": res['current_price'], "direction": "Down", "notes": f"Smart SL", "created_at": str(datetime.now()), "status": "Active", "triggered_at": ""}
                    st.session_state.alert_db = pd.concat([st.session_state.alert_db, pd.DataFrame([new])], ignore_index=True)
                    sync_db(st.session_state.alert_db); st.success("Set!"); time.sleep(1); st.rerun()

    # 3. HISTORY TAB (FULL)
    with tab_hist:
        st.markdown("### 📜 Log")
        hist_view = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Completed']
        if not hist_view.empty:
            for idx, row in hist_view[::-1].iterrows(): st.info(f"✅ {row['ticker']} - ${float(row['target_price']):.2f} on {row['triggered_at']}")
            if st.button("🗑️ Clear Log"):
                st.session_state.alert_db = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
                sync_db(st.session_state.alert_db); st.rerun()
        else: st.caption("Empty.")

if __name__ == "__main__":
    main()
