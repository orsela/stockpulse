import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime import datetime
import requests, time

# קורא את הסודות מהענן
SHEET_ID = st.secrets["SHEET_ID"]
WHATSAPP_PHONE = st.secrets["WHATSAPP_PHONE"]
WHATSAPP_API_KEY = st.secrets["WHATSAPP_API_KEY"]

st.set_page_config(page_title="StockPulse", layout="wide", page_icon="Chart Increasing")

# חיבור לגיליון
@st.cache_resource(ttl=1800)
def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet("Rules")

# טען התראות
def load_alerts(email):
    data = get_sheet().get_all_records()
    df = pd.DataFrame(data)
    if df.empty: return df
    df = df[df['user_email'] == email]
    df['min_price'] = pd.to_numeric(df['min_price'], errors='coerce').fillna(0)
    df['max_price'] = pd.to_numeric(df['max_price'], errors='coerce').fillna(0)
    df['min_vol'] = pd.to_numeric(df['min_vol'], errors='coerce').fillna(0)
    return df[df['status'] == 'Active']

# עיצוב נקי
st.markdown("""
<style>
    .big {font-size: 2.5rem !important; font-weight: bold; color: #00ff88; text-align: center;}
    .card {background: linear-gradient(135deg, #1e1e2e, #16213e); color: white; padding: 20px; border-radius: 15px; margin: 10px 0;}
    .triggered {background: linear-gradient(135deg, #440000, #880000) !important;}
    .rtl {direction: rtl; text-align: right;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="big">StockPulse Pro</div>', unsafe_allow_html=True)
st.markdown("### התראות חכמות בזמן אמת • עיצוב ישראלי נקי")

email = st.text_input("הכנס את המייל שלך מהגיליון", placeholder="orsela@gmail.cc")

if not email:
    st.stop()

alerts = load_alerts(email)

if alerts.empty:
    st.info("אין התראות פעילות – תוסיף בגיליון או תכתוב לי ואוסיף לך אחת")
    st.stop()

for i, a in alerts.iterrows():
    data = yf.Ticker(a['symb']).info
    price = data.get("currentPrice") or data.get("regularMarketPrice")
    prev = data.get("previousClose", price)
    change = (price-prev)/prev*100 if prev else 0
    vol = data.get("volume", 0)

    triggered = False
    if a['alert_type'] == "מעל" and price >= a['max_price'] and vol >= a['min_vol']:
        triggered = True
    elif a['alert_type'] == "מתחת" and price <= a['min_price'] and vol >= a['min_vol']:
        triggered = True

    st.markdown(f"""
    <div class="card {'triggered' if triggered else ''} rtl">
        <h2>{a['symb']} • {data.get('longName','')[:25]}</h2>
        <h1>${price}</h1> <span style="color:{'lime' if change>0 else 'red'}"> {change:+.2f}%</span>
        <p>יעד: ${a['max_price']} • ווליום: {vol/1e6:.1f}M</p>
        {'' if triggered else f"<p>מרחק: {((price-a['max_price'])/a['max_price']*100):.1f}%</p>"}
        {f'<h2>התראה הופעלה! בדוק ווטסאפ</h2>' if triggered else ''}
    </div>
    """, unsafe_allow_html=True)

    if triggered and WHATSAPP_API_KEY != "123456":
        msg = f"StockPulse: {a['symb']} הגיע ליעד! ${price} (+{change:.1f}%)"
        url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={msg}&apikey={WHATSAPP_API_KEY}"
        requests.get(url, timeout=5)

st.caption("מתעדכן אוטומטית כל דקה • גרסה 2025")
