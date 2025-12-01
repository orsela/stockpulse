import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import requests

# CONFIG – אל תשנה!
SHEET_ID = "18GROVu8c2Hx5n4H2FiZrOeLXgH9xJG0miPqfgdb-V9w"  # מהלינק שלך
WORKSHEET_NAME = "Rules"
WHATSAPP_PHONE = "+972XXXXXXXXX"  # שנה למספר שלך (למשל +972501234567)
WHATSAPP_API_KEY = "your_api_key"  # קח מ-callmebot.com (אחר כך)

st.set_page_config(page_title="StockPulse Pro", layout="wide", page_icon="💹")

@st.cache_resource(ttl=3600)
def get_gsheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME)

def load_alerts(user_email=None):
    sheet = get_gsheet()
    data = sheet.get_all_records()
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    # התאמה לעמודות שלך (A-L)
    df = df[['user_email', 'symb', 'min_price', 'max_price', 'min_vol', 'last_alert', 'is_one_time', 'status', 'alert_type', 'notes', 'created_at']]
    df.columns = ['user_email', 'ticker', 'min_price', 'target_price', 'min_vol', 'last_alert', 'is_one_time', 'triggered', 'alert_type', 'notes', 'created_at']
    df['min_price'] = pd.to_numeric(df['min_price'], errors='coerce')
    df['target_price'] = pd.to_numeric(df['target_price'], errors='coerce')
    df['min_vol'] = pd.to_numeric(df['min_vol'], errors='coerce')
    df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce')
    df['is_one_time'] = df['is_one_time'].map({'TRUE': True, True: True, 'FALSE': False, False: False})
    df['triggered'] = df['triggered'].map({'Active': 'לא', 'ארכיב': 'כן', 'לא': 'לא', 'כן': 'כן'})
    if user_email:
        df = df[df['user_email'] == user_email]
    return df[df['triggered'] == 'לא']  # רק פעילות

def save_alert(user_email, ticker, min_p, target_p, min_v, alert_t, notes):
    sheet = get_gsheet()
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [user_email, ticker.upper(), min_p, target_p, min_v, '', 'TRUE', 'Active', alert_t, notes, created]
    sheet.append_row(row)
    st.success("התראה נוספה! 📈")

@st.cache_data(ttl=30)
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if hist.empty: return None
        price = hist['Close'].iloc[-1]
        vol = hist['Volume'].iloc[-1]
        sma150 = hist['Close'].rolling(150).mean().iloc[-1]
        info = stock.info
        change = ((price - info.get('previousClose', price)) / info.get('previousClose', price)) * 100
        return {
            'price': round(price, 2),
            'change': round(change, 2),
            'vol': vol,
            'sma150': round(sma150, 2),
            'name': info.get('longName', ticker)[:20]
        }
    except: return None

def check_trigger(alert, data):
    if not data: return False
    price, vol = data['price'], data['vol']
    typ = alert['alert_type']
    if typ == 'מעל' and price >= alert['target_price'] and vol >= alert['min_vol']:
        return True
    if typ == 'מתחת' and price <= alert['min_price'] and vol >= alert['min_vol']:
        return True
    if typ == 'range' and alert['min_price'] <= price <= alert['target_price'] and vol >= alert['min_vol']:
        return True
    return False

# UI פשוט ונקי
st.markdown("""
<style>
.alert-card {background: #f0f2f6; padding: 15px; border-radius: 10px; margin: 10px 0; border-left: 5px solid #4CAF50; font-family: Arial; direction: rtl;}
.triggered {border-left-color: #f44336 !important; background: #ffebee !important;}
.metric {font-size: 1.2em; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

if 'user_email' not in st.session_state:
    st.session_state.user_email = None

if not st.session_state.user_email:
    st.title("ברוכים הבאים ל-StockPulse Pro 💹")
    st.markdown("התחבר עם האימייל שלך מהגיליון.")
    email = st.text_input("אימייל", placeholder="orsela@gmail.cc")
    if st.button("התחבר", use_container_width=True):
        if email in ['orsela@gmail.cc', 'yael_r7@hotmail', 'user1@1.com']:  # מהגיליון שלך
            st.session_state.user_email = email
            st.rerun()
        else:
            st.error("אימייל לא מוכר – בדוק בגיליון Users.")
    st.stop()

st.title(f"התראות של {st.session_state.user_email}")
st.markdown("---")

col1, col2 = st.columns([3, 1])

with col2:
    st.header("הוסף התראה")
    with st.form("add_alert", clear_on_submit=True):
        ticker = st.text_input("סימול מניה", placeholder="NVDA")
        min_p = st.number_input("מחיר מינימלי ($)", min_value=0.0, value=0.0)
        target_p = st.number_input("מחיר מקסימלי ($)", min_value=0.0)
        min_v = st.number_input("ווליום מינימלי", value=1000000.0)
        typ = st.selectbox("סוג התראה", ["מעל", "מתחת", "range"])
        notes = st.text_input("הערות")
        if st.form_submit_button("הוסף", use_container_width=True):
            save_alert(st.session_state.user_email, ticker, min_p, target_p, min_v, typ, notes)
            st.rerun()

with col1:
    alerts = load_alerts(st.session_state.user_email)
    if alerts.empty:
        st.info("אין התראות פעילות. הוסף אחת למעלה! 📝")
    else:
        for idx, alert in alerts.iterrows():
            data = get_stock_data(alert['ticker'])
            triggered = check_trigger(alert, data)
            if triggered:
                # עדכן בגיליון
                sheet = get_gsheet()
                row_num = idx + 2  # headers בשורה 1
                sheet.update_cell(row_num, 8, 'ארכיב')  # status
                sheet.update_cell(row_num, 6, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))  # last_alert
                # שלח ווטסאפ (פעולה עתידית)
                st.balloons()  # אפקט כיפי!

            pct = ((data['price'] - alert['target_price']) / alert['target_price'] * 100) if data else 0
            cls = "triggered" if triggered else ""
            st.markdown(f"""
            <div class="alert-card {cls}">
                <h3>{alert['ticker']} - {data['name'] if data else 'N/A'}</h3>
                <p class="metric">מחיר נוכחי: ${data['price'] if data else 'N/A'} ({data['change'] if data else 0}%)</p>
                <p>יעד: ${alert['target_price']} | מרחק: {pct:.1f}%</p>
                <p>SMA 150: ${data['sma150'] if data else 'N/A'} | ווליום: {data['vol']/1e6:.1f}M</p>
                <small>{alert['notes'] or 'ללא הערות'}</small>
                {f'<p style="color:red; font-size:1.5em;">🚨 התראה הופעלה!</p>' if triggered else ''}
            </div>
            """, unsafe_allow_html=True)

# ריענון אוטו כל 60 שניות
if 'last_run' not in st.session_state: st.session_state.last_run = time.time()
if time.time() - st.session_state.last_run > 60:
    st.rerun()
    st.session_state.last_run = time.time()
