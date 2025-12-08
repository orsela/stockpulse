import streamlit as st
import pandas as pd
from datetime import datetime
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 0. CONFIGURATION & SECRETS
# ==========================================
try:
    SENDER_EMAIL = st.secrets["SENDER_EMAIL"]
    SENDER_PASSWORD = st.secrets["SENDER_PASSWORD"]
except Exception:
    SENDER_EMAIL = ""
    SENDER_PASSWORD = ""

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
# 2. EMAIL FUNCTION
# ==========================================
def send_email_alert(to_email, ticker, current_price, target_price, direction, notes):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        return False, "Secrets not configured in Streamlit Cloud."
    
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
        return True, "Email sent successfully"
    except Exception as e:
        return False, str(e)

# ==========================================
# 3. CSS STYLING
# ==========================================
def apply_custom_ui():
    st.markdown("""
    <style>
        /* GLOBAL DARK THEME */
        .stApp {
            background-color: #0e0e0e !important;
            color: #ffffff;
        }
        
        /* INPUT FIELDS STYLING */
        .stTextInput input, .stNumberInput input, .stTextArea textarea, 
        .stSelectbox div[data-baseweb="select"] {
            background-color: #1e1e1e !important; 
            color: #ffffff !important;
            border: 1px solid #444 !important;
        }
        
        /* HEADER SETTINGS BAR */
        .settings-bar {
            background-color: #1a1a1a;
            border-bottom: 2px solid #FFC107;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 8px;
        }
        
        /* METRICS TOP BAR */
        .metric-container {
            background-color: #1c1c1e;
            border-radius: 8px;
            padding: 10px;
            text-align: center;
            border: 1px solid #333;
            margin-bottom: 10px;
        }
        .metric-title { font-size: 0.8rem; color: #aaa; text-transform: uppercase; }
        .metric-value { font-size: 1.3rem; font-weight: bold; color: #fff; }
        .metric-up { color: #4CAF50; font-size: 0.9rem; }
        .metric-down { color: #FF5252; font-size: 0.9rem; }

        /* STICKY NOTES (ALERTS) */
        .sticky-note {
            background-color: #F9E79F;
            color: #222 !important;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 15px;
            box-shadow: 4px 4px 10px rgba(0,0,0,0.5);
            position: relative;
            border-top: 1px solid #fcf3cf;
        }
        .sticky-note h4, .sticky-note p, .sticky-note div, .sticky-note span {
            color: #222 !important;
        }
        .note-header {
            display: flex; justify-content: space-between; align-items: center;
            border-bottom: 1px solid rgba(0,0,0,0.1); padding-bottom: 5px; margin-bottom: 8px;
        }
        .note-ticker { font-size: 1.4rem; font-weight: 800; }

        /* TARGET MARKER */
        .target-marker {
            display: inline-flex;
            align-items: center;
            font-weight: 700;
            color: #ff5252;
            font-size: 1.1rem;
        }
        
        /* FORM CONTAINER */
        .create-form-container {
            background-color: #1a1a1a;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.5);
        }
        .form-header {
            color: #FFC107;
            font-size: 1.5rem;
            font-weight: bold;
            margin-bottom: 15px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
        }

        /* BUTTONS STYLING */
        div.stButton > button {
            background-color: #FFC107 !important;
            color: #000000 !important; 
            font-weight: 800 !important;
            border-radius: 8px !important;
            border: none !important;
        }
        div.stButton > button:hover {
            background-color: #e0a800 !important;
            color: #000000 !important;
        }
        div.stButton > button:active {
            color: #000000 !important;
        }

        /* CONNECTION GREEN DOT */
        .connection-dot {
            width: 14px;
            height: 14px;
            border-radius: 50%;
            background-color: #00e676;
            box-shadow: 0 0 10px rgba(0, 230, 118, 0.9);
            margin-right: 8px;
            display: inline-block;
            animation: blink 1s infinite;
        }
        @keyframes blink {
            0%, 100% { opacity: 0.2; }
            50%      { opacity: 1;   }
        }
        .connection-bar {
            display: flex;
            align-items: center;
            font-size: 0.9rem;
            color: #bbb;
            margin-bottom: 10px;
            margin-top: 3px;
        }
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
            current_price = info.get('regularMarketPrice', 
                                     info.get('currentPrice', None))
            close_price = info.get('previousClose', None)
            display_price = current_price if current_price not in (None, "N/A") else close_price
            ma150_approx = info.get('twoHundredDayAverage', 
                                    info.get('fiftyDayAverage', 0))
            
            live_data[ticker] = {
                "price": display_price if display_price is not None else 0.0,
                "MA150": ma150_approx if ma150_approx is not None else 0.0,
            }
        except Exception:
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
                current_email = st.session_state.user_email or ""
                current_phone = st.session_state.user_phone or "No Phone"
                
                # --- SEND REAL EMAIL ---
                email_status = "Skipped"
                if current_email:
                    success, msg = send_email_alert(
                        current_email, ticker, current, target, direction, row['notes']
                    )
                    email_status = "Sent" if success else f"Failed ({msg})"
                else:
                    email_status = "No Email Provided"

                new_completed = {
                    "ticker": ticker,
                    "target_price": target,
                    "final_price": current,
                    "alert_time": datetime.now(),
                    "direction": direction,
                    "notes": row['notes'] 
                             + f" (Email Status: {email_status})",
                }
                st.session_state.completed_alerts = pd.concat(
                    [st.session_state.completed_alerts, 
                     pd.DataFrame([new_completed])], 
                    ignore_index=True,
                )
                alerts_to_move.append(index)
                
                st.toast(
                    f"🚀 Alert Sent! {ticker} @ ${current:,.2f}\n"
                    f"Email: {email_status}",
                    icon="📨",
                )

    if alerts_to_move:
        st.session_state.active_alerts.drop(alerts_to_move, inplace=True)
        st.session_state.active_alerts.reset_index(drop=True, inplace=True)
        st.rerun()

# ==========================================
# 5. NEW MARKET DATA FUNCTIONS
# ==========================================

@st.cache_data(ttl=300) # מרענן כל 5 דקות כדי לא להכביד
def get_market_data_real():
    # הממירים (Tickers) של המדדים החשובים
    indicators = {
        "S&P 500": "^GSPC",
        "BITCOIN": "BTC-USD", 
        "VIX": "^VIX",
        "NASDAQ": "^IXIC"
    }
    
    results = []
    
    for name, ticker in indicators.items():
        try:
            # מושכים 5 ימים אחרונים כדי לוודא שיש נתונים גם בסופ"ש
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            
            if not hist.empty:
                # לוקחים תמיד את השורה האחרונה - זה המחיר הכי עדכני שיש (חי או סגירה)
                last_price = hist['Close'].iloc[-1]
                
                # כדי לקבוע אם החץ ירוק או אדום, נשווה ליום שלפניו
                if len(hist) >= 2:
                    prev_close = hist['Close'].iloc[-2]
                    direction = "up" if last_price >= prev_close else "down"
                else:
                    direction = "up" # ברירת מחדל אם אין מספיק היסטוריה
                
                results.append((name, f"{last_price:,.2f}", direction))
            else:
                results.append((name, "N/A", "down"))
        except Exception as e:
            results.append((name, "Error", "down"))
            
    return results

# ==========================================
# 6. COMPONENT RENDERING
# ==========================================

def render_header_settings():
    st.markdown("### 📡 Alert Configuration")
    st.markdown("Enter destination for alerts. If empty, alerts will log locally only.")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.user_email = st.text_input(
            "📧 Email Address",
            value=st.session_state.user_email,
            placeholder="e.g. name@example.com",
        )
    with col2:
        st.session_state.user_phone = st.text_input(
            "📱 Mobile Phone",
            value=st.session_state.user_phone,
            placeholder="e.g. 050-1234567",
        )
    st.write("---")

def render_top_bar():
    # קריאה לפונקציה האמיתית החדשה
    metrics = get_market_data_real()
    
    col1, col2, col3, col4 = st.columns(4)
    cols = [col1, col2, col3, col4]
    
    for i, (name, val, direction) in enumerate(metrics):
        arrow = "⬇" if direction == "down" else "⬆"
        color_class = "metric-down" if direction == "down" else "metric-up"
        
        if i < len(cols):
            with cols[i]:
                st.markdown(f"""
                <div class="metric-container">
                    <div class="metric-title">{name}</div>
                    <div class="metric-value">{val}</div>
                    <div class="{color_class}">{arrow}</div>
                </div>""", unsafe_allow_html=True)

def render_sticky_note(ticker, live_data, alert_row, index):
    data = live_data.get(ticker, {})
    price = data.get('price', 0.0) or 0.0
    ma150 = data.get('MA150', 0.0) or 0.0

    target = alert_row['target_price']
    direction = alert_row['direction']
    notes = alert_row['notes']
    
    arrow_icon = "⬆" if direction == "Up" else "⬇"

    st.markdown(f"""
    <div class="sticky-note">
        <div class="note-header">
            <div class="note-ticker">{ticker}</div>
            <div class="note-target target-marker">
                {arrow_icon} 🎯 ${target:,.2f}
            </div>
        </div>
        <div class="note-price">Current: ${price:,.2f}</div>
        <div style="font-size: 0.9em; margin-top:5px;">
            MA150: ${ma150:,.2f} | Dir: {direction}
        </div>
        <div style="margin-top: 10px; font-style: italic; 
                    background: rgba(255,255,255,0.3); 
                    padding: 5px; border-radius: 4px;">
            "{notes}"
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns([1, 1])
    
    # EDIT
    with c1:
        with st.popover("✏️ Edit", use_container_width=True):
            st.markdown("**Update Alert Details**")
            
            ed_ticker = st.text_input(
                "Ticker", value=ticker, key=f"ed_tick_{index}"
            )
            ed_price = st.number_input(
                "Target Price", value=float(target), 
                format="%.2f", key=f"ed_price_{index}",
            )
            ed_dir = st.selectbox(
                "Direction", ["Up", "Down"], 
                index=0 if direction == "Up" else 1,
                key=f"ed_dir_{index}",
            )
            ed_notes = st.text_area(
                "Notes", value=notes, height=80, key=f"ed_note_{index}"
            )
            
            if st.button("💾 Save Changes", key=f"btn_save_{index}"):
                st.session_state.active_alerts.at[index, 'ticker'] = ed_ticker.upper()
                st.session_state.active_alerts.at[index, 'target_price'] = ed_price
                st.session_state.active_alerts.at[index, 'direction'] = ed_dir
                st.session_state.active_alerts.at[index, 'notes'] = ed_notes
                st.success("Updated!")
                st.rerun()

    # DELETE
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
    
    st.markdown(
        "<h1 style='text-align: center; color: #FFC107;'>⚡ StockPulse Terminal</h1>", 
        unsafe_allow_html=True,
    )
    
    render_header_settings()
    
    # הבר העליון מקבל עכשיו נתונים אמיתיים
    render_top_bar()
    
    st.markdown(
        "<div class='connection-bar'>"
        "<span class='connection-dot'></span>"
        "<span>Connected to price server</span>"
        "</div>", 
        unsafe_allow_html=True,
    )
    check_alerts()
    
    st.write("---")
    
    col_alerts, col_create = st.columns([1.2, 1], gap="large")
    
    with col_alerts:
        st.markdown("### 🔔 Active Alerts")
        if not st.session_state.active_alerts.empty:
            tickers = st.session_state.active_alerts['ticker'].tolist()
            live_data = get_live_data(tickers)
            
            note_cols = st.columns(2)
            for i, row in st.session_state.active_alerts.iterrows():
                with note_cols[i % 2]:
                    render_sticky_note(row['ticker'], live_data, row, i)
        else:
            st.info("No active alerts.")

    with col_create:
        st.markdown('<div class="create-form-container">', unsafe_allow_html=True)
        st.markdown(
            '<div class="form-header">➕ Create New Alert</div>', 
            unsafe_allow_html=True,
        )
        
        with st.form("create_alert_form", clear_on_submit=True):
            st.markdown("**Ticker Symbol**")
            st.text_input(
                "Ticker Symbol", 
                placeholder="e.g. NVDA",
                key="new_ticker",
                label_visibility="collapsed",
            )
            
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Target Price ($)**")
                st.session_state.new_target = st.slider(
                    "Target", 
                    min_value=0.0, 
                    max_value=2000.0, 
                    value=200.0, 
                    step=1.0,
                    key="new_target_slider",
                    label_visibility="collapsed",
                )
            with c2:
                st.markdown("**Direction**")
                st.selectbox(
                    "Direction", 
                    ["Up", "Down"], 
                    key="new_direction",
                    label_visibility="collapsed",
                )
                
            st.markdown("**Notes / Strategy**")
            st.text_area(
                "Notes", 
                placeholder="Strategy details...",
                height=100,
                key="new_notes",
                label_visibility="collapsed",
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            submitted = st.form_submit_button(
                "ADD NOTIFICATION ➔", use_container_width=True
            )
            
            if submitted:
                ticker_in = st.session_state.new_ticker.upper()
                target_in = st.session_state.new_target
                
                if ticker_in and target_in > 0:
                    new_alert = {
                        "ticker": ticker_in,
                        "target_price": target_in,
                        "current_price": 0.0,
                        "direction": st.session_state.new_direction,
                        "notes": (
                            st.session_state.new_notes 
                            if st.session_state.new_notes 
                            else "No notes"
                        ),
                        "created_at": datetime.now(),
                    }
                    st.session_state.active_alerts = pd.concat(
                        [st.session_state.active_alerts, 
                         pd.DataFrame([new_alert])], 
                        ignore_index=True,
                    )
                    st.success(f"Alert for {ticker_in} added!")
                    st.rerun()
                else:
                    st.error("Please enter Ticker and Target.")
                    
        st.markdown('</div>', unsafe_allow_html=True)
        
    st.write("---")
    with st.expander("📂 View History"):
        st.dataframe(st.session_state.completed_alerts, use_container_width=True)

if __name__ == "__main__":
    main()
