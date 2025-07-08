from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import random
import requests
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

EASYPAY_API_URL = "https://www.easypay.co.ug/api/"
EASYPAY_USERNAME = "331d3b1290d90f31"
EASYPAY_PASSWORD = "7377396e883e612a"
CALLBACK_URL = "https://ancient-thicket-16292.herokuapp.com/webhook"

# --------------------------
# Database initialization
# --------------------------
def init_db():
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()

        # Create table if not exists
        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                nin TEXT NOT NULL,
                phone TEXT NOT NULL,
                amount INTEGER NOT NULL,
                member_id TEXT,
                status TEXT DEFAULT 'Pending',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Add missing columns if not exist
        try:
            c.execute("ALTER TABLE payments ADD COLUMN reference TEXT UNIQUE")
        except sqlite3.OperationalError:
            pass  # column already exists

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

# --------------------------
# Helper functions
# --------------------------
def generate_member_id():
    number = random.randint(10000, 99999)
    return f"TM{number}"

def normalize_phone(phone):
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("256"):
        return phone
    if phone.startswith("0"):
        return "256" + phone[1:]
    if phone.startswith(("7","3")):
        return "256" + phone
    return phone

# --------------------------
# Routes
# --------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/payment')
def payment():
    return render_template('payment.html')

@app.route('/process_payment', methods=['POST'])
def process_payment():
    name = request.form['name']
    nin = request.form['nin']
    raw_phone = request.form['phone']
    phone = normalize_phone(raw_phone)
    amount = int(request.form.get('amount', 15000))
    member_id = generate_member_id()
    reference = f"{member_id}-{random.randint(1000,9999)}"

    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO payments (name, nin, phone, amount, member_id, reference) VALUES (?, ?, ?, ?, ?, ?)",
            (name, nin, phone, amount, member_id, reference)
        )
        conn.commit()

    payload = {
        "username": EASYPAY_USERNAME,
        "password": EASYPAY_PASSWORD,
        "action": "mmdeposit",
        "amount": amount,
        "currency": "UGX",
        "phone": phone,
        "reference": reference,
        "reason": "Team15 membership payment"
    }

    try:
        response = requests.post(EASYPAY_API_URL, json=payload, timeout=120)
        data = response.json()
    except requests.exceptions.Timeout:
        data = {"success": 0, "errormsg": "Request timed out. Complete payment on your phone."}
    except Exception as e:
        return f"Error contacting EasyPay API: {str(e)}", 500

    with open("easypay_response_log.txt", "a") as f:
        f.write(f"Ref {reference}: {data}\n")

    return render_template(
        "payment_pending.html",
        name=name,
        member_id=member_id,
        reference=reference,
        easypay_status=data.get("success"),
        easypay_message=data.get("errormsg", "Awaiting confirmation.")
    )

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
    return render_template('thankyou.html', member_id=member_id, name=name)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    reference = data.get('reference')
    if not reference:
        return "Missing reference", 400

    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("UPDATE payments SET status='Confirmed' WHERE reference = ?", (reference,))
        conn.commit()

    with open("webhook_log.txt", "a") as f:
        f.write(str(data) + "\n")

    return jsonify({"success": 1})

@app.route('/admin')
def admin():
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM payments")
        payments = c.fetchall()
        c.execute('''
            SELECT referrer_member_id, COUNT(*) as count
            FROM referrals
            GROUP BY referrer_member_id
        ''')
        referrals = c.fetchall()
        c.execute("SELECT * FROM withdrawals")
        withdrawals = c.fetchall()
    return render_template('admin.html', payments=payments, referrals=referrals, withdrawals=withdrawals)

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        member_id = request.form['member_id']
        with sqlite3.connect('database.db') as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM payments WHERE member_id = ? AND status = 'Confirmed'", (member_id,))
            member = c.fetchone()
            if member:
                session['member_id'] = member_id
                return redirect(url_for('dashboard'))
            error = "Invalid Member ID or payment not confirmed yet."
    return render_template('login.html', error=error)

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
        c.execute("SELECT SUM(amount) FROM withdrawals WHERE member_id = ?", (member_id,))
        total_withdrawn = c.fetchone()[0] or 0
        c.execute("SELECT * FROM withdrawals WHERE member_id = ? ORDER BY timestamp DESC", (member_id,))
        withdrawals = c.fetchall()
    return render_template('dashboard.html', member=member, total_earnings=total_earnings, referral_count=referral_count, total_withdrawn=total_withdrawn, withdrawals=withdrawals)

@app.route('/request_withdrawal', methods=['POST'])
def request_withdrawal():
    if 'member_id' not in session:
        return redirect(url_for('login'))
    amount = request.form['amount']
    member_id = session['member_id']
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("INSERT INTO withdrawals (member_id, amount) VALUES (?, ?)", (member_id, amount))
        conn.commit()
    return redirect(url_for('dashboard'))

@app.route('/approve_withdrawal/<int:id>')
def approve_withdrawal(id):
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("UPDATE withdrawals SET status = 'Approved' WHERE id = ?", (id,))
        conn.commit()
    return redirect(url_for('admin'))

@app.route('/reject_withdrawal/<int:id>')
def reject_withdrawal(id):
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("UPDATE withdrawals SET status = 'Rejected' WHERE id = ?", (id,))
        conn.commit()
    return redirect(url_for('admin'))

@app.route('/logout')
def logout():
    session.pop('member_id', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

