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
# 3. CSS STYLING (UPDATED TO MATCH LATEST MOCKUP)
# ==========================================
def apply_custom_ui():
    st.markdown("""
    <style>
        /* GLOBAL DARK THEME */
        .stApp {
            background-color: #0e0e0e !important;
            color: #ffffff;
        }
        
        /* --- INPUT FIELDS STYLING (Light grey bg, Orange border) --- */
        /* Target the container of text inputs for background and border */
        div[data-testid="stTextInput"] div[data-baseweb="input-container"] {
            background-color: #e0e0e0 !important; /* Light grey background */
            border: 2px solid #FFC107 !important; /* Orange border */
            border-radius: 6px !important;
        }
        /* Target the actual text inside the input to be dark for contrast */
        div[data-testid="stTextInput"] input {
            color: #222 !important; /* Dark text */
            background-color: transparent !important;
        }
         /* Target placeholder color to be dark grey */
        div[data-testid="stTextInput"] input::placeholder {
            color: #666 !important;
            opacity: 1;
        }
        /* Ensure labels are white */
        label[data-baseweb="label"] {
            color: #ffffff !important;
        }

        /* --- OTHER STYLES --- */
        /* Number inputs and text areas remain dark styling for now */
        .stNumberInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
             background-color: #262730 !important;
             color: #ffffff !important;
             border: 1px solid #4e4e4e !important;
             border-radius: 8px !important;
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

        /* STICKY NOTES */
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
        .note-ticker { color: #000 !important; font-size: 1.4rem; font-weight: 800; }
        .note-price, .sticky-note div { color: #333 !important; }

        /* TARGET MARKER */
        .target-marker {
            display: inline-flex;
            align-items: center;
            font-weight: 700;
            color: #d32f2f; /* Darker red for visibility on yellow */
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

        /* BUTTONS */
        div.stButton > button {
            background-color: #FFC107 !important;
            color: #000000 !important; 
            font-weight: 800 !important;
            border-radius: 8px !important;
        }
        
        /* CONNECTION BAR */
        .connection-dot {
            width: 10px; height: 10px; border-radius: 50%;
            background-color: #00e676; display: inline-block;
            box-shadow: 0 0 8px #00e676;
            margin-right: 8px;
        }
        .connection-bar {
            color: #888; font-size: 0.85rem; margin-top: 5px; margin-bottom: 15px;
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
                    success, msg = send_email
