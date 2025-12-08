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
    # Email & Twilio Secrets
    SENDER_EMAIL = st.secrets.get("SENDER_EMAIL", "")
    SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD", "")
    TWILIO_SID = st.secrets.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_TOKEN = st.secrets.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM = st.secrets.get("TWILIO_PHONE_NUMBER", "")
    
    # Google Sheets Secrets
    GCP_SECRETS = st.secrets["gcp_service_account"]
except Exception:
    st.error("Error loading secrets. Please check your secrets.toml file.")
    st.stop()

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SHEET_NAME = "StockPulse_DB" # השם של הגיליון שיצרת בגוגל

# ==========================================
# 1. DATABASE FUNCTIONS (GOOGLE SHEETS)
# ==========================================
def get_db_connection():
    """יוצר חיבור לגיליון גוגל"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(GCP_SECRETS, scope)
    client = gspread.authorize(creds)
    try:
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        st.error(f"Could not open Google Sheet '{SHEET_NAME}'. Check permissions.")
        return None

def load_data_from_db():
    """טוען את כל ההתראות מהגיליון"""
    sheet = get_db_connection()
    if not sheet: return pd.DataFrame()
    
    try:
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        # אם הגיליון ריק, נחזיר דאטה-פריים ריק עם עמודות
        if df.empty:
            return pd.DataFrame(columns=["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status"])
        return df
    except Exception:
        return pd.DataFrame(columns=["ticker", "target_price", "current_price", "direction", "notes", "created_at", "status"])

def sync_db(df):
    """שומר את הטבלה המעודכנת לגיליון (מוחק וכותב מחדש)"""
    sheet = get_db_connection()
    if not sheet: return
    
    # המרת תאריכים למחרוזות (JSON לא תומך ב-datetime)
    df_save = df.copy()
    if 'created_at' in df_save.columns:
        df_save['created_at'] = df_save['created_at'].astype(str)
        
    try:
        sheet.clear() # ניקוי הגיליון
        # כתיבת כותרות + נתונים
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())
    except Exception as e:
        st.error(f"Error saving to DB: {e}")

# ==========================================
# 2. PAGE SETUP
# ==========================================
st.set_page_config(
    page_title="StockPulse Terminal",
    layout="wide",
    page_icon="💹",
    initial_sidebar_state="collapsed"
)

# ==========================================
# 3. NOTIFICATION FUNCTIONS
# ==========================================
def send_email_alert(to_email, ticker, current_price, target_price, direction, notes):
    if not SENDER_EMAIL or not SENDER_PASSWORD: return False, "Secrets missing"
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = f"🚀 StockPulse Alert: {ticker} hit ${current_price:,.2f}"
        body = f"""<html><body><h2>Stock Alert Triggered!</h2><p><strong>Ticker:</strong> {ticker}</p><p><strong>Trigger Price:</strong> ${current_price:,.2f}</p><p><strong>Target Was:</strong> ${target_price:,.2f} ({direction})</p><p><strong>Notes:</strong> {notes}</p><br><p>Sent from StockPulse Terminal</p></body></html>"""
        msg.attach(MIMEText(body, 'html'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        text = msg.as_string()
        server.sendmail(SENDER_EMAIL, to_email, text)
        server.quit()
        return True, "Email Sent"
    except Exception as e: return False, str(e)

def send_whatsapp_alert(to_number, ticker, current_price, target_price, direction):
    if not TWILIO_SID or not TWILIO_TOKEN or not TWILIO_FROM: return False, "Twilio secrets missing"
    clean_digits = re.sub(r'\D', '', str(to_number))
    if clean_digits.startswith("0"): clean_digits = "972" + clean_digits[1:]
    to_whatsapp = f"whatsapp:+{clean_digits}"
    msg_body = f"🚀 *StockPulse Alert* 🚀\n\n📊 *{ticker}* hit *${current_price:,.2f}*\n🎯 Target: ${target_price:,.2f} ({direction})\n⏱️ Time: {datetime.now().strftime('%H:%M')}"
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(from_=TWILIO_FROM, body=msg_body, to=to_whatsapp)
        return True, "WhatsApp Sent"
    except Exception as e: return False, f"WA Error: {str(e)}"

# ==========================================
# 4. CSS STYLING
# ==========================================
def apply_custom_ui():
    st.markdown("""
    <style>
        .stApp { background-color: #0e0e0e !important; color: #ffffff; }
        div[data-testid="stTextInput"] div[data-baseweb="input-container"] {
            background-color: #e0e0e0 !important; border: 2px solid #FFC107 !important; border-radius: 6px !important;
        }
        div[data-testid="stTextInput"] input { color: #222 !important; background-color: transparent !important; }
        div[data-testid="stTextInput"] input::placeholder { color: #666 !important; opacity: 1; }
        label[data-baseweb="label"] { color: #ffffff !important; }
        .metric-container { background-color: #1c1c1e; border-radius: 8px; padding: 10px; text-align: center; border: 1px solid #333; margin-bottom: 10px; }
        .metric-title { font-size: 0.8rem; color: #aaa; text-transform: uppercase; }
        .metric-value { font-size: 1.3rem; font-weight: bold; color: #fff; }
        .metric-up { color: #4CAF50; } .metric-down { color: #FF5252; }
        .sticky-note { background-color: #F9E79F; color: #222 !important; padding: 15px; border-radius: 4px; margin-bottom: 15px; border-top: 1px solid #fcf3cf; }
        .note-ticker { color: #000 !important; font-size: 1.4rem; font-weight: 800; }
        .note-price, .sticky-note div { color: #333 !important; }
        .target-marker { color: #d32f2f; font-weight: 700; font-size: 1.1rem; }
        .create-form-container { background-color: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 20px; }
        .form-header { color: #FFC107; font-size: 1.5rem; font-weight: bold; margin-bottom: 15px; }
        div.stButton > button { background-color: #FFC107 !important; color: #000000 !important; font-weight: 800 !important; border-radius: 8px !important; }
        .connection-bar { color: #888; font-size: 0.85rem; margin-top: 5px; margin-bottom: 15px; }
        .poll-badge-on { color: #00e676; font-weight: bold; font-size: 0.8rem; border: 1px solid #00e676; padding: 2px 6px; border-radius: 4px; }
        .poll-badge-off { color: #666; font-size: 0.8rem; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 5. STATE & DATA LOADING
# ==========================================
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'user_phone' not in st.session_state: st.session_state.user_phone = ""
if 'temp_email' not in st.session_state: st.session_state.temp_email = ""
if 'temp_phone' not in st.session_state: st.session_state.temp_phone = ""
if 'processed_msgs' not in st.session_state: st.session_state.processed_msgs = set()

# טעינת נתונים מגוגל שיטס בטעינה ראשונה
if 'active_alerts' not in st.session_state:
    with st.spinner('Connecting to Database...'):
        st.session_state.active_alerts = load_data_from_db()

# סינון להצגת התראות פעילות בלבד בלוח (סטטוס = Active או ריק)
if not st.session_state.active_alerts.empty:
    if 'status' not in st.session_state.active_alerts.columns:
         st.session_state.active_alerts['status'] = 'Active'

if 'completed_alerts' not in st.session_state:
    st.session_state.completed_alerts = pd.DataFrame(columns=["ticker", "target_price", "final_price", "alert_time", "direction", "notes"])

REFRESH_RATE = 60

@st.cache_data(ttl=REFRESH_RATE)
def get_live_data(tickers):
    if not tickers: return {}
    live_data = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            curr = info.get('regularMarketPrice', info.get('currentPrice', None))
            prev = info.get('previousClose', None)
            price = curr if curr not in (None, "N/A") else prev
            ma150 = info.get('twoHundredDayAverage', info.get('fiftyDayAverage', 0))
            live_data[ticker] = {"price": price if price else 0.0, "MA150": ma150 if ma150 else 0.0}
        except: live_data[ticker] = {"price": 0.0, "MA150": 0.0}
    return live_data

# ==========================================
# 6. LOGIC & WORKFLOW
# ==========================================
def process_incoming_whatsapp():
    if not TWILIO_SID or not TWILIO_TOKEN or not st.session_state.user_phone: return
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        raw_phone = str(st.session_state.user_phone)
        digits_only = re.sub(r'\D', '', raw_phone)
        if digits_only.startswith("0"): digits_only = "972" + digits_only[1:]
        expected_sender = f"whatsapp:+{digits_only}"
        
        messages = client.messages.list(limit=15, to=TWILIO_FROM)
        changes = False
        
        for msg in messages:
            is_inbound = (msg.direction == 'inbound')
            is_from_user = (msg.from_ == expected_sender)
            is_new = (msg.sid not in st.session_state.processed_msgs)
            
            if is_inbound and is_from_user and is_new:
                st.session_state.processed_msgs.add(msg.sid)
                body = msg.body.strip().upper()
                match = re.match(r"^([A-Z]+)\s+(\d+(\.\d+)?)$", body)
                if match:
                    ticker = match.group(1)
                    target = float(match.group(2))
                    new_alert = {"ticker": ticker, "target_price": target, "current_price": 0.0, "direction": "Up", "notes": "Added via WhatsApp", "created_at": str(datetime.now()), "status": "Active"}
                    st.session_state.active_alerts = pd.concat([st.session_state.active_alerts, pd.DataFrame([new_alert])], ignore_index=True)
                    changes = True
                    st.toast(f"📱 WhatsApp: Added {ticker} @ {target}", icon="✅")
        
        if changes:
            sync_db(st.session_state.active_alerts) # שמירה ל-DB
            
    except Exception: pass

def check_alerts():
    process_incoming_whatsapp()
    
    # עבודה רק על התראות פעילות
    if st.session_state.active_alerts.empty: return
    
    # סינון: רק שורות שהסטטוס שלהן לא 'Completed'
    active_mask = st.session_state.active_alerts['status'] != 'Completed'
    if not active_mask.any(): return
    
    active_df = st.session_state.active_alerts[active_mask]
    tickers = active_df['ticker'].unique().tolist()
    live_data = get_live_data(tickers)
    
    changes_made = False
    
    for idx, row in active_df.iterrows():
        tkr = row['ticker']
        tgt = row['target_price']
        direct = row['direction']
        
        if tkr in live_data and live_data[tkr]['price'] != 0.0:
            cur = live_data[tkr]['price']
            # עדכון מחיר בטבלה הראשית (בזיכרון)
            st.session_state.active_alerts.at[idx, 'current_price'] = cur
            
            trig = (direct == "Up" and cur >= tgt) or (direct == "Down" and cur <= tgt)
            if trig:
                log = []
                if st.session_state.user_email:
                    ok, _ = send_email_alert(st.session_state.user_email, tkr, cur, tgt, direct, row['notes'])
                    log.append(f"Email: {'✅' if ok else '❌'}")
                if st.session_state.user_phone:
                    ok, _ = send_whatsapp_alert(st.session_state.user_phone, tkr, cur, tgt, direct)
                    log.append(f"WA: {'✅' if ok else '❌'}")
                if not log: log.append("Local Only")
                
                # העברה להיסטוריה
                new_hist = {"ticker": tkr, "target_price": tgt, "final_price": cur, "alert_time": str(datetime.now()), "direction": direct, "notes": row['notes'] + f" ({' | '.join(log)})"}
                st.session_state.completed_alerts = pd.concat([st.session_state.completed_alerts, pd.DataFrame([new_hist])], ignore_index=True)
                
                # סימון כהושלם בטבלה הראשית (במקום מחיקה, כדי לשמור ב-DB אם רוצים)
                # במקרה שלנו, נמחק מהתצוגה הפעילה
                st.session_state.active_alerts.at[idx, 'status'] = 'Completed'
                changes_made = True
                
                st.toast(f"🚀 Alert: {tkr} @ ${cur:,.2f}\n{' | '.join(log)}", icon="🔥")

    if changes_made:
        # שמירת השינויים (כולל סטטוס Completed) לגיליון
        # ננקה מהזיכרון התראות שהושלמו כדי שלא יכבידו על התצוגה, אך ב-DB הן יישארו? 
        # לטובת הפשטות: אנחנו מוחקים מהזיכרון ומה-DB שורות שהושלמו (כמו בקוד המקורי),
        # ושומרים אותן רק בטבלה המקומית של ההיסטוריה (completed_alerts).
        
        # 1. שמירת ההיסטוריה (אופציונלי: אפשר לשמור לגיליון נפרד, כרגע זה מקומי)
        
        # 2. מחיקת Completed מה-Active Alerts
        st.session_state.active_alerts = st.session_state.active_alerts[st.session_state.active_alerts['status'] != 'Completed']
        st.session_state.active_alerts.reset_index(drop=True, inplace=True)
        
        # 3. סנכרון ל-Google Sheets
        sync_db(st.session_state.active_alerts)
        st.rerun()

@st.cache_data(ttl=300) 
def get_market_data_real():
    inds = {"S&P 500": "^GSPC", "BITCOIN": "BTC-USD", "VIX": "^VIX", "NASDAQ": "^IXIC"}
    res = []
    for n, t in inds.items():
        try:
            h = yf.Ticker(t).history(period="1mo")
            if not h.empty:
                last = h['Close'].iloc[-1]
                prev = h['Close'].iloc[-2] if len(h) >= 2 else last
                d = "up" if last >= prev else "down"
                res.append((n, f"{last:,.2f}", d))
            else: res.append((n, "N/A", "down"))
        except: res.append((n, "Error", "down"))
    return res

# ==========================================
# 7. UI COMPONENTS
# ==========================================
def render_header_settings():
    st.markdown("### <span style='color: #FFC107;'>Notification Settings ⚙️</span>", unsafe_allow_html=True)
    st.caption("Define where you want to receive real-time alerts. Click 'Save' to persist.")
    with st.form("settings_form"):
        c1, c2 = st.columns(2)
        with c1: st.text_input("📧 Email", key="temp_email", value=st.session_state.user_email, placeholder="name@company.com")
        with c2: st.text_input("📱 WhatsApp", key="temp_phone", value=st.session_state.user_phone, placeholder="050-1234567")
        c_sub, c_clear = st.columns([1, 1])
        with c_sub: 
            if st.form_submit_button("💾 Save Settings", use_container_width=True):
                st.session_state.user_email = st.session_state.temp_email
                st.session_state.user_phone = st.session_state.temp_phone
                st.success("Settings Saved!")
        with c_clear:
            if st.form_submit_button("🧹 Clear", use_container_width=True):
                st.session_state.user_email = ""; st.session_state.user_phone = ""
                st.rerun()
    st.markdown("---")
    col_auto, col_status = st.columns([0.3, 0.7])
    with col_auto: auto_poll = st.toggle("🔄 Auto-Poll (60s)", value=False)
    with col_status:
        if auto_poll:
            st.markdown("<span class='poll-badge-on'>Listening for messages...</span>", unsafe_allow_html=True)
            time.sleep(60); st.rerun()
        else: st.markdown("<span class='poll-badge-off'>Auto-poll disabled</span>", unsafe_allow_html=True)

def render_top_bar():
    metrics = get_market_data_real()
    cols = st.columns(4)
    for i, (name, val, direction) in enumerate(metrics):
        if i < 4:
            arrow = "⬇" if direction == "down" else "⬆"
            cls = "metric-down" if direction == "down" else "metric-up"
            with cols[i]: st.markdown(f"""<div class="metric-container"><div class="metric-title">{name}</div><div class="metric-value">{val}</div><div class="{cls}">{arrow}</div></div>""", unsafe_allow_html=True)

def render_sticky_note(ticker, live_data, alert_row, index):
    data = live_data.get(ticker, {})
    price = data.get('price', 0.0); ma150 = data.get('MA150', 0.0)
    target = alert_row['target_price']; direction = alert_row['direction']; notes = alert_row['notes']
    arrow = "⬆" if direction == "Up" else "⬇"
    st.markdown(f"""<div class="sticky-note"><div class="note-header"><div class="note-ticker">{ticker}</div><div class="target-marker">{arrow} 🎯 ${target:,.2f}</div></div><div class="note-price">Current: ${price:,.2f}</div><div style="font-size: 0.9em; margin-top:5px;">MA150: ${ma150:,.2f} | Dir: {direction}</div><div style="margin-top: 10px; font-style: italic; background: rgba(255,255,255,0.3); padding: 5px; border-radius: 4px;">"{notes}"</div></div>""", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 1])
    with c1:
        with st.popover("✏️ Edit", use_container_width=True):
            ed_t = st.text_input("Ticker", value=ticker, key=f"et_{index}")
            ed_p = st.number_input("Price", value=float(target), key=f"ep_{index}")
            ed_d = st.selectbox("Dir", ["Up", "Down"], index=0 if direction=="Up" else 1, key=f"ed_{index}")
            ed_n = st.text_area("Notes", value=notes, key=f"en_{index}")
            if st.button("Save", key=f"sv_{index}"):
                st.session_state.active_alerts.at[index, 'ticker'] = ed_t.upper()
                st.session_state.active_alerts.at[index, 'target_price'] = ed_p
                st.session_state.active_alerts.at[index, 'direction'] = ed_d
                st.session_state.active_alerts.at[index, 'notes'] = ed_n
                sync_db(st.session_state.active_alerts) # Sync on Edit
                st.rerun()
    with c2:
        if st.button("🗑️ Del", key=f"del_{index}", use_container_width=True):
            st.session_state.active_alerts.drop(index, inplace=True)
            st.session_state.active_alerts.reset_index(drop=True, inplace=True)
            sync_db(st.session_state.active_alerts) # Sync on Delete
            st.rerun()

# ==========================================
# 8. MAIN APP
# ==========================================
def main():
    apply_custom_ui()
    st.markdown("<h1 style='text-align: center; color: #FFC107;'>⚡ StockPulse Terminal</h1>", unsafe_allow_html=True)
    render_header_settings()
    render_top_bar()
    st.markdown("<div class='connection-bar'><span class='connection-dot'></span><span>Connected to price server</span></div>", unsafe_allow_html=True)
    check_alerts()
    st.write("---")
    
    col_alerts, col_create = st.columns([1.2, 1], gap="large")
    with col_alerts:
        st.markdown("### 🔔 Active Alerts")
        if not st.session_state.active_alerts.empty:
            tickers = st.session_state.active_alerts['ticker'].tolist()
            live_data = get_live_data(tickers)
            cols = st.columns(2)
            for i, row in st.session_state.active_alerts.iterrows():
                with cols[i % 2]:
                    render_sticky_note(row['ticker'], live_data, row, i)
        else: st.info("No active alerts.")
            
    with col_create:
        st.markdown('<div class="create-form-container"><div class="form-header">➕ Create New Alert</div>', unsafe_allow_html=True)
        with st.form("create_alert_form", clear_on_submit=True):
            t_in = st.text_input("Ticker", placeholder="e.g. NVDA").upper()
            c1, c2 = st.columns(2)
            with c1: p_in = st.slider("Target", 0.0, 2000.0, 200.0)
            with c2: d_in = st.selectbox("Direction", ["Up", "Down"])
            n_in = st.text_area("Notes", placeholder="Strategy details...")
            if st.form_submit_button("ADD NOTIFICATION ➔", use_container_width=True):
                if t_in and p_in > 0:
                    new = {"ticker": t_in, "target_price": p_in, "current_price": 0.0, "direction": d_in, "notes": n_in or "No notes", "created_at": str(datetime.now()), "status": "Active"}
                    st.session_state.active_alerts = pd.concat([st.session_state.active_alerts, pd.DataFrame([new])], ignore_index=True)
                    sync_db(st.session_state.active_alerts) # Sync on Add
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    st.write("---")
    with st.expander("📂 View History"): st.dataframe(st.session_state.completed_alerts, use_container_width=True)

if __name__ == "__main__":
    main()
