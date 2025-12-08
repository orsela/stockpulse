# ==========================================
# 5. WHATSAPP LOGIC (SUPER DEBUG VERSION)
# ==========================================
def process_incoming_whatsapp():
    # בדיקה שיש קרדנשלס
    if not TWILIO_SID or not TWILIO_TOKEN: 
        if st.session_state.show_debug:
            st.session_state.debug_info = {"error": "Twilio Secrets Missing!"}
        return
    
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        
        # 1. הכנת המספר הצפוי של המשתמש (לצורך השוואה)
        raw_phone = str(st.session_state.user_phone)
        digits_only = re.sub(r'\D', '', raw_phone) 
        if digits_only.startswith("0"):
            digits_only = "972" + digits_only[1:]
        expected_sender = f"whatsapp:+{digits_only}"
        
        # 2. אתחול דיבאג
        st.session_state.debug_info = {
            "my_number_formatted": expected_sender,
            "twilio_configured_number": TWILIO_FROM, # נראה מה מוגדר בסודות
            "messages_found": []
        }
        
        # 3. משיכת כל ההודעות האחרונות (בלי פילטר 'to' כדי לראות הכל)
        # זה יעזור לנו להבין אם המספר ב-Secrets לא תואם
        messages = client.messages.list(limit=15)
        
        for msg in messages:
            # נשמור מידע לדיבאג
            st.session_state.debug_info["messages_found"].append({
                "direction": msg.direction, # inbound / outbound
                "from": msg.from_,
                "to": msg.to,
                "body": msg.body,
                "status": msg.status,
                "sid": msg.sid
            })
            
            # לוגיקה: אנחנו מחפשים הודעה שנכנסה (inbound) והגיעה מהמשתמש שלנו
            is_inbound = (msg.direction == 'inbound')
            is_from_user = (msg.from_ == expected_sender)
            is_new = (msg.sid not in st.session_state.processed_msgs)
            
            if is_inbound and is_from_user and is_new:
                st.session_state.processed_msgs.add(msg.sid)
                
                # פענוח ההודעה
                body = msg.body.strip().upper()
                match = re.match(r"^([A-Z]+)\s+(\d+(\.\d+)?)$", body)
                
                if match:
                    ticker = match.group(1)
                    target = float(match.group(2))
                    new_alert = {
                        "ticker": ticker, 
                        "target_price": target, 
                        "current_price": 0.0, 
                        "direction": "Up", 
                        "notes": "Added via WhatsApp", 
                        "created_at": datetime.now()
                    }
                    st.session_state.active_alerts = pd.concat([st.session_state.active_alerts, pd.DataFrame([new_alert])], ignore_index=True)
                    st.toast(f"📱 WhatsApp: Added {ticker} @ {target}", icon="✅")
                    
    except Exception as e:
        st.session_state.debug_error = str(e)
