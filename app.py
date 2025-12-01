import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import requests
import time

# קורא את הסודות מהענן
SHEET_ID = st.secrets["SHEET_ID"]
WHATSAPP_PHONE = st.secrets["WHATSAPP_PHONE"]
WHATSAPP_API_KEY = st.secrets["WHATSAPP_API_KEY"]

st.set_page_config(page_title="StockPulse Pro", layout="wide", page_icon="💹")

# חיבור לגיליון
@st.cache_resource(ttl=1800)
def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet("Rules")

# טען התראות
def load_alerts(email):
    try:
        data = get_sheet().get_all_records()
        df = pd.DataFrame(data)
        if df.empty: return df
        df = df[df['user_email'] == email]
        df['min_price'] = pd.to_numeric(df['min_price'], errors='coerce').fillna(0)
        df['max_price'] = pd.to_numeric(df['max_price'], errors='coerce').fillna(0)
        df['min_vol'] = pd.to_numeric(df['min_vol'], errors='coerce').fillna(0)
        # אם alert_type ריק, הגדר כברירת מחדל "מעל"
        df['alert_type'] = df['alert_type'].fillna('מעל')
        return df[df['status'] == 'Active']
    except Exception as e:
        st.error(f"שגיאה בקריאת הגיליון: {e}")
        return pd.DataFrame()

# נתוני מניה
@st.cache_data(ttl=30)
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2d")
        if hist.empty: return None
        price = hist['Close'].iloc[-1]
        vol = hist['Volume'].iloc[-1]
        prev = hist['Close'].iloc[-2] if len(hist) > 1 else price
        change = ((price - prev) / prev) * 100
        info = stock.info
        name = info.get('longName', ticker)[:25]
        return {'price': price, 'change': change, 'vol': vol, 'name': name}
    except:
        return None

# בדיקת טריגר
def check_trigger(alert, data):
    if not data: return False
    price, vol = data['price'], data['vol']
    typ = alert['alert_type']
    if typ == 'מעל' and price >= alert['max_price'] and vol >= alert['min_vol']:
        return True
    if typ == 'מתחת' and price <= alert['min_price'] and vol >= alert['min_vol']:
        return True
    if typ == 'range' and alert['min_price'] <= price <= alert['max_price'] and vol >= alert['min_vol']:
        return True
    return False

# עיצוב פשוט וברור
st.markdown("""
<style>
    .big {font-size: 2.5rem !important; font-weight: bold; color: #00ff88; text-align: center;}
    .card {background: #f8f9fa; color: #333; padding: 20px; border-radius: 15px; margin: 10px 0; border-left: 5px solid #4CAF50;}
    .triggered {border-left-color: #f44336 !important; background: #ffebee !important;}
    .rtl {direction: rtl; text-align: right; font-family: Arial, sans-serif;}
    .metric {font-size: 1.5em; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="big rtl">StockPulse Pro</div>', unsafe_allow_html=True)
st.markdown('<p class="rtl">התראות חכמות בזמן אמת • עיצוב פשוט וברור</p>', unsafe_allow_html=True)

email = st.text_input("הכנס את המייל שלך מהגיליון", placeholder="orsela@gmail.cc", key="email_input")

if not email:
    st.stop()

alerts = load_alerts(email)

if alerts.empty:
    st.info("אין התראות פעילות – תוסיף בגיליון או תכתוב לי ואוסיף לך אחת 📝")
    st.stop()

for _, alert in alerts.iterrows():
    data = get_stock_data(alert['symb'])
    triggered = check_trigger(alert, data)
    
    if triggered and alert['is_one_time'] == 'TRUE':
        # עדכן סטטוס בגיליון
        try:
            sheet = get_sheet()
            row_num = alerts.index[alerts['symb'] == alert['symb']] + 2  # שורה + headers
            sheet.update_cell(row_num[0] + 1, 8, 'ארכיב')  # עמודה H: status
        except:
            pass
    
    pct = ((data['price'] - alert['max_price']) / alert['max_price'] * 100) if data and alert['max_price'] > 0 else 0
    cls = "triggered" if triggered else ""
    color_change = "green" if data['change'] > 0 else "red"
    
    st.markdown(f"""
    <div class="card {cls} rtl">
        <h3>{alert['symb']} • {data['name'] if data else 'N/A'}</h3>
        <p class="metric">מחיר נוכחי: ${data['price'] if data else 'N/A'}</p>
        <p>שינוי: <span style="color:{color_change};">{data['change']:+.2f}%</span></p>
        <p>יעד: ${alert['max_price']} • מרחק: {pct:.1f}%</p>
        <p>ווליום: {data['vol']/1e6:.1f}M (מינימום: {alert['min_vol']/1e6:.0f}M)</p>
        <small>{alert['notes'] or 'ללא הערות'}</small>
        {f'<p style="color:#f44336; font-size:1.5em;">🚨 התראה הופעלה! בדוק ווטסאפ</p>' if triggered else ''}
    </div>
    """, unsafe_allow_html=True)
    
    if triggered and WHATSAPP_API_KEY != "123456":
        msg = f"🚨 StockPulse Alert: {alert['symb']} הגיע ליעד! מחיר: ${data['price']} ({data['change']:+.1f}%)"
        url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={requests.utils.quote(msg)}&apikey={WHATSAPP_API_KEY}"
        try:
            requests.get(url, timeout=5)
        except:
            pass

st.caption("מתעדכן אוטומטית כל 30 שניות • גרסה 2025 • פותחה ב-xAI")

# ריענון אוטומטי
time.sleep(1)
if 'last_run' not in st.session_state:
    st.session_state.last_run = time.time()
if time.time() - st.session_state.last_run > 30:
    st.rerun()
    st.session_state.last_run = time.time()
