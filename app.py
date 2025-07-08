from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import random
import requests
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# EasyPay Configuration
EASYPAY_API_URL = "https://www.easypay.co.ug/api/"
EASYPAY_USERNAME = "331d3b1290d90f31"
EASYPAY_PASSWORD = "7377396e883e612a"
CALLBACK_URL = "https://ancient-thicket-16292.herokuapp.com/webhook"
STANDARD_AMOUNT = 15000  # UGX

# Database initialization
def init_db():
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()

        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                nin TEXT NOT NULL,
                phone TEXT NOT NULL,
                amount INTEGER NOT NULL,
                member_id TEXT,
                status TEXT DEFAULT 'Pending',
                reference TEXT UNIQUE,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_member_id TEXT NOT NULL,
                referred_member_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                type TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT DEFAULT 'Pending',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()

# Helper functions
def generate_member_id():
    return f"TM{random.randint(10000, 99999)}"

def normalize_phone(phone):
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("256"):
        return phone
    if phone.startswith("0"):
        return "256" + phone[1:]
    if phone.startswith(("7","3")):
        return "256" + phone
    return phone

def log_payment_attempt(reference, data):
    with open("payment_attempts.log", "a") as f:
        f.write(f"{datetime.now()} - {reference}: {data}\n")

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/payment')
def payment():
    return render_template('payment.html')

@app.route('/process_payment', methods=['POST'])
def process_payment():
    try:
        # Get and validate form data
        name = request.form['name']
        nin = request.form['nin']
        raw_phone = request.form['phone']
        phone = normalize_phone(raw_phone)
        amount = STANDARD_AMOUNT
        member_id = generate_member_id()
        reference = f"{member_id}-{random.randint(1000,9999)}"

        # Store payment in database as Pending
        with sqlite3.connect('database.db') as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO payments (name, nin, phone, amount, member_id, reference, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, nin, phone, amount, member_id, reference, 'Pending')
            )
            conn.commit()

        # Prepare EasyPay payload
        payload = {
            "username": EASYPAY_USERNAME,
            "password": EASYPAY_PASSWORD,
            "action": "mmdeposit",
            "amount": amount,
            "currency": "UGX",
            "phone": phone,
            "reference": reference,
            "reason": "Team15 Membership",
            "callback_url": CALLBACK_URL
        }

        # Initiate payment with EasyPay
        try:
            response = requests.post(EASYPAY_API_URL, json=payload, timeout=30)
            response.raise_for_status()
            api_response = response.json()
            
            # Log the API response
            log_payment_attempt(reference, api_response)
            
            if api_response.get('success') == 1:
                # Payment initiated successfully - show pending page
                return render_template(
                    "payment_pending.html",
                    name=name,
                    member_id=member_id,
                    reference=reference,
                    phone=phone[-9:]  # Show last 9 digits for user confirmation
                )
            else:
                # Payment initiation failed
                error_msg = api_response.get('errormsg', 'Payment initiation failed')
                return render_template(
                    "payment_error.html",
                    error_message=error_msg,
                    member_id=member_id
                )
                
        except requests.exceptions.RequestException as e:
            # API request failed
            error_msg = f"Payment service unavailable: {str(e)}"
            log_payment_attempt(reference, f"API Error: {error_msg}")
            return render_template(
                "payment_error.html",
                error_message=error_msg,
                member_id=member_id
            )

    except Exception as e:
        # General processing error
        error_msg = f"An error occurred: {str(e)}"
        log_payment_attempt("N/A", f"Processing Error: {error_msg}")
        return render_template(
            "payment_error.html",
            error_message="System error. Please try again later.",
            member_id="N/A"
        ), 500

@app.route('/payment_status/<reference>')
def payment_status(reference):
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("SELECT status FROM payments WHERE reference = ?", (reference,))
        row = c.fetchone()
        return jsonify({"status": row[0]}) if row else (jsonify({"status": "NotFound"}), 404

@app.route('/thankyou')
def thankyou():
    member_id = request.args.get('member_id')
    name = request.args.get('name')
    
    if not member_id or not name:
        return redirect(url_for('payment'))
    
    return render_template('thankyou.html', 
                         member_id=member_id, 
                         name=name)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        reference = data.get('reference')
        status = data.get('status', '').lower()
        
        if not reference:
            return jsonify({"success": 0, "error": "Missing reference"}), 400

        # Validate the payment status
        if status not in ['success', 'completed', 'confirmed']:
            return jsonify({"success": 0, "error": "Invalid status"}), 400

        with sqlite3.connect('database.db') as conn:
            c = conn.cursor()
            
            # Update payment status
            c.execute(
                "UPDATE payments SET status='Confirmed' WHERE reference = ?",
                (reference,)
            )
            
            # Get member details
            c.execute(
                "SELECT member_id, name FROM payments WHERE reference = ?",
                (reference,)
            )
            payment = c.fetchone()
            
            if payment:
                member_id, name = payment
                # Record referral if applicable
                # [Add your referral logic here if needed]
                
            conn.commit()

        # Log successful webhook
        with open("webhook_log.txt", "a") as f:
            f.write(f"{datetime.now()} - {reference}: {data}\n")

        return jsonify({"success": 1})

    except Exception as e:
        # Log webhook error
        with open("webhook_errors.txt", "a") as f:
            f.write(f"{datetime.now()} - Error: {str(e)}\n")
        return jsonify({"success": 0, "error": str(e)}), 500

# [Keep all your other routes the same - admin, login, dashboard, etc.]

if __name__ == '__main__':
    init_db()
    app.run(debug=True)