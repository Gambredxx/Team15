from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import random
import requests
import os
from datetime import datetime
import traceback

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# EasyPay Configuration
# WARNING: Hardcoding credentials is insecure. Replace with environment variables in production:
# export EASYPAY_USERNAME="256705817050"
# export EASYPAY_PASSWORD="159367"
# export CALLBACK_URL="https://your-app.herokuapp.com/webhook"
EASYPAY_API_URL = "https://www.easypay.co.ug/api/"
EASYPAY_USERNAME = "ularker martine"
EASYPAY_PASSWORD = "159367"
CALLBACK_URL = os.environ.get('CALLBACK_URL', 'https://your-app.herokuapp.com/webhook')
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

def log_transaction(reference, message):
    with open("transaction_log.txt", "a") as f:
        f.write(f"{datetime.now()} - {reference}: {message}\n")

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
        # Get form data
        name = request.form['name']
        nin = request.form['nin']
        phone = normalize_phone(request.form['phone'])
        member_id = generate_member_id()
        reference = f"{member_id}-{random.randint(1000,9999)}"

        # Log normalized phone for debugging
        print(f"Normalized phone: {phone}")

        # Store in database
        with sqlite3.connect('database.db') as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO payments (name, nin, phone, amount, member_id, reference) VALUES (?, ?, ?, ?, ?, ?)",
                (name, nin, phone, STANDARD_AMOUNT, member_id, reference)
            )
            conn.commit()

        # Initiate EasyPay payment
        payload = {
            "username": EASYPAY_USERNAME,
            "password": EASYPAY_PASSWORD,
            "action": "mmdeposit",
            "amount": STANDARD_AMOUNT,
            "currency": "UGX",
            "phone": phone,
            "reference": reference,
            "reason": "Team15 Membership"
            # Removed callback_url as it's set in EasyPay dashboard per documentation
        }

        # Debug logging
        print(f"Sending payload to EasyPay: {payload}")
        response = requests.post(EASYPAY_API_URL, json=payload, timeout=30)
        print(f"EasyPay response status: {response.status_code}")
        print(f"EasyPay response body: {response.text}")
        response.raise_for_status()
        api_response = response.json()

        log_transaction(reference, f"Payment initiated: {api_response}")

        if api_response.get('success') == 1:
            return render_template(
                "payment_pending.html",
                name=name,
                member_id=member_id,
                reference=reference,
                phone=phone[-9:]  # Show last 9 digits
            )
        else:
            error_msg = api_response.get('errormsg', 'Payment initiation failed')
            print(f"EasyPay error: {error_msg}")
            return render_template(
                "payment_error.html",
                error_message=error_msg,
                member_id=member_id
            )

    except requests.exceptions.RequestException as e:
        error_msg = f"Payment service error: {str(e)}\n{traceback.format_exc()}"
        log_transaction("N/A", error_msg)
        print(error_msg)
        return render_template(
            "payment_error.html",
            error_message="Payment service unavailable. Please try again later.",
            member_id="N/A"
        ), 503

    except Exception as e:
        error_msg = f"System error: {str(e)}\n{traceback.format_exc()}"
        log_transaction("N/A", error_msg)
        print(error_msg)
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
        return jsonify({"status": row[0]}) if row else (jsonify({"status": "NotFound"}), 404)

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
        transaction_id = data.get('transactionId')
        amount = data.get('amount')
        phone = data.get('phone')
        
        if not reference:
            print("Webhook error: Missing reference")
            return jsonify({"success": 0, "error": "Missing reference"}), 400

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
                # Add referral logic here if needed
                
            conn.commit()

        log_transaction(reference, f"Payment confirmed via webhook: {data}")
        print(f"Webhook processed: {data}")
        return jsonify({"success": 1})

    except Exception as e:
        error_msg = f"Webhook error: {str(e)}\n{traceback.format_exc()}"
        log_transaction("N/A", error_msg)
        print(error_msg)
        return jsonify({"success": 0, "error": str(e)}), 500

# Admin routes
@app.route('/admin')
def admin():
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM payments ORDER BY timestamp DESC")
        payments = c.fetchall()
        c.execute("SELECT * FROM withdrawals ORDER BY timestamp DESC")
        withdrawals = c.fetchall()
        
    return render_template('admin.html', payments=payments, withdrawals=withdrawals)

# Member routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        member_id = request.form['member_id']
        
        with sqlite3.connect('database.db') as conn:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM payments WHERE member_id = ? AND status = 'Confirmed'",
                (member_id,)
            )
            member = c.fetchone()
            
            if member:
                session['member_id'] = member_id
                return redirect(url_for('dashboard'))
            
        return render_template('login.html', error="Invalid Member ID or payment not confirmed")
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'member_id' not in session:
        return redirect(url_for('login'))
    
    member_id = session['member_id']
    
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM payments WHERE member_id = ?", (member_id,))
        member = c.fetchone()
        
        c.execute("SELECT SUM(amount) FROM earnings WHERE member_id = ?", (member_id,))
        total_earnings = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_member_id = ?", (member_id,))
        referral_count = c.fetchone()[0]
        
        c.execute("SELECT * FROM withdrawals WHERE member_id = ? ORDER BY timestamp DESC", (member_id,))
        withdrawals = c.fetchall()
    
    return render_template(
        'dashboard.html',
        member=member,
        total_earnings=total_earnings,
        referral_count=referral_count,
        withdrawals=withdrawals
    )

@app.route('/request_withdrawal', methods=['POST'])
def request_withdrawal():
    if 'member_id' not in session:
        return redirect(url_for('login'))
    
    try:
        amount = int(request.form['amount'])
        member_id = session['member_id']
        
        with sqlite3.connect('database.db') as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO withdrawals (member_id, amount) VALUES (?, ?)",
                (member_id, amount)
            )
            conn.commit()
            
        return redirect(url_for('dashboard'))
    
    except Exception as e:
        return render_template(
            'dashboard.html',
            error_message=f"Withdrawal request failed: {str(e)}"
        ), 400

@app.route('/logout')
def logout():
    session.pop('member_id', None)
    return redirect(url_for('index'))

# Admin actions
@app.route('/admin/approve_withdrawal/<int:id>')
def approve_withdrawal(id):
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE withdrawals SET status = 'Approved' WHERE id = ?",
            (id,)
        )
        conn.commit()
    
    return redirect(url_for('admin'))

@app.route('/admin/reject_withdrawal/<int:id>')
def reject_withdrawal(id):
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE withdrawals SET status = 'Rejected' WHERE id = ?",
            (id,)
        )
        conn.commit()
    
    return redirect(url_for('admin'))

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', False))