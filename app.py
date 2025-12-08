import streamlit as st
import pandas as pd
from datetime import datetime
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from twilio.rest import Client  # Import Twilio

# ==========================================
# 0. CONFIGURATION & SECRETS
# ==========================================
try:
    # Email Secrets
    SENDER_EMAIL = st.secrets.get("SENDER_EMAIL", "")
    SENDER_PASSWORD = st.secrets.get("SENDER_PASSWORD", "")
    
    # Twilio (WhatsApp) Secrets
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

        body = f"""
        <html>
          <body>
            <h2>Stock Alert Triggered!</h2>
            <p><strong>Ticker:</strong> {ticker}</p>
            <p><strong>Trigger Price:</strong> ${current_price:,.2f}</p>
            <p><strong>Target Was:</strong> ${target_price:,.2f} ({direction})</p>
            <p><strong>Notes:</strong> {notes}</p>
            <br>
            <p>Sent from StockPulse Terminal</p>
          </body>
        </html>
        """
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
    # בדיקה שיש הגדרות טוויליו
    if not TWILIO_SID or not TWILIO_TOKEN or not TWILIO_FROM:
        return False, "Twilio secrets missing"
    
    # ניקוי ופירמוט המספר (חייב להתחיל ב +972 למשל)
    clean_number = to_number.strip()
    if clean_number.startswith("0"):
        clean_number = "+972" + clean_number[1:]
    
    # טוויליו דורשים קידומת whatsapp: לפני המספר
    to_whatsapp = f"whatsapp:{clean_number}"
    
    msg_body = (
        f"🚀 *StockPulse Alert* 🚀\n\n"
        f"📊 *{ticker}* hit *${current_price:,.2f}*\n"
        f"🎯 Target: ${target_price:,.2f} ({direction})\n"
        f"⏱️ Time: {datetime.now().strftime('%H:%M')}"
    )

    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        message = client.messages.create(
            from_=TWILIO_FROM,
            body=msg_body,
            to=to_whatsapp
        )
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
        
        /* INPUT FIELDS */
        div[data-testid="stTextInput"] div[data-baseweb="input-container"] {
            background-color: #e0e0e0 !important;
            border: 2px solid #FFC107 !important;
            border-radius: 6px !important;
        }
        div[data-testid="stTextInput"] input {
            color: #222 !important;
            background-color: transparent !important;
        }
        div[data-testid="stTextInput"] input::placeholder {
            color: #666 !important;
            opacity: 1;
        }
        label[data-baseweb="label"] { color: #ffffff !important; }

        /* METRICS */
        .metric-container {
            background-color: #1c1c1e; border-radius: 8px; padding: 10px;
            text-align: center; border: 1px solid #333; margin-bottom: 10px;
        }
        .metric-title { font-size: 0.8rem; color: #aaa; text-transform: uppercase; }
        .metric-value { font-size: 1.3rem; font-weight: bold; color: #fff; }
        .metric-up { color: #4CAF50; }
        .metric-down { color: #FF5252; }

        /* STICKY NOTES */
        .sticky-note {
            background-color: #F9E79F; color: #222 !important; padding: 15px;
            border-radius: 4px; margin-bottom: 15px; border-top: 1px solid #fcf3cf;
        }
        .note-ticker { color: #000 !important; font-size: 1.4rem; font-weight: 800; }
        .note-price, .sticky-note div { color: #333 !important; }
        .target-marker { color: #d32f2f; font-weight: 700; font-size: 1.1rem; }
        
        /* GENERAL */
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

if 'active_alerts' not in st.session_state:
    st.session_state.active_alerts = pd.DataFrame([
        {
            "ticker": "NVDA",
            "target_price": 950.00,
            "current_price": 900.00,
            "direction": "Up",
            "notes": "Strong earnings expected",
            "created_at": datetime.now(),
        },
    ])

if 'completed_alerts' not in st.session_state:
    st.session_state.completed_alerts = pd.DataFrame(
        columns=["ticker", "target_price", "final_price", 
                 "alert_time", "direction", "notes"]
    )

REFRESH_RATE = 60  # seconds

@st.cache_data(ttl=REFRESH_RATE)
def get_live_data(tickers):
    if not tickers:
        return {}
    live_data = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            current_price = info.get('regularMarketPrice', info.get('currentPrice', None))
            close_price = info.get('previousClose', None)
            display_price = current_price if current_price not in (None, "N/A") else close_price
            ma150 = info.get('twoHundredDayAverage', info.get('fiftyDayAverage', 0))
            
            live_data[ticker] = {
                "price": display_price if display_price is not None else 0.0,
                "MA150": ma150 if ma150 is not None else 0.0,
            }
        except:
            live_data[ticker] = {"price": 0.0, "MA150": 0.0}
    return live_data

def check_alerts():
    if st.session_state.active_alerts.empty:
        return
    tickers = st.session_state.active_alerts['ticker'].tolist()
    live_data = get_live_data(tickers)
    
    alerts_to_move = []
    for index, row in st.session_state.active_alerts.iterrows():
        ticker = row['ticker']
        target = row['target_price']
        direction = row['direction']
        
        if ticker in live_data and live_data[ticker]['price'] != 0.0:
            current = live_data[ticker]['price']
            st.session_state.active_alerts.loc[index, 'current_price'] = current
            
            triggered = False
            if direction == "Up" and current >= target:
                triggered = True
            elif direction == "Down" and current <= target:
                triggered = True
                
            if triggered:
                # --- SEND NOTIFICATIONS ---
                current_email = st.session_state.user_email
                current_phone = st.session_state.user_phone
                
                status_log = []
                
                # 1. Email
                if current_email:
                    ok, msg = send_email_alert(current_email, ticker, current, target, direction, row['notes'])
                    status_log.append(f"Email: {'✅' if ok else '❌'}")
                
                # 2. WhatsApp
                if current_phone:
                    ok, msg = send_whatsapp_alert(current_phone, ticker, current, target, direction)
                    status_log.append(f"WhatsApp: {'✅' if ok else '❌'}")
                
                if not status_log:
                    status_log.append("Local Only")

                status_str = " | ".join(status_log)

                new_completed = {
                    "ticker": ticker,
                    "target_price": target,
                    "final_price": current,
                    "alert_time": datetime.now(),
                    "direction": direction,
                    "notes": row['notes'] + f" ({status_str})",
                }
                st.session_state.completed_alerts = pd.concat(
                    [st.session_state.completed_alerts, pd.DataFrame([new_completed])], 
                    ignore_index=True
                )
                alerts_to_move.append(index)
                
                st.toast(
                    f"🚀 Alert: {ticker} @ ${current:,.2f}\n{status_str}",
                    icon="🔥",
                )

    if alerts_to_move:
        st.session_state.active_alerts.drop(alerts_to_move, inplace=True)
        st.session_state.active_alerts.reset_index(drop=True, inplace=True)
        st.rerun()

# ==========================================
# 5. MARKET DATA
# ==========================================
@st.cache_data(ttl=300) 
def get_market_data_real():
    indicators = {"S&P 500": "^GSPC", "BITCOIN": "BTC-USD", "VIX": "^VIX", "NASDAQ": "^IXIC"}
    results = []
    for name, ticker in indicators.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1mo")
            if not hist.empty:
                last = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2] if len(hist) >= 2 else last
                direction = "up" if last >= prev else "down"
                results.append((name, f"{last:,.2f}", direction))
            else:
                results.append((name, "N/A", "down"))
        except:
            results.append((name, "Error", "down"))
    return results

# ==========================================
# 6. UI COMPONENTS
# ==========================================
def render_header_settings():
    st.markdown("### <span style='color: #FFC107;'>Notification Settings ⚙️</span>", unsafe_allow_html=True)
    st.caption("Define where you want to receive real-time alerts.")
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        st.session_state.user_email = st.text_input("📧 Email Destination", value=st.session_state.user_email, placeholder="name@company.com")
    with col2:
        st.session_state.user_phone = st.text_input("📱 WhatsApp Number", value=st.session_state.user_phone, placeholder="050-1234567")

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
