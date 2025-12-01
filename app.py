import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import requests
import time

# סודות
SHEET_ID = st.secrets["SHEET_ID"]
WHATSAPP_PHONE = st.secrets.get("WHATSAPP_PHONE", "")
WHATSAPP_API_KEY = st.secrets.get("WHATSAPP_API_KEY", "123456")

st.set_page_config(page_title="StockPulse Pro", layout="wide", page_icon="💹")

@st.cache_resource(ttl=1800)
def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet("Rules")

def load_alerts(email):
    try:
        data = get_sheet().get_all_records()
        df = pd.DataFrame(data)
        if df.empty: return df
        # תומך גם ב-@gmail.com וגם ב-@gmail.cc
        df = df[df['user_email'].str.contains(email.split('@')[0], case=False, na=False)]
        df['min_price'] = pd.to_numeric(df['min_price'], errors='coerce').fillna(0)
        df['max_price'] = pd.to_numeric(df['max_price'], errors='coerce').fillna(0)
        df['min_vol'] = pd.to_numeric(df['min_vol'], errors='coerce').fillna(0)
        df['alert_type'] = df['alert_type'].fillna('מעל')
        return df[df['status'] == 'Active']
    except Exception as e:
        st.error(f"שגיאה בגיליון: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=30)
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if hist.empty: return None
        price = round(hist['Close'].iloc[-1], 2)
        vol = hist['Volume'].iloc[-1]
        sma150 = round(hist['Close'].rolling(150).mean().iloc[-1], 2) if len(hist) >= 150 else None
        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else price
        change = round(((price - prev_close) / prev_close) * 100, 2)
        name = stock.info.get('longName', ticker)[:30]
        return {'price': price, 'change': change, 'vol': vol, 'sma150': sma150, 'name': name}
    except:
        return None

def check_trigger(a, d):
    if not d: return False
    p, v = d['price'], d['vol']
    t = a['alert_type']
    if t == 'מעל' and p >= a['max_price'] and v >= a['min_vol']: return True
    if t == 'מתחת' and p <= a['min_price'] and v >= a['min_vol']: return True
    if t == 'range' and a['min_price'] <= p <= a['max_price'] and v >= a['min_vol']: return True
    return False

# עיצוב
st.markdown("""
<style>
    .big{font-size:2.8rem!important;font-weight:bold;color:#00ff88;text-align:center}
    .card{background:#f8f9fa;padding:20px;border-radius:15px;margin:15px 0;border-left:6px solid #4CAF50}
    .triggered{border-left-color:#f44336!important;background:#ffebee!important}
    .rtl{direction:rtl;text-align:right;font-family:Arial,sans-serif}
    .metric{font-size:1.6em;font-weight:bold}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="big rtl">StockPulse Pro</div>', unsafe_allow_html=True)
st.markdown('<p class="rtl">התראות בזמן אמת • פשוט וברור</p>', unsafe_allow_html=True)

email = st.text_input("הכנס את המייל שלך", placeholder="orsela@gmail.com")

if not email:
    st.stop()

# טופס הוספה
with st.sidebar:
    st.header("הוסף התראה חדשה")
    with st.form("new_alert", clear_on_submit=True):
        symb = st.text_input("סימול", "NVDA")
        max_p = st.number_input("מחיר יעד", value=100.0)
        min_v = st.number_input("ווליום מינימלי", value=5000000)
        typ = st.selectbox("סוג", ["מעל", "מתחת"])
        notes = st.text_area("הערות", height=80)
        if st.form_submit_button("שמור התראה"):
            sheet = get_sheet()
            sheet.append_row([email, symb.upper(), 0, max_p, min_v, "", "TRUE", "Active", typ, notes, datetime.now().strftime("%d/%m %H:%M")])
            st.success("נוסף!")
            st.rerun()

alerts = load_alerts(email)

if alerts.empty:
    st.info("אין התראות פעילות – תוסיף אחת בצד!")
    st.stop()

for _, a in alerts.iterrows():
    data = get_stock_data(a['symb'])
    triggered = check_trigger(a, data)
    
    cls = "triggered" if triggered else ""
    col = "green" if data and data['change'] > 0 else "red"
    
    st.markdown(f"""
    <div class="card {cls} rtl">
        <h2>{a['symb']} • {data['name'] if data else 'טוען...'}</h2>
        <p class="metric">${data['price'] if data else '...'} <span style="color:{col}">{data['change'] if data else 0:+.2f}%</span></p>
        <p>יעד: ${a['max_price']} • ווליום: {data['vol']/1e6:.1f}M</p>
        {f'<p> SMA150: ${data["sma150"]}</p>' if data and data['sma150'] else ''}
        {f'<h3 style="color:#f44336">התראה הופעלה! 🚨</h3>' if triggered else ''}
    </div>
    """, unsafe_allow_html=True)
    
    if triggered and WHATSAPP_API_KEY != "123456":
        msg = f"StockPulse: {a['symb']} הגיע ליעד! ${data['price']} ({data['change']:+.2f}%)"
        requests.get(f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={requests.utils.quote(msg)}&apikey={WHATSAPP_API_KEY}", timeout=5)

st.caption("מתעדכן כל 30 שניות אוטומטית")

# ריענון
time.sleep(1)
if time.time() - st.session_state.get('last', 0) > 30:
    st.rerun()
