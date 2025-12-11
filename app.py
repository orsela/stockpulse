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
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 0. CONFIGURATION & SECRETS
# ==========================================
st.set_page_config(page_title="StockPulse Terminal", page_icon="⚡", layout="wide")

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
    """מושך נתוני מדדים בזמן אמת עבור הדשבורד"""
    tickers = {'S&P 500': '^GSPC', 'Nasdaq': '^IXIC', 'VIX': '^VIX', 'Bitcoin': 'BTC-USD'}
    try:
        data = yf.download(list(tickers.values()), period="1d", progress=False)['Close']
        results = {}
        for name, symbol in tickers.items():
            try:
                # טיפול בפורמטים שונים של yfinance
                if len(tickers) == 1: price = data.iloc[-1].item()
                else: price = data[symbol].iloc[-1]
                
                # חישוב שינוי יומי (פשוט להמחשה, אפשר לשכלל)
                open_price = yf.Ticker(symbol).history(period='1d')['Open'].iloc[-1]
                delta = ((price - open_price) / open_price) * 100
                results[name] = (price, delta)
            except:
                results[name] = (0.0, 0.0)
        return results
    except:
        return {k: (0.0, 0.0) for k in tickers}

# ==========================================
# 3. ANALYSIS FUNCTIONS (Smart SL)
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
        if final_sl < sl_max_loss:
            final_sl = sl_max_loss
            reason = "Max Loss Limit (12%)"
            
        if curr_price > ma150 and final_sl < ma150:
            final_sl = ma150
            reason = "MA150 Support Rule"
        
        if final_sl >= curr_price:
            final_sl = curr_price * 0.99
            reason = "Immediate Exit (Price violated rules)"

        trend = "UP 🟢" if curr_price > ma150 else "DOWN 🔴"
        return {"ma150": ma150, "atr": atr, "trend": trend, "sl_price": final_sl, "current_price": curr_price, "reason": reason, "entry": entry}, None
    except Exception as e: return None, str(e)

# ==========================================
# 4. NOTIFICATIONS & PROCESSING
# ==========================================
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
# 5. UI & CSS (FIXED HIGH CONTRAST)
# ==========================================
def apply_custom_ui():
    st.markdown("""
    <style>
        /* Base App Styling */
        .stApp { background-color: #0e0e0e !important; color: #ffffff; }
        
        /* FIX 1: HIGH CONTRAST INPUTS */
        /* Targets Text Input, Number Input, Selectbox */
        div[data-baseweb="input"] > div, 
        div[data-baseweb="select"] > div, 
        div[data-testid="stNumberInput"] div[data-baseweb="input"] > div {
            background-color: #262730 !important;
            color: #ffffff !important;
            border: 1px solid #555 !important;
        }
        /* Input Text Color */
        input[type="text"], input[type="number"] {
            color: #ffffff !important;
            caret-color: #ffffff !important; /* The typing cursor */
        }
        /* Dropdown Text Color */
        div[data-baseweb="select"] span {
            color: #ffffff !important;
        }
        /* Labels */
        label {
            color: #ffc107 !important;
            font-weight: bold !important;
        }

        /* Dashboard Metrics */
        .metric-card {
            background-color: #1c1c1e;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
        }
        
        /* Alert Cards */
        .sticky-note { 
            background: #F9E79F; 
            color: #000 !important; 
            padding: 10px; 
            border-radius: 8px; 
            margin-bottom: 10px; 
            box-shadow: 2px 2px 10px rgba(0,0,0,0.5); 
        }
        /* Fix text inside sticky note (black text on yellow) */
        .sticky-note b, .sticky-note span, .sticky-note small {
            color: #000000 !important;
        }

        /* Buttons */
        button[kind="primary"] {
            background-color: #FF4B4B !important;
            color: white !important;
            border: none;
        }
        button[kind="secondary"] {
            border: 1px solid #555 !important;
            color: #eee !important;
        }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 6. MAIN APP
# ==========================================
def main():
    apply_custom_ui()
    
    # Init State
    if 'user_email' not in st.session_state: st.session_state.user_email = ""
    if 'user_phone' not in st.session_state: st.session_state.user_phone = ""
    if 'processed_msgs' not in st.session_state: st.session_state.processed_msgs = set()
    if 'alert_db' not in st.session_state: st.session_state.alert_db = load_data_from_db()
    
    # State for Editing
    if 'edit_ticker' not in st.session_state: st.session_state.edit_ticker = ""
    if 'edit_price' not in st.session_state: st.session_state.edit_price = 0.0
    if 'edit_note' not in st.session_state: st.session_state.edit_note = ""

    st.markdown("<h1 style='text-align: center; color: #FFC107;'>⚡ StockPulse Terminal</h1>", unsafe_allow_html=True)

    # --- 4. MARKET DASHBOARD (RESTORED) ---
    with st.container():
        st.markdown("### 🌍 Market Status")
        m_cols = st.columns(4)
        market_data = get_market_status()
        
        metrics = [("S&P 500", "S&P 500"), ("Nasdaq", "Nasdaq"), ("VIX", "VIX"), ("Bitcoin", "Bitcoin")]
        for i, (label, key) in enumerate(metrics):
            val, delta = market_data[key]
            color = "normal" if key == "VIX" else ("inverse" if delta < 0 else "normal") # VIX acts opposite usually, but keeping simple
            with m_cols[i]:
                st.metric(label=label, value=f"{val:,.2f}", delta=f"{delta:.2f}%")
        st.markdown("---")

    # --- SETTINGS ---
    with st.expander("⚙️ Settings & Connection", expanded=False):
        c1, c2 = st.columns(2)
        with c1: st.text_input("Email", key="temp_email", value=st.session_state.user_email)
        with c2: st.text_input("WhatsApp", key="temp_phone", value=st.session_state.user_phone)
        
        # FIX 5: Primary Button for Visibility
        if st.button("Save Connection Settings", type="primary"):
            st.session_state.user_email = st.session_state.temp_email
            st.session_state.user_phone = st.session_state.temp_phone
            st.success("✅ Settings Saved Successfully!")
        
        auto_poll = st.toggle("🔄 Auto-Poll (60s)", value=False)
        if auto_poll:
            check_alerts()
            time.sleep(60)
            st.rerun()

    # --- TABS ---
    tab_alerts, tab_calc, tab_hist = st.tabs(["🔔 Active Alerts", "🛡️ Smart SL Calculator", "📂 History Log"])
    
    # 1. ALERTS TAB
    with tab_alerts:
        col_list, col_add = st.columns([2, 1])
        active_view = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
        
        with col_list:
            if not active_view.empty:
                for idx, row in active_view.iterrows():
                    # Card UI
                    st.markdown(f"""
                    <div class="sticky-note">
                        <div style="display:flex; justify-content:space-between;">
                            <span style="font-size:1.2em; font-weight:bold;">{row['ticker']}</span> 
                            <span style="font-weight:bold;">Target: ${float(row['target_price']):.2f}</span>
                        </div>
                        <div style="font-size:0.9em;">
                             Current: ${float(row['current_price']):.2f} | {row['direction']} | {row['notes']}
                        </div>
                    </div>""", unsafe_allow_html=True)
                    
                    # FIX 2: Edit & Delete Buttons
                    b1, b2 = st.columns([1, 4])
                    with b1:
                        if st.button(f"✏️", key=f"edit_{idx}", help="Edit this alert"):
                            st.session_state.edit_ticker = row['ticker']
                            st.session_state.edit_price = float(row['target_price'])
                            st.session_state.edit_note = row['notes']
                            # Remove old one so we don't duplicate
                            st.session_state.alert_db.drop(idx, inplace=True)
                            st.session_state.alert_db.reset_index(drop=True, inplace=True)
                            sync_db(st.session_state.alert_db)
                            st.toast(f"Editing {row['ticker']}... Check the form on the right.")
                            st.rerun()
                    with b2:
                        if st.button(f"🗑️ Delete", key=f"del_{idx}"):
                            st.session_state.alert_db.drop(idx, inplace=True)
                            st.session_state.alert_db.reset_index(drop=True, inplace=True)
                            sync_db(st.session_state.alert_db)
                            st.rerun()
            else:
                st.info("No active alerts.")

        with col_add:
            st.markdown("### ➕ Add / Edit Alert")
            with st.form("add_alert"):
                # Pre-fill if editing
                def_t = st.session_state.edit_ticker if st.session_state.edit_ticker else ""
                def_p = st.session_state.edit_price if st.session_state.edit_price else 0.0
                def_n = st.session_state.edit_note if st.session_state.edit_note else ""

                t = st.text_input("Ticker", value=def_t).upper()
                p = st.number_input("Target Price", min_value=0.0, value=def_p, step=0.1)
                d = st.selectbox("Direction", ["Up", "Down"])
                n = st.text_input("Notes", value=def_n)
                
                if st.form_submit_button("Save Alert", type="primary"):
                    if is_duplicate_alert(t, p, d):
                        st.error("⚠️ Alert already exists!")
                    else:
                        new = {
                            "ticker": t, "target_price": p, "current_price": 0.0, 
                            "direction": d, "notes": n, 
                            "created_at": str(datetime.now()), "status": "Active", "triggered_at": ""
                        }
                        st.session_state.alert_db = pd.concat([st.session_state.alert_db, pd.DataFrame([new])], ignore_index=True)
                        sync_db(st.session_state.alert_db)
                        # Clear edit state
                        st.session_state.edit_ticker = ""
                        st.session_state.edit_price = 0.0
                        st.session_state.edit_note = ""
                        st.success(f"Saved {t}!")
                        st.rerun()

    # 2. CALCULATOR TAB
    with tab_calc:
        st.markdown("### 🧠 AI Stop-Loss")
        
        # FIX 3: Slider Implementation
        calc_ticker = st.text_input("Stock Ticker", placeholder="Enter Ticker (e.g. NVDA) to load price...").upper()
        
        current_val = 0.0
        if calc_ticker:
            try:
                # Get current price quickly for slider default
                data = yf.Ticker(calc_ticker).history(period='1d')['Close']
                if not data.empty:
                    current_val = float(data.iloc[-1])
            except: pass
        
        # Slider setup: Max range is 2x current price, default is current price
        max_rng = current_val * 2 if current_val > 0 else 1000.0
        val_default = current_val if current_val > 0 else 0.0
        
        buy_price = st.slider("Purchase Price ($)", min_value=0.0, max_value=max_rng, value=val_default, step=0.1)
        
        if st.button("Calculate Safe Stop", type="primary"):
            if calc_ticker:
                with st.spinner("Analyzing market structure..."):
                    res, err = calculate_smart_sl(calc_ticker, buy_price)
                    if err: st.error(err)
                    else:
                        st.session_state.calc_res = res
                        st.session_state.calc_ticker = calc_ticker
        
        if 'calc_res' in st.session_state:
            res = st.session_state.calc_res
            tkr = st.session_state.calc_ticker
            
            st.markdown(f"""
            <div style="background:#262730; padding:20px; border-radius:10px; border-left:5px solid #FFC107;">
                <h3 style="margin-top:0;">Analysis: {tkr}</h3>
                <div style="font-size:1.5rem; font-weight:bold; color:#FFC107;">Recommended SL: ${res['sl_price']:,.2f}</div>
                <div>Logic: {res['reason']}</div>
                <div>Trend: {res['trend']} | MA150: ${res['ma150']:.2f}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"🔔 Set Stop Loss Alert"):
                sl_target = round(res['sl_price'], 2)
                if is_duplicate_alert(tkr, sl_target, "Down"):
                     st.warning("Stop Loss alert already active!")
                else:
                    new = {
                        "ticker": tkr, "target_price": sl_target, "current_price": res['current_price'],
                        "direction": "Down", "notes": f"Smart SL ({res['reason']})",
                        "created_at": str(datetime.now()), "status": "Active", "triggered_at": ""
                    }
                    st.session_state.alert_db = pd.concat([st.session_state.alert_db, pd.DataFrame([new])], ignore_index=True)
                    sync_db(st.session_state.alert_db)
                    st.success(f"Protection Set for {tkr}!")
                    time.sleep(1)
                    st.rerun()

    # 3. HISTORY TAB
    with tab_hist:
        st.markdown("### 📜 Alert History Log")
        hist_view = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Completed']
        
        if not hist_view.empty:
            for idx, row in hist_view[::-1].iterrows():
                st.info(f"✅ {row['ticker']} - Target ${float(row['target_price']):.2f} reached on {row['triggered_at']}. Note: {row['notes']}")
            
            if st.button("🗑️ Clear History (Keep Active)"):
                st.session_state.alert_db = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
                sync_db(st.session_state.alert_db)
                st.rerun()
        else:
            st.caption("No completed alerts yet.")

if __name__ == "__main__":
    main()
