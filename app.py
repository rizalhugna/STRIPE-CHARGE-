import requests
import re
import threading
import random
import string
import time
import logging
import os
from datetime import datetime
from flask import Flask, request, jsonify

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
BOT_TOKEN = '8323578379:AAFDGDFlHEEakTK3Mw49ANizwsbewPAaWKo'
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Stripe Keys - Ganti dengan key Anda
# Untuk TESTING, gunakan test keys dulu
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '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')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', 'pk_live_51TWskSF79lbCDrn2YUT5OTMiCtJOtfjPRdu5Fvi77BXKcyrqYdDV43q7k7XTJlO8docnOY45e6KdcPZdYzPoyFRr00Xlnsy2Wn')

app = Flask(__name__)

# --- Global variables for polling
last_update_id = 0
bot_running = True

# --- Stripe Auth Check (Simplified & Fixed) ---
def stripe_auth_check(cc, mm, yy, cvv):
    """Check card using Stripe API - Simplified version"""
    
    # Format data
    if len(yy) == 4:
        yy = yy[-2:]
    mm = mm.zfill(2)
    
    # Clean card number (remove spaces)
    cc = re.sub(r'\s+', '', cc)
    
    try:
        # Step 1: Create payment method
        payment_data = {
            'type': 'card',
            'card[number]': cc,
            'card[exp_month]': mm,
            'card[exp_year]': f'20{yy}',
            'card[cvc]': cvv
        }
        
        logger.info(f"Checking card: {cc[:4]}****{cc[-4:]}")
        
        response = requests.post(
            'https://api.stripe.com/v1/payment_methods',
            data=payment_data,
            auth=(STRIPE_SECRET_KEY, ''),
            timeout=20
        )
        
        result = response.json()
        
        if response.status_code == 200:
            payment_id = result.get('id')
            
            # Step 2: Create setup intent to validate
            setup_data = {
                'payment_method': payment_id,
                'confirm': 'true'
            }
            
            setup_response = requests.post(
                'https://api.stripe.com/v1/setup_intents',
                data=setup_data,
                auth=(STRIPE_SECRET_KEY, ''),
                timeout=20
            )
            
            if setup_response.status_code == 200:
                setup_result = setup_response.json()
                status = setup_result.get('status')
                
                if status == 'succeeded':
                    return {
                        "status": "Approved",
                        "response": "Card is valid and active!"
                    }
                elif status == 'requires_payment_method':
                    return {
                        "status": "Declined",
                        "response": "Card declined - needs 3D secure verification"
                    }
                else:
                    return {
                        "status": "Declined",
                        "response": f"Status: {status}"
                    }
            else:
                error = setup_response.json().get('error', {})
                return {
                    "status": "Declined",
                    "response": error.get('message', 'Setup failed')
                }
                
        elif response.status_code == 402:
            error = result.get('error', {})
            decline_code = error.get('decline_code', 'generic_decline')
            message = error.get('message', 'Card declined')
            
            # Map decline codes to friendly messages
            decline_messages = {
                'insufficient_funds': 'Insufficient funds',
                'lost_card': 'Card reported lost',
                'stolen_card': 'Card reported stolen',
                'expired_card': 'Card expired',
                'incorrect_cvc': 'Wrong CVV',
                'incorrect_zip': 'Wrong postal code',
                'card_declined': 'Card declined by bank'
            }
            
            friendly_msg = decline_messages.get(decline_code, message)
            return {
                "status": "Declined",
                "response": friendly_msg
            }
        else:
            error = result.get('error', {})
            return {
                "status": "Declined",
                "response": error.get('message', 'Unknown error')
            }
            
    except requests.exceptions.Timeout:
        return {
            "status": "Declined",
            "response": "Request timeout - Stripe API slow"
        }
    except Exception as e:
        logger.error(f"Stripe error: {str(e)}")
        return {
            "status": "Declined",
            "response": f"Error: {str(e)[:100]}"
        }

# --- Braintree Check (Simplified) ---
def braintree_check(cc, mm, yy, cvv):
    """Braintree gateway check"""
    time.sleep(1)
    return {
        "status": "Declined",
        "response": "Braintree gateway requires separate configuration"
    }

# --- Stripe Charge Check ---
def stripe_charge_check(cc, mm, yy, cvv):
    """Stripe charge with small amount"""
    
    if len(yy) == 4:
        yy = yy[-2:]
    mm = mm.zfill(2)
    cc = re.sub(r'\s+', '', cc)
    
    try:
        # Create payment method
        payment_data = {
            'type': 'card',
            'card[number]': cc,
            'card[exp_month]': mm,
            'card[exp_year]': f'20{yy}',
            'card[cvc]': cvv
        }
        
        pm_response = requests.post(
            'https://api.stripe.com/v1/payment_methods',
            data=payment_data,
            auth=(STRIPE_SECRET_KEY, ''),
            timeout=20
        )
        
        if pm_response.status_code != 200:
            error = pm_response.json().get('error', {})
            return {
                "status": "Declined",
                "response": error.get('message', 'Invalid card')
            }
        
        payment_id = pm_response.json().get('id')
        
        # Create payment intent with $0.50
        intent_data = {
            'amount': 500,  # $0.50
            'currency': 'usd',
            'payment_method': payment_id,
            'confirm': 'true',
            'capture_method': 'manual'  # Don't actually charge
        }
        
        intent_response = requests.post(
            'https://api.stripe.com/v1/payment_intents',
            data=intent_data,
            auth=(STRIPE_SECRET_KEY, ''),
            timeout=20
        )
        
        if intent_response.status_code == 200:
            intent = intent_response.json()
            status = intent.get('status')
            
            if status in ['requires_capture', 'succeeded']:
                return {
                    "status": "Approved",
                    "response": "Card authorized successfully!"
                }
            else:
                return {
                    "status": "Declined",
                    "response": f"Status: {status}"
                }
        else:
            error = intent_response.json().get('error', {})
            return {
                "status": "Declined",
                "response": error.get('message', 'Authorization failed')
            }
            
    except Exception as e:
        logger.error(f"Charge error: {str(e)}")
        return {
            "status": "Declined",
            "response": f"Error: {str(e)[:100]}"
        }

# --- BIN Lookup (Multiple Sources) ---
def get_bin_info(bin_number):
    """Get BIN information from multiple sources"""
    
    bin_number = bin_number[:6]
    
    # Try multiple APIs
    apis = [
        f'https://lookup.binlist.net/{bin_number}',
        f'https://binlist.io/lookup/{bin_number}/',
        f'https://data.handyapi.com/bin/{bin_number}'
    ]
    
    for api in apis:
        try:
            headers = {'Accept-Version': '3'}
            response = requests.get(api, headers=headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                
                # Parse response
                result = {
                    'brand': data.get('scheme', data.get('brand', 'Unknown')).upper(),
                    'type': data.get('type', 'Unknown').upper(),
                    'country': data.get('country', {}).get('name', 'Unknown'),
                    'country_code': data.get('country', {}).get('alpha2', ''),
                    'bank': data.get('bank', {}).get('name', 'Unknown')
                }
                
                # Handle different API formats
                if 'country_name' in data:
                    result['country'] = data.get('country_name', 'Unknown')
                if 'bank' in data and isinstance(data['bank'], str):
                    result['bank'] = data.get('bank', 'Unknown')
                    
                return result
        except:
            continue
    
    return {
        'brand': 'Unknown',
        'type': 'Unknown',
        'country': 'Unknown',
        'country_code': '',
        'bank': 'Unknown'
    }

# --- Send Message to Telegram ---
def send_message(chat_id, text, parse_mode='HTML'):
    """Send message to Telegram"""
    url = TELEGRAM_API_URL + "sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        result = response.json()
        
        if result.get('ok'):
            return result.get('result')
        else:
            logger.error(f"Send error: {result}")
            return None
    except Exception as e:
        logger.error(f"Send exception: {str(e)}")
        return None

# --- Process Card Check ---
def process_card(chat_id, card_string, gateway_func, gateway_name):
    """Process card check in background"""
    try:
        # Validate format
        parts = card_string.split('|')
        if len(parts) != 4:
            send_message(chat_id, "❌ Invalid format!\n\nUse: <code>CC|MM|YY|CVV</code>\nExample: <code>4111111111111111|12|25|123</code>")
            return
        
        cc, mm, yy, cvv = parts
        
        # Basic validation
        if not cc.isdigit() or len(cc) not in [15, 16]:
            send_message(chat_id, f"❌ Invalid card number: {cc}\nMust be 15 or 16 digits")
            return
        
        if not mm.isdigit() or int(mm) < 1 or int(mm) > 12:
            send_message(chat_id, f"❌ Invalid month: {mm}\nMust be 01-12")
            return
        
        if not yy.isdigit() or len(yy) not in [2, 4]:
            send_message(chat_id, f"❌ Invalid year: {yy}\nUse 2 or 4 digits")
            return
        
        if not cvv.isdigit() or len(cvv) not in [3, 4]:
            send_message(chat_id, f"❌ Invalid CVV: {cvv}\nMust be 3 or 4 digits")
            return
        
        # Send processing message
        processing_msg = f"🔄 <b>Processing {gateway_name}...</b>\n\nCard: <code>{cc[:4]}****{cc[-4:]}|{mm}|{yy}|{cvv}</code>\n⏳ Please wait..."
        send_message(chat_id, processing_msg)
        
        # Check card
        result = gateway_func(cc, mm, yy, cvv)
        
        # Get BIN info
        bin_info = get_bin_info(cc)
        
        # Format response
        status = result.get('status', 'Declined')
        response_text = result.get('response', 'No response')
        
        brand = bin_info.get('brand', 'Unknown')
        card_type = bin_info.get('type', 'Unknown')
        country = bin_info.get('country', 'Unknown')
        country_code = bin_info.get('country_code', '')
        bank = bin_info.get('bank', 'Unknown')
        
        # Country flag emoji
        flag = ""
        if country_code and len(country_code) == 2:
            flag = f" {chr(127397 + ord(country_code[0]))}{chr(127397 + ord(country_code[1]))}"
        
        # Final message
        if status == "Approved":
            final_msg = f"""✅ <b>APPROVED ({gateway_name})</b> ✅

💳 <b>Card:</b> <code>{cc[:4]}****{cc[-4:]}|{mm}|{yy}|{cvv}</code>
📝 <b>Response:</b> {response_text}

ℹ️ <b>Info:</b> {brand} - {card_type}
🏦 <b>Issuer:</b> {bank}
🌍 <b>Country:</b> {country}{flag}

✨ Valid card detected!"""
        else:
            final_msg = f"""❌ <b>DECLINED ({gateway_name})</b> ❌

💳 <b>Card:</b> <code>{cc[:4]}****{cc[-4:]}|{mm}|{yy}|{cvv}</code>
📝 <b>Response:</b> {response_text}

ℹ️ <b>Info:</b> {brand} - {card_type}
🏦 <b>Issuer:</b> {bank}
🌍 <b>Country:</b> {country}{flag}"""
        
        send_message(chat_id, final_msg)
        
    except Exception as e:
        logger.error(f"Process error: {str(e)}")
        send_message(chat_id, f"❌ Error: {str(e)[:150]}")

# --- Delete Webhook ---
def delete_webhook():
    """Delete webhook to use polling"""
    url = TELEGRAM_API_URL + "deleteWebhook"
    try:
        response = requests.post(url, json={'drop_pending_updates': True})
        logger.info(f"Webhook deleted: {response.json()}")
        return True
    except Exception as e:
        logger.error(f"Delete webhook error: {str(e)}")
        return False

# --- Get Updates (Polling) ---
def get_updates(offset=None):
    """Get updates from Telegram"""
    url = TELEGRAM_API_URL + "getUpdates"
    params = {'timeout': 20, 'allowed_updates': ['message']}
    if offset:
        params['offset'] = offset
    
    try:
        response = requests.get(url, params=params, timeout=25)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                return data.get('result', [])
    except Exception as e:
        logger.error(f"Get updates error: {str(e)}")
    return []

# --- Bot Polling Loop ---
def bot_polling():
    """Main bot polling loop"""
    global last_update_id, bot_running
    
    logger.info("Starting bot polling...")
    
    # Delete webhook first
    delete_webhook()
    time.sleep(1)
    
    # Test bot connection
    try:
        resp = requests.get(TELEGRAM_API_URL + "getMe", timeout=10)
        bot_info = resp.json()
        if bot_info.get('ok'):
            logger.info(f"✅ Bot connected: @{bot_info['result']['username']}")
        else:
            logger.error("❌ Bot connection failed")
            return
    except Exception as e:
        logger.error(f"❌ Cannot connect: {str(e)}")
        return
    
    logger.info("🤖 Bot is running! Waiting for commands...")
    
    while bot_running:
        try:
            updates = get_updates(last_update_id + 1 if last_update_id else None)
            
            for update in updates:
                last_update_id = update['update_id']
                
                if 'message' in update:
                    msg = update['message']
                    chat_id = msg['chat']['id']
                    text = msg.get('text', '').strip()
                    username = msg['chat'].get('username', msg['chat'].get('first_name', 'User'))
                    
                    if not text:
                        continue
                    
                    logger.info(f"📨 {username}: {text[:50]}")
                    
                    # --- Command: /start ---
                    if text == '/start':
                        welcome = f"""🚀 <b>Card Checker Bot Active!</b> 🚀

<b>Welcome {username}!</b>

<b>📝 Commands:</b>

<code>/stripe_auth CC|MM|YY|CVV</code>
  ↳ Check card with Stripe Auth
  ↳ Fast response

<code>/stripe_charge CC|MM|YY|CVV</code>
  ↳ Check with $0.50 authorization
  ↳ More accurate

<code>/braintree CC|MM|YY|CVV</code>
  ↳ Braintree gateway check

<b>📌 Example:</b>
<code>/stripe_auth 4111111111111111|12|25|123</code>

<b>⚡ Status:</b> Active
<b>🔧 Mode:</b> {'LIVE' if 'live' in STRIPE_SECRET_KEY else 'TEST'}"""
                        send_message(chat_id, welcome)
                    
                    # --- Command: /stripe_auth ---
                    elif text.startswith('/stripe_auth'):
                        parts = text.split(maxsplit=1)
                        if len(parts) < 2:
                            send_message(chat_id, "❌ Missing card!\n\nFormat: <code>/stripe_auth CC|MM|YY|CVV</code>")
                            continue
                        
                        card_str = parts[1].strip()
                        
                        if not re.match(r'^\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', card_str):
                            send_message(chat_id, "❌ Invalid format!\n\nUse: <code>CC|MM|YY|CVV</code>\nExample: <code>4111111111111111|12|25|123</code>")
                            continue
                        
                        thread = threading.Thread(target=process_card, args=(chat_id, card_str, stripe_auth_check, "Stripe Auth"))
                        thread.daemon = True
                        thread.start()
                    
                    # --- Command: /stripe_charge ---
                    elif text.startswith('/stripe_charge'):
                        parts = text.split(maxsplit=1)
                        if len(parts) < 2:
                            send_message(chat_id, "❌ Missing card!\n\nFormat: <code>/stripe_charge CC|MM|YY|CVV</code>")
                            continue
                        
                        card_str = parts[1].strip()
                        
                        if not re.match(r'^\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', card_str):
                            send_message(chat_id, "❌ Invalid format!\n\nUse: <code>CC|MM|YY|CVV</code>")
                            continue
                        
                        thread = threading.Thread(target=process_card, args=(chat_id, card_str, stripe_charge_check, "Stripe Charge"))
                        thread.daemon = True
                        thread.start()
                    
                    # --- Command: /braintree ---
                    elif text.startswith('/braintree'):
                        parts = text.split(maxsplit=1)
                        if len(parts) < 2:
                            send_message(chat_id, "❌ Missing card!\n\nFormat: <code>/braintree CC|MM|YY|CVV</code>")
                            continue
                        
                        card_str = parts[1].strip()
                        
                        if not re.match(r'^\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', card_str):
                            send_message(chat_id, "❌ Invalid format!\n\nUse: <code>CC|MM|YY|CVV</code>")
                            continue
                        
                        thread = threading.Thread(target=process_card, args=(chat_id, card_str, braintree_check, "Braintree"))
                        thread.daemon = True
                        thread.start()
                    
                    # --- Unknown command ---
                    elif text.startswith('/'):
                        send_message(chat_id, f"❌ Unknown command: {text}\n\nType /start for help")
            
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Polling error: {str(e)}")
            time.sleep(5)

# --- Flask Routes ---
@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "bot": "Card Checker Bot",
        "mode": "polling",
        "commands": ["/start", "/stripe_auth", "/stripe_charge", "/braintree"]
    })

@app.route('/status')
def status():
    return jsonify({
        "status": "active",
        "last_update_id": last_update_id,
        "stripe_mode": "LIVE" if "live" in STRIPE_SECRET_KEY else "TEST"
    })

@app.route('/stop')
def stop():
    global bot_running
    bot_running = False
    return jsonify({"status": "stopping"})

# --- Main Entry Point ---
if __name__ == '__main__':
    # Start bot polling in background thread
    poll_thread = threading.Thread(target=bot_polling)
    poll_thread.daemon = True
    poll_thread.start()
    
    # Run Flask app (for Render)
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
