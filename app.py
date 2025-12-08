import streamlit as st
import pandas as pd
from datetime import datetime
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from twilio.rest import Client
import re  # <--- הוספנו את ספריית הביטויים הרגולריים

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
        .note-ticker { color: #000 !important; font-size
