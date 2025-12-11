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
# 1. DATABASE FUNCTIONS (Google Sheets)
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
        
        # עמודות חובה - כולל triggered_at לתיעוד היסטוריה
        expected_cols = ["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status", "triggered_at"]
        
        if df.empty:
            return pd.DataFrame(columns=expected_cols)
            
        # השלמת עמודות חסרות אם ישנן
        for col in expected_cols:
            if col not in df.columns: df[col] = ""
            
        return df
    except Exception as e:
        st.error(f"Error reading DB: {e}")
        return pd.DataFrame(columns=["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status", "triggered_at"])

def sync_db(df):
    """שמירת כל המידע (פעילים + היסטוריה) חזרה לשיט"""
    sheet = get_db_connection()
    if not sheet: return
    
    # המרת הכל ל-String למניעת בעיות JSON ב-Gspread
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
    """מוודא שלא קיימת התראה זהה בסטטוס פעיל"""
    if st.session_state.alert_db.empty: return False
    
    # מסנן רק התראות פעילות
    active_mask = st.session_state.alert_db['status'] == 'Active'
    df_active = st.session_state.alert_db[active_mask]
    
    if df_active.empty: return False

    # בודק האם יש שורה עם אותם נתונים בדיוק (טיקר, מחיר, כיוון)
    # שימוש ב-float כדי למנוע אי התאמה בין 150 ל-150.0
    try:
        target_float = float(target)
        # יצירת עמודת עזר להשוואה
        check_df = df_active.copy()
        check_df['target_float'] = pd.to_numeric(check_df['target_price'], errors='coerce')
        
        duplicate = check_df[
            (check_df['ticker'] == ticker) & 
            (check_df['target_float'] == target_float) & 
            (check_df['direction'] == direction)
        ]
        return not duplicate.empty
    except:
        return False

# ==========================================
# 3. ANALYSIS FUNCTIONS (Smart SL)
# ==========================================
def calculate_smart_sl(ticker, buy_price):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        
        if len(hist) < 150:
            return None, "Not enough data for MA150"
            
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
        
        # 1. ATR Logic
        sl_atr = entry - (2 * atr)
        final_sl = sl_atr
        reason = "Volatility (2x ATR)"
        
        # 2. Max Loss 12%
        sl_max_loss = entry * 0.88
        if final_sl < sl_max_loss:
            final_sl = sl_max_loss
            reason = "Max Loss Limit (12%)"
            
        # 3. MA150 Support
        if curr_price > ma150:
            if final_sl < ma150:
                final_sl = ma150
                reason = "MA150 Support Rule"
        
        # Immediate Exit Protection
        if final_sl >= curr_price:
            final_sl = curr_price * 0.99
            reason = "Immediate Exit (Price violated rules)"

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
# 4. NOTIFICATIONS
# ==========================================
def send_email_alert(to_email, ticker, current_price, target_price, direction, notes):
    if not SENDER_EMAIL or not SENDER_PASSWORD: return False, "Secrets missing"
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL; msg['To'] = to_email
        msg['Subject'] = f"🚀 StockPulse Alert: {ticker} hit ${current_price:,.2f}"
        body = f"Ticker: {ticker}\nTrigger: ${current_price}\nTarget: ${target_price}\nDirection: {direction}\nNote: {notes}\n\nTime: {datetime.now()}"
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

# ==========================================
# 5. CORE PROCESS (ALERTS ENGINE)
# ==========================================
def process_incoming_whatsapp():
    """קורא הודעות ווטסאפ ומוסיף אותן למערכת"""
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
                
                # Parsing: "NVDA 140"
                match = re.match(r"^([A-Z]+)\s+(\d+(\.\d+)?)$", msg.body.strip().upper())
                if match:
                    t, p = match.group(1), float(match.group(2))
                    
                    if not is_duplicate_alert(t, p, "Up"): # הנחת ברירת מחדל שהכיוון הוא UP מווטסאפ
                        new = {
                            "ticker": t, "target_price": p, "current_price": 0.0, 
                            "direction": "Up", "notes": "WA Add", 
                            "created_at": str(datetime.now()), "status": "Active", "triggered_at": ""
                        }
                        st.session_state.alert_db = pd.concat([st.session_state.alert_db, pd.DataFrame([new])], ignore_index=True)
                        changes = True
                        st.toast(f"✅ WA Added: {t}")
                    else:
                        st.toast(f"⚠️ WA Duplicate ignored: {t}")
                        
        if changes: sync_db(st.session_state.alert_db)
    except: pass

def check_alerts():
    """הפונקציה הראשית שבודקת מחירים ושולחת התראות"""
    process_incoming_whatsapp()
    
    if st.session_state.alert_db.empty: return
    
    # עבודה רק על התראות פעילות
    active_indices = st.session_state.alert_db.index[st.session_state.alert_db['status'] == 'Active'].tolist()
    if not active_indices: return
    
    # שליפת מחירים
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
            # עדכון מחיר נוכחי בזיכרון
            st.session_state.alert_db.at[idx, 'current_price'] = price
            
            tgt = float(row['target_price'])
            direct = row['direction']
            
            # בדיקת התנאי
            triggered = (direct == "Up" and price >= tgt) or (direct == "Down" and price <= tgt)
            
            if triggered:
                # 1. שליחת התראה
                if st.session_state.user_email: 
                    send_email_alert(st.session_state.user_email, tkr, price, tgt, direct, row['notes'])
                if st.session_state.user_phone: 
                    send_whatsapp_alert(st.session_state.user_phone, tkr, price, tgt, direct)
                
                # 2. עדכון סטטוס ל-Completed (לא מחיקה!)
                st.session_state.alert_db.at[idx, 'status'] = 'Completed'
                st.session_state.alert_db.at[idx, 'triggered_at'] = str(datetime.now())
                
                st.toast(f"🔥 Triggered: {tkr} at ${price:.2f}")
                changes_made = True
    
    if changes_made:
        sync_db(st.session_state.alert_db)
        st.rerun()

# ==========================================
# 6. UI & MAIN
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
        .history-row { background: #333; padding: 10px; border-radius: 5px; margin-bottom: 5px; border-left: 3px solid #4CAF50; }
    </style>
    """, unsafe_allow_html=True)

def main():
    apply_custom_ui()
    
    # State Init
    if 'user_email' not in st.session_state: st.session_state.user_email = ""
    if 'user_phone' not in st.session_state: st.session_state.user_phone = ""
    if 'processed_msgs' not in st.session_state: st.session_state.processed_msgs = set()
    
    # טעינת נתונים ראשונית - Database אחד לכולם
    if 'alert_db' not in st.session_state: 
        st.session_state.alert_db = load_data_from_db()

    st.markdown("<h1 style='text-align: center; color: #FFC107;'>⚡ StockPulse Terminal</h1>", unsafe_allow_html=True)
    
    # --- SETTINGS ---
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
            st.caption("Polling active... System checking prices.")
            check_alerts()
            time.sleep(60)
            st.rerun()

    # --- TABS ---
    tab_alerts, tab_calc, tab_hist = st.tabs(["🔔 Active Alerts", "🛡️ Smart SL Calculator", "📂 History Log"])
    
    # 1. ACTIVE ALERTS TAB
    with tab_alerts:
        col_list, col_add = st.columns([2, 1])
        
        # יצירת View רק לפעילים
        active_view = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
        
        with col_list:
            if not active_view.empty:
                for idx, row in active_view.iterrows():
                    st.markdown(f"""
                    <div class="sticky-note">
                        <div style="display:flex; justify-content:space-between;">
                            <b>{row['ticker']}</b> 
                            <span>Target: <b>${float(row['target_price']):.2f}</b></span>
                        </div>
                        <small>Current: ${float(row['current_price']):.2f} | {row['direction']} | {row['notes']}</small>
                    </div>""", unsafe_allow_html=True)
                    
                    # כפתור מחיקה (מוחק פיזית כי המשתמש ביקש למחוק, לא כי הושלם)
                    if st.button(f"🗑️ Remove {row['ticker']}", key=f"del_{idx}"):
                        st.session_state.alert_db.drop(idx, inplace=True)
                        st.session_state.alert_db.reset_index(drop=True, inplace=True)
                        sync_db(st.session_state.alert_db)
                        st.rerun()
            else:
                st.info("No active alerts running.")

        with col_add:
            st.markdown("### ➕ Add Alert")
            with st.form("add_alert"):
                t = st.text_input("Ticker").upper()
                p = st.number_input("Target Price", min_value=0.0)
                d = st.selectbox("Direction", ["Up", "Down"])
                n = st.text_input("Notes")
                
                if st.form_submit_button("Create"):
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
                        st.success(f"Added {t}!")
                        st.rerun()

    # 2. CALCULATOR TAB
    with tab_calc:
        st.markdown("### 🧠 AI Stop-Loss")
        cc1, cc2 = st.columns(2)
        with cc1: calc_ticker = st.text_input("Stock Ticker", placeholder="NVDA").upper()
        with cc2: buy_price = st.number_input("Entry Price ($)", min_value=0.0, step=0.1)
        
        if st.button("Calculate Safe Stop"):
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
            <div class="recommendation-box">
                <h3>{tkr} Analysis</h3>
                <div class="stat-value">SL: ${res['sl_price']:,.2f}</div>
                <div>Reason: {res['reason']}</div>
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
        
        # יצירת View רק להיסטוריה
        hist_view = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Completed']
        
        if not hist_view.empty:
            # מציג מהאחרון לראשון
            for idx, row in hist_view[::-1].iterrows():
                st.markdown(f"""
                <div class="history-row">
                    <b>{row['ticker']}</b> - Target ${float(row['target_price']):.2f} reached.<br>
                    <small style="color:#aaa;">Triggered: {row['triggered_at']} | Note: {row['notes']}</small>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            if st.button("🗑️ Clear History (Keep Active)"):
                st.session_state.alert_db = st.session_state.alert_db[st.session_state.alert_db['status'] == 'Active']
                sync_db(st.session_state.alert_db)
                st.rerun()
        else:
            st.caption("No completed alerts yet.")

if __name__ == "__main__":
    main()
