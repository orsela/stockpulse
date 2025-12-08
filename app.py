import streamlit as st
import pandas as pd
from datetime import datetime
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from twilio.rest import Client
import re

# ==========================================
# 0. CONFIGURATION & SECRETS
# ==========================================
try:
    SENDER_EMAIL = st.secrets.get("SENDER_EMAIL", "")
    SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD", "")
    TWILIO_SID = st.secrets.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_TOKEN = st.secrets.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM = st.secrets.get("TWILIO_PHONE_NUMBER", "")
except Exception:
    SENDER_EMAIL = ""
    SENDER_PASSWORD = ""
    TWILIO_SID = ""
    TWILIO_TOKEN = ""
    TWILIO_FROM = ""

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ==========================================
# 1. PAGE SETUP
# ==========================================
st.set_page_config(
    page_title="StockPulse Terminal",
    layout="wide",
    page_icon="💹",
    initial_sidebar_state="collapsed"
)

# ==========================================
# 2. NOTIFICATION FUNCTIONS
# ==========================================
def send_email_alert(to_email, ticker, current_price, target_price, direction, notes):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        return False, "Secrets missing"
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
    except Exception as e:
        return False, str(e)

def send_whatsapp_alert(to_number, ticker, current_price, target_price, direction):
    if not TWILIO_SID or not TWILIO_TOKEN or not TWILIO_FROM:
        return False, "Twilio secrets missing"
    clean_number = to_number.strip()
    if clean_number.startswith("0"):
        clean_number = "+972" + clean_number[1:]
    to_whatsapp = f"whatsapp:{clean_number}"
    msg_body = f"🚀 *StockPulse Alert* 🚀\n\n📊 *{ticker}* hit *${current_price:,.2f}*\n🎯 Target: ${target_price:,.2f} ({direction})\n⏱️ Time: {datetime.now().strftime('%H:%M')}"
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(from_=TWILIO_FROM, body=msg_body, to=to_whatsapp)
        return True, "WhatsApp Sent"
    except Exception as e:
        return False, f"WA Error: {str(e)}"

# ==========================================
# 3. CSS STYLING
# ==========================================
def apply_custom_ui():
    st.markdown("""
    <style>
        .stApp { background-color: #0e0e0e !important; color: #ffffff; }
        div[data-testid="stTextInput"] div[data-baseweb="input-container"] {
            background-color: #e0e0e0 !important;
            border: 2px solid #FFC107 !important; border-radius: 6px !important;
        }
        div[data-testid="stTextInput"] input { color: #222 !important; background-color: transparent !important; }
        div[data-testid="stTextInput"] input::placeholder { color: #666 !important; opacity: 1; }
        label[data-baseweb="label"] { color: #ffffff !important; }
        .metric-container {
            background-color: #1c1c1e; border-radius: 8px; padding: 10px;
            text-align: center; border: 1px solid #333; margin-bottom: 10px;
        }
        .metric-title { font-size: 0.8rem; color: #aaa; text-transform: uppercase; }
        .metric-value { font-size: 1.3rem; font-weight: bold; color: #fff; }
        .metric-up { color: #4CAF50; } .metric-down { color: #FF5252; }
        .sticky-note {
            background-color: #F9E79F; color: #222 !important; padding: 15px;
            border-radius: 4px; margin-bottom: 15px; border-top: 1px solid #fcf3cf;
        }
        .note-ticker { color: #000 !important; font-size: 1.4rem; font-weight: 800; }
        .note-price, .sticky-note div { color: #333 !important; }
        .target-marker { color: #d32f2f; font-weight: 700; font-size: 1.1rem; }
        .create-form-container {
            background-color: #1a1a1a; border: 1px solid #333;
            border-radius: 12px; padding: 20px;
        }
        .form-header { color: #FFC107; font-size: 1.5rem; font-weight: bold; margin-bottom: 15px; }
        div.stButton > button {
            background-color: #FFC107 !important; color: #000000 !important; 
            font-weight: 800 !important; border-radius: 8px !important;
        }
        .connection-dot {
            width: 10px; height: 10px; border-radius: 50%; background-color: #00e676;
            display: inline-block; box-shadow: 0 0 8px #00e676; margin-right: 8px;
        }
        .connection-bar { color: #888; font-size: 0.85rem; margin-top: 5px; margin-bottom: 15px; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 4. STATE MANAGEMENT
# ==========================================
if 'user_email' not in st.session_state:
    st.session_state.user_email = ""
if 'user_phone' not in st.session_state:
    st.session_state.user_phone = ""
# שמירת מזהי הודעות שטופלו כדי למנוע כפילויות
if 'processed_msgs' not in st.session_state:
    st.session_state.processed_msgs = set()

if 'active_alerts' not in st.session_state:
    st.session_state.active_alerts = pd.DataFrame([{
        "ticker": "NVDA", "target_price": 950.00, "current_price": 900.00,
        "direction": "Up", "notes": "Strong earnings expected", "created_at": datetime.now()
    }])
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
        except:
            live_data[ticker] = {"price": 0.0, "MA150": 0.0}
    return live_data

# ==========================================
# 5. INCOMING WHATSAPP LOGIC
# ==========================================
def process_incoming_whatsapp():
    """בודק הודעות נכנסות מ-Twilio ויוצר התראות חדשות"""
    # אם אין הגדרות או אין מספר טלפון משתמש, אין מה לבדוק
    if not TWILIO_SID or not TWILIO_TOKEN or not st.session_state.user_phone:
        return

    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        
        # נירמול המספר של המשתמש לפורמט בינלאומי לחיפוש
        user_phone_clean = st.session_state.user_phone.strip()
        if user_phone_clean.startswith("0"):
            user_phone_clean = "+972" + user_phone_clean[1:]
        
        # משיכת 10 ההודעות האחרונות שנשלחו למספר ה-Sandbox
        # הערה: ב-Sandbox, הודעות נכנסות מופיעות בלוגים
        messages = client.messages.list(limit=15, to=TWILIO_FROM)
        
        for msg in messages:
            # בדיקה 1: האם ההודעה הגיעה מהמשתמש שלנו?
            # בדיקה 2: האם כבר טיפלנו בהודעה הזו?
            is_from_user = msg.from_ == f"whatsapp:{user_phone_clean}"
            is_new = msg.sid not in st.session_state.processed_msgs
            
            if is_from_user and is_new:
                body = msg.body.strip().upper() # המרת טקסט לאותיות גדולות
                st.session_state.processed_msgs.add(msg.sid) # סימון שטופל
                
                # ניסיון לפענח פורמט: TICKER PRICE (למשל: TSLA 200)
                # Regex: מילה (טיקר), רווח, מספר (מחיר)
                match = re.match(r"^([A-Z]+)\s+(\d+(\.\d+)?)$", body)
                
                if match:
                    ticker = match.group(1)
                    target = float(match.group(2))
                    
                    # בדיקת כיוון אוטומטית (פשוטה)
                    # נניח ברירת מחדל Up, או ננסה להביא מחיר נוכחי
                    # לטובת המהירות נגדיר Up כברירת מחדל אם לא צוין אחרת, המשתמש יכול לערוך
                    direction = "Up" 
                    
                    new_alert = {
                        "ticker": ticker,
                        "target_price": target,
                        "current_price": 0.0,
                        "direction": direction,
                        "notes": "Added via WhatsApp",
                        "created_at": datetime.now()
                    }
                    
                    st.session_state.active_alerts = pd.concat(
                        [st.session_state.active_alerts, pd.DataFrame([new_alert])], 
                        ignore_index=True
                    )
                    st.toast(f"📱 New WhatsApp Alert: {ticker} @ {target}", icon="✅")
                
    except Exception:
        pass # התעלמות משגיאות חיבור זמניות כדי לא להפריע למערכת

def check_alerts():
    # --- הוספת הבדיקה של ווטסאפ ---
    process_incoming_whatsapp()
    # ------------------------------

    if st.session_state.active_alerts.empty: return
    tickers = st.session_state.active_alerts['ticker'].tolist()
    live_data = get_live_data(tickers)
    to_move = []
    for idx, row in st.session_state.active_alerts.iterrows():
        tkr = row['ticker']
        tgt = row['target_price']
        direct = row['direction']
        if tkr in live_data and live_data[tkr]['price'] != 0.0:
            cur = live_data[tkr]['price']
            st.session_state.active_alerts.loc[idx, 'current_price'] = cur
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
                
                new = {"ticker": tkr, "target_price": tgt, "final_price": cur, "alert_time": datetime.now(), 
                       "direction": direct, "notes": row['notes'] + f" ({' | '.join(log)})"}
                st.session_state.completed_alerts = pd.concat([st.session_state.completed_alerts, pd.DataFrame([new])], ignore_index=True)
                to_move.append(idx)
                st.toast(f"🚀 Alert: {tkr} @ ${cur:,.2f}\n{' | '.join(log)}", icon="🔥")
    if to_move:
        st.session_state.active_alerts.drop(to_move, inplace=True)
        st.session_state.active_alerts.reset_index(drop=True, inplace=True)
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
# 6. UI COMPONENTS & VALIDATION
# ==========================================
def validate_email_callback():
    email = st.session_state.user_email
    if email: 
        pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(pattern, email):
            st.toast("❌ כתובת מייל לא חוקית! הנתון נמחק.", icon="⚠️")
            st.session_state.user_email = ""

def validate_phone_callback():
    phone = st.session_state.user_phone
    if phone:
        pattern = r"^05\d[-]?\d{7}$"
        if not re.match(pattern, phone):
            st.toast("❌ מספר טלפון לא חוקי! יש להזין נייד ישראלי (05X-XXXXXXX).", icon="⚠️")
            st.session_state.user_phone = ""

def render_header_settings():
    st.markdown("### <span style='color: #FFC107;'>Notification Settings ⚙️</span>", unsafe_allow_html=True)
    st.caption("Define where you want to receive real-time alerts.")
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        st.text_input("📧 Email Destination", key="user_email", placeholder="name@company.com", on_change=validate_email_callback)
    with col2:
        st.text_input("📱 WhatsApp Number", key="user_phone", placeholder="050-1234567", on_change=validate_phone_callback)

def render_top_bar():
    metrics = get_market_data_real()
    cols = st.columns(4)
    for i, (name, val, direction) in enumerate(metrics):
        if i < 4:
            arrow = "⬇" if direction == "down" else "⬆"
            cls = "metric-down" if direction == "down" else "metric-up"
            with cols[i]:
                st.markdown(f"""<div class="metric-container"><div class="metric-title">{name}</div><div class="metric-value">{val}</div><div class="{cls}">{arrow}</div></div>""", unsafe_allow_html=True)

def render_sticky_note(ticker, live_data, alert_row, index):
    data = live_data.get(ticker, {})
    price = data.get('price', 0.0)
    ma150 = data.get('MA150', 0.0)
    target = alert_row['target_price']
    direction = alert_row['direction']
    notes = alert_row['notes']
    arrow = "⬆" if direction == "Up" else "⬇"

    st.markdown(f"""
    <div class="sticky-note">
        <div class="note-header"><div class="note-ticker">{ticker}</div><div class="target-marker">{arrow} 🎯 ${target:,.2f}</div></div>
        <div class="note-price">Current: ${price:,.2f}</div>
        <div style="font-size: 0.9em; margin-top:5px;">MA150: ${ma150:,.2f} | Dir: {direction}</div>
        <div style="margin-top: 10px; font-style: italic; background: rgba(255,255,255,0.3); padding: 5px; border-radius: 4px;">"{notes}"</div>
    </div>""", unsafe_allow_html=True)

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
                st.rerun()
    with c2:
        if st.button("🗑️ Del", key=f"del_{index}", use_container_width=True):
            st.session_state.active_alerts.drop(index, inplace=True)
            st.session_state.active_alerts.reset_index(drop=True, inplace=True)
            st.rerun()

# ==========================================
# 7. MAIN APP
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
        else:
            st.info("No active alerts.")
            
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
                    new = {"ticker": t_in, "target_price": p_in, "current_price": 0.0, "direction": d_in, "notes": n_in or "No notes", "created_at": datetime.now()}
                    st.session_state.active_alerts = pd.concat([st.session_state.active_alerts, pd.DataFrame([new])], ignore_index=True)
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        
    st.write("---")
    with st.expander("📂 View History"):
        st.dataframe(st.session_state.completed_alerts, use_container_width=True)

if __name__ == "__main__":
    main()
