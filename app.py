import os
import re
import random
import string
import threading
import requests
import stripe
from flask import Flask, request, jsonify

# ---------- Konfigurasi ----------
BOT_TOKEN = '8323578379:AAFDGDFlHEEakTK3Mw49ANizwsbewPAaWKo'
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Stripe Secret Key dari environment variable
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
if not STRIPE_SECRET_KEY:
    raise Exception("STRIPE_SECRET_KEY environment variable not set")
stripe.api_key = STRIPE_SECRET_KEY

app = Flask(__name__)

# ---------- Helper BIN ----------
def get_bin_info(bin_number):
    try:
        resp = requests.get(f'https://bins.antipublic.cc/bins/{bin_number}')
        return resp.json() if resp.status_code == 200 else {}
    except:
        return {}

# ---------- Stripe Charge $5 (live) ----------
def stripe_charge_check(cc, mm, yy, cvv):
    try:
        # Format exp year
        if len(yy) == 2:
            yy = 2000 + int(yy)
        else:
            yy = int(yy)

        intent = stripe.PaymentIntent.create(
            amount=500,  # $5 = 500 cents
            currency='usd',
            payment_method_types=['card'],
            description='Bot charge $5'
        )

        # Confirm with card details
        confirm = stripe.PaymentIntent.confirm(
            intent.id,
            payment_method_data={
                'type': 'card',
                'card': {
                    'number': cc,
                    'exp_month': int(mm),
                    'exp_year': yy,
                    'cvc': cvv,
                }
            }
        )

        if confirm.status == 'succeeded':
            return {
                "status": "Approved",
                "response": f"✅ Charged $5 successfully! PaymentIntent: {confirm.id}",
                "decline_type": "none"
            }
        else:
            return {
                "status": "Declined",
                "response": f"Status: {confirm.status}",
                "decline_type": "card_decline"
            }

    except stripe.error.CardError as e:
        return {
            "status": "Declined",
            "response": e.error.message,
            "decline_type": "card_decline"
        }
    except Exception as e:
        return {
            "status": "Declined",
            "response": str(e),
            "decline_type": "process_error"
        }

# ---------- Background task untuk Telegram (edit message) ----------
def background_task(chat_id, message_id, full_cc_string, gateway_func, gateway_name):
    cc, mm, yy, cvv = full_cc_string.split('|')
    result = gateway_func(cc, mm, yy, cvv)
    bin_info = get_bin_info(cc[:6])

    status = result.get('status', 'Declined')
    response_text = result.get('response', 'No response')
    brand = bin_info.get('brand', 'Unknown')
    card_type = bin_info.get('type', 'Unknown')
    country = bin_info.get('country_name', 'Unknown')
    country_flag = bin_info.get('country_flag', '')
    bank = bin_info.get('bank', 'Unknown')

    if status == "Approved":
        final_message = f"""<b>✅ APPROVED ({gateway_name})</b>

<b>Card:</b> <code>{full_cc_string}</code>
<b>Response:</b> {response_text}

<b>Info:</b> {brand} - {card_type}
<b>Issuer:</b> {bank}
<b>Country:</b> {country} {country_flag}"""
    else:
        final_message = f"""<b>❌ DECLINED ({gateway_name})</b>

<b>Card:</b> <code>{full_cc_string}</code>
<b>Response:</b> {response_text}

<b>Info:</b> {brand} - {card_type}
<b>Issuer:</b> {bank}
<b>Country:</b> {country} {country_flag}"""

    url = TELEGRAM_API_URL + "editMessageText"
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': final_message,
        'parse_mode': 'HTML'
    }
    requests.post(url, json=payload)

# ---------- Webhook Telegram ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"ok": True})

    message = data['message']
    chat_id = message['chat']['id']
    text = message.get('text', '')

    # Format: cc|mm|yy|cvv
    if '|' not in text:
        # Kirim pesan balasan instruksi
        send_message(chat_id, "❌ Kirim dalam format:\n`4111111111111111|12|26|123`\n\nGunakan Stripe Charge $5 (secret key live)")
        return jsonify({"ok": True})

    parts = text.split('|')
    if len(parts) != 4:
        send_message(chat_id, "❌ Format salah. Contoh: `4111111111111111|12|26|123`")
        return jsonify({"ok": True})

    cc, mm, yy, cvv = parts
    if not (cc.isdigit() and mm.isdigit() and yy.isdigit() and cvv.isdigit()):
        send_message(chat_id, "❌ Hanya angka yang diperbolehkan.")
        return jsonify({"ok": True})

    # Kirim pesan "Processing..." lalu edit nanti
    sent_msg = send_message(chat_id, "⏳ Processing Stripe Charge $5... Please wait", parse_mode=None)
    if not sent_msg:
        return jsonify({"ok": True})

    message_id = sent_msg['result']['message_id']

    # Jalankan background thread
    full_cc = f"{cc}|{mm}|{yy}|{cvv}"
    thread = threading.Thread(
        target=background_task,
        args=(chat_id, message_id, full_cc, stripe_charge_check, "Stripe Charge $5")
    )
    thread.start()

    return jsonify({"ok": True})

def send_message(chat_id, text, parse_mode='HTML'):
    url = TELEGRAM_API_URL + "sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        return resp.json()
    return None

# ---------- Health check ----------
@app.route('/')
def home():
    return "Stripe Charge $5 Bot (Secret Key) is running on Render"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
