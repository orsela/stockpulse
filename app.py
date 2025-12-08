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
try:
    SENDER_EMAIL = st.secrets.get("SENDER_EMAIL", "")
    SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD", "")
    TWILIO_SID = st.secrets.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_TOKEN = st.secrets.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM = st.secrets.get("TWILIO_PHONE_NUMBER", "")
    GCP_SECRETS = st.secrets["gcp_service_account"]
except Exception:
    st.error("Error loading secrets. Please check your secrets.toml file.")
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
        st.error(f"❌ Database Error: {e}")
        return None

def load_data_from_db():
    sheet = get_db_connection()
    if not sheet: return pd.DataFrame()
    try:
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame(columns=["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status"])
        expected_cols = ["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status"]
        for col in expected_cols:
            if col not in df.columns: df[col] = ""
        return df
    except:
        return pd.DataFrame(columns=["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status"])

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
# 2. ANALYSIS FUNCTIONS (UPDATED RULES)
# ==========================================
def calculate_smart_sl(ticker, buy_price):
    """
    מחשב סטופ-לוס חכם עם החוקים החדשים:
    1. בסיס: ATR X 2
    2. חוק 1: מקסימום הפסד 12%
    3. חוק 2: לא יורד מתחת ל-MA150 (אם המחיר כרגע מעליו)
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        
        if len(hist) < 150:
            return None, "Not enough data for MA150"
            
        # חישוב אינדיקטורים
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
        
        # מחיר כניסה (אם המשתמש לא הזין, לוקחים מחיר נוכחי)
        entry = buy_price if buy_price > 0 else curr_price
        
        # --- לוגיקת החוקים ---
        
        # 1. חישוב בסיסי (ATR)
        sl_atr = entry - (2 * atr)
        final_sl = sl_atr
        reason = "Volatility (2x ATR)"
        
        # 2. חוק מקסימום הפסד 12% (רצפה קשיחה)
        # הסטופ לא יכול להיות נמוך מ-88% ממחיר הכניסה
        sl_max_loss = entry * 0.88
        if final_sl < sl_max_loss:
            final_sl = sl_max_loss
            reason = "Max Loss Limit (12%)"
            
        # 3. חוק MA150 (תמיכה טכנית)
        # מופעל רק אם המניה כרגע נמצאת מעל הממוצע (מגמת עלייה)
        if curr_price > ma150:
            # הסטופ לא יכול להיות מתחת ל-MA150
            if final_sl < ma150:
                final_sl = ma150
                reason = "MA150 Support Rule"
        
        # הגנה: אם הסטופ המחושב גבוה מהמחיר הנוכחי (למשל מניה קרסה מתחת לממוצע), נתריע
        is_below_sl = False
        if final_sl >= curr_price:
            final_sl = curr_price * 0.99 # נותן סטופ קצת מתחת למחיר הנוכחי ליציאה מיידית
            reason = "Immediate Exit (Price violated rules)"
            is_below_sl = True

        trend = "UP 🟢" if curr_price > ma150 else "DOWN 🔴"
        
        return {
            "ma150": ma150,
            "atr": atr,
            "trend": trend,
            "sl_price": final_sl,
            "current_price": curr_price,
            "reason": reason,
            "entry": entry
        }, None
        
    except Exception as e:
        return None, str(e)

# ==========================================
# 3. NOTIFICATIONS
# ==========================================
def send_email_alert(to_email, ticker, current_price, target_price, direction, notes):
    if not SENDER_EMAIL or not SENDER_PASSWORD: return False, "Secrets missing"
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL; msg['To'] = to_email
        msg['Subject'] = f"🚀 StockPulse Alert: {ticker} hit ${current_price:,.2f}"
        body = f"Ticker: {ticker}\nTrigger: ${current_price}\nTarget: ${target_price}\nNote: {notes}"
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
        client.messages.create(from_=TWILIO_FROM, body=f"🚀 {ticker} hit ${current_price} ({direction})", to=f"whatsapp:+{clean_digits}")
        return True, "WA Sent"
    except Exception as e: return False, str(e)

# ==========================================
# 4. CSS
# ==========================================
def apply_custom_ui():
    st.markdown("""
    <style>
        .stApp { background-color: #0e0e0e !important; color: #ffffff; }
        div[data-testid="stTextInput"] input { color: #fff !important; }
        .metric-container { background: #1c1c1e; border: 1px solid #333; border-radius: 8px; padding: 10px; text-align: center; }
        .recommendation-box { background: #262730; border: 1px solid #444; border-left: 4px solid #FFC107; padding: 20px; margin-top: 10px; border-radius: 8px; }
        .stat-value { font-size: 1.8rem; font-weight: bold; color: #FFC107; margin: 10px 0; }
        .sticky-note { background: #F9E79F; color: #000 !important; padding: 10px; border-radius: 8px; margin-bottom: 10px; box-shadow: 2px 2px 10px rgba(0,0,0,0.5); }
        .reason-badge { background: #333; color: #aaa; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 5. STATE
# ==========================================
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'user_phone' not in st.session_state: st.session_state.user_phone = ""
if 'processed_msgs' not in st.session_state: st.session_state.processed_msgs = set()
if 'active_alerts' not in st.session_state: st.session_state.active_alerts = load_data_from_db()
if not st.session_state.active_alerts.empty and 'status' not in st.session_state.active_alerts.columns:
    st.session_state.active_alerts['status'] = 'Active'
if 'completed_alerts' not in st.session_state:
    st.session_state.completed_alerts = pd.DataFrame(columns=["ticker", "target_price", "final_price", "alert_time", "direction", "notes"])

# ==========================================
# 6. LOGIC
# ==========================================
def process_incoming_whatsapp():
    if not TWILIO_SID: return
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        raw_phone = str(st.session_state.user_phone)
        digits_only = re.sub(r'\D', '', raw_phone)
        if digits_only.startswith("0"): digits_only = "972" + digits_only[1:]
        expected_sender = f"whatsapp:+{digits_only}"
        messages = client.messages.list(limit=10, to=TWILIO_FROM)
        changes = False
        for msg in messages:
            if msg.direction == 'inbound' and msg.from_ == expected_sender and msg.sid not in st.session_state.processed_msgs:
                st.session_state.processed_msgs.add(msg.sid)
                match = re.match(r"^([A-Z]+)\s+(\d+(\.\d+)?)$", msg.body.strip().upper())
                if match:
                    new = {"ticker": match.group(1), "target_price": float(match.group(2)), "current_price": 0.0, "direction": "Up", "notes": "WA Add", "created_at": str(datetime.now()), "status": "Active"}
                    st.session_state.active_alerts = pd.concat([st.session_state.active_alerts, pd.DataFrame([new])], ignore_index=True)
                    changes = True
                    st.toast(f"Added via WA: {match.group(1)}")
        if changes: sync_db(st.session_state.active_alerts)
    except: pass

def check_alerts():
    process_incoming_whatsapp()
    if st.session_state.active_alerts.empty: return
    
    active_mask = st.session_state.active_alerts['status'] != 'Completed'
    if not active_mask.any(): return
    active_df = st.session_state.active_alerts[active_mask]
    
    tickers = active_df['ticker'].unique().tolist()
    if not tickers: return
    
    try:
        data = yf.download(tickers, period="1d", progress=False)['Close']
        if len(tickers) == 1:
            current_prices = {tickers[0]: data.iloc[-1].item()}
        else:
            current_prices = data.iloc[-1].to_dict()
    except: return

    changes = False
    for idx, row in active_df.iterrows():
        tkr = row['ticker']
        price = current_prices.get(tkr, 0)
        if price > 0:
            real_idx = st.session_state.active_alerts.index[st.session_state.active_alerts['created_at'] == row['created_at']].tolist()[0]
            st.session_state.active_alerts.at[real_idx, 'current_price'] = price
            
            tgt = float(row['target_price'])
            direct = row['direction']
            
            if (direct == "Up" and price >= tgt) or (direct == "Down" and price <= tgt):
                if st.session_state.user_email: send_email_alert(st.session_state.user_email, tkr, price, tgt, direct, row['notes'])
                if st.session_state.user_phone: send_whatsapp_alert(st.session_state.user_phone, tkr, price, tgt, direct)
                
                st.session_state.active_alerts.at[real_idx, 'status'] = 'Completed'
                st.session_state.completed_alerts = pd.concat([st.session_state.completed_alerts, pd.DataFrame([row])], ignore_index=True)
                changes = True
                st.toast(f"🔥 Alert Triggered: {tkr}")
    
    if changes:
        st.session_state.active_alerts = st.session_state.active_alerts[st.session_state.active_alerts['status'] != 'Completed']
        st.session_state.active_alerts.reset_index(drop=True, inplace=True)
        sync_db(st.session_state.active_alerts)
        st.rerun()

# ==========================================
# 7. UI
# ==========================================
def main():
    apply_custom_ui()
    st.markdown("<h1 style='text-align: center; color: #FFC107;'>⚡ StockPulse Terminal</h1>", unsafe_allow_html=True)
    
    # SETTINGS
    with st.expander("⚙️ Settings & Connection", expanded=False):
        c1, c2 = st.columns(2)
        with c1: st.text_input("Email", key="temp_email", value=st.session_state.user_email)
        with c2: st.text_input("WhatsApp", key="temp_phone", value=st.session_state.user_phone)
        if st.button("Save Settings"):
            st.session_state.user_email = st.session_state.temp_email
            st.session_state.user_phone = st.session_state.temp_phone
            st.success("Saved!")
        st.markdown("---")
        auto_poll = st.toggle("🔄 Auto-Poll (60s)", value=False)
        if auto_poll:
            st.caption("Polling active...")
            check_alerts()
            time.sleep(60)
            st.rerun()
    
    tab_alerts, tab_calc, tab_hist = st.tabs(["🔔 Active Alerts", "🛡️ Smart SL Calculator", "📂 History"])
    
    # ALERTS TAB
    with tab_alerts:
        col_list, col_add = st.columns([2, 1])
        with col_list:
            if not st.session_state.active_alerts.empty:
                for idx, row in st.session_state.active_alerts.iterrows():
                    st.markdown(f"""
                    <div class="sticky-note">
                        <b>{row['ticker']}</b> | Target: <b>${row['target_price']}</b> ({row['direction']})<br>
                        <small>Current: ${float(row['current_price']):.2f} | {row['notes']}</small>
                    </div>""", unsafe_allow_html=True)
                    if st.button(f"🗑️ Delete {row['ticker']}", key=f"del_{idx}"):
                        st.session_state.active_alerts.drop(idx, inplace=True)
                        st.session_state.active_alerts.reset_index(drop=True, inplace=True)
                        sync_db(st.session_state.active_alerts)
                        st.rerun()
            else: st.info("No active alerts.")

        with col_add:
            st.markdown("### ➕ Manual Add")
            with st.form("add_alert"):
                t = st.text_input("Ticker").upper()
                p = st.number_input("Target Price", min_value=0.0)
                d = st.selectbox("Direction", ["Up", "Down"])
                n = st.text_input("Notes")
                if st.form_submit_button("Add Alert"):
                    new = {"ticker": t, "target_price": p, "current_price": 0.0, "direction": d, "notes": n, "created_at": str(datetime.now()), "status": "Active"}
                    st.session_state.active_alerts = pd.concat([st.session_state.active_alerts, pd.DataFrame([new])], ignore_index=True)
                    sync_db(st.session_state.active_alerts)
                    st.rerun()

    # CALCULATOR TAB (IMPROVED)
    with tab_calc:
        st.markdown("### 🧠 Smart Stop-Loss AI")
        st.info("Calculates optimal SL based on: 1. Volatility (ATR) 2. Max 12% Loss Rule 3. MA150 Support")
        
        cc1, cc2 = st.columns(2)
        with cc1: calc_ticker = st.text_input("Stock Ticker", placeholder="e.g. NVDA").upper()
        with cc2: buy_price = st.number_input("Purchase Price ($)", min_value=0.0, step=0.1)
        
        if st.button("🔍 Calculate Safe Stop"):
            if calc_ticker:
                with st.spinner(f"Analyzing {calc_ticker} market structure..."):
                    res, err = calculate_smart_sl(calc_ticker, buy_price)
                    if err:
                        st.error(f"Error: {err}")
                    else:
                        st.session_state.calc_res = res
                        st.session_state.calc_ticker = calc_ticker
            else: st.warning("Enter a ticker.")

        if 'calc_res' in st.session_state:
            res = st.session_state.calc_res
            tkr = st.session_state.calc_ticker
            
            st.markdown(f"""
            <div class="recommendation-box">
                <h3 style='margin:0'>{tkr} Analysis</h3>
                <div style="display: flex; gap: 20px; margin-top: 10px;">
                    <div>📉 <b>MA150:</b> ${res['ma150']:,.2f}</div>
                    <div>📊 <b>ATR:</b> ${res['atr']:,.2f}</div>
                    <div>🚪 <b>Entry:</b> ${res['entry']:,.2f}</div>
                </div>
                <hr style="border-color: #444;">
                <div style="color: #aaa; font-size: 0.9rem;">Determining Factor: <span class="reason-badge">{res['reason']}</span></div>
                <div class="stat-value">Recommended SL: ${res['sl_price']:,.2f}</div>
                <div style="color: {('#4CAF50' if 'UP' in res['trend'] else '#FF5252')}; font-weight:bold;">Trend: {res['trend']}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"🔔 Set Stop Loss Alert at ${res['sl_price']:.2f}"):
                new = {
                    "ticker": tkr,
                    "target_price": round(res['sl_price'], 2),
                    "current_price": res['current_price'],
                    "direction": "Down",
                    "notes": f"Smart SL ({res['reason']})",
                    "created_at": str(datetime.now()),
                    "status": "Active"
                }
                st.session_state.active_alerts = pd.concat([st.session_state.active_alerts, pd.DataFrame([new])], ignore_index=True)
                sync_db(st.session_state.active_alerts)
                st.success(f"Protection Set for {tkr}!")
                time.sleep(1)
                st.rerun()

    # HISTORY TAB
    with tab_hist:
        st.dataframe(st.session_state.completed_alerts, use_container_width=True)

if __name__ == "__main__":
    main()
