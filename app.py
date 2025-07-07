from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import random
import requests

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Replace with a secure key

EASYPAY_API_URL = "https://www.easypay.co.ug/api/"
EASYPAY_USERNAME = "331d3b1290d90f31"      # Your client id
EASYPAY_PASSWORD = "7377396e883e612a"      # Your secret key
CALLBACK_URL = "https://ancient-thicket-16292.herokuapp.com/webhook"  # Your webhook URL

# --------------------------
# Database initialization
# --------------------------
def init_db():
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()

        # Update payments table to add reference and status
        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                nin TEXT NOT NULL,
                phone TEXT NOT NULL,
                amount INTEGER NOT NULL,
                member_id TEXT,
                reference TEXT UNIQUE,
                status TEXT DEFAULT 'Pending',
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

# --------------------------
# Helper functions
# --------------------------
def generate_member_id():
    number = random.randint(10000, 99999)
    return f"TM{number}"

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
    phone = request.form['phone']
    amount = int(request.form.get('amount', 15000))
    member_id = generate_member_id()

    # Create unique reference combining member_id and random suffix
    reference = f"{member_id}-{random.randint(1000,9999)}"

    # Build payload for EasyPay mmdeposit
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

    # Call EasyPay API
    try:
        response = requests.post(EASYPAY_API_URL, json=payload, timeout=15)
        data = response.json()
    except Exception as e:
        return f"Error contacting EasyPay API: {str(e)}", 500

    if data.get("success") != 1:
        err = data.get("errormsg", "Unknown error")
        return f"Payment initiation failed: {err}", 400

    # Save payment as pending in DB
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO payments (name, nin, phone, amount, member_id, reference, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, nin, phone, amount, member_id, reference, "Pending")
        )
        conn.commit()

    # Show pending page telling user to complete payment on their phone
    return render_template("payment_pending.html", name=name, member_id=member_id, reference=reference)

@app.route('/thankyou')
def thankyou():
    member_id = request.args.get('member_id')
    name = request.args.get('name')
    return render_template('thankyou.html', member_id=member_id, name=name)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("✅ Webhook received:", data)

    # Optional: Validate the secret if EasyPay sends it (not in docs, so skip or implement if provided)
    # received_secret = data.get('secret')
    # if received_secret != EASYPAY_PASSWORD:
    #     return "Invalid secret", 403

    reference = data.get("reference")
    transaction_id = data.get("transactionId")
    phone = data.get("phone")
    amount = data.get("amount")

    if not reference:
        return "Missing reference", 400

    # Update payment record status to Confirmed
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("UPDATE payments SET status = 'Confirmed' WHERE reference = ?", (reference,))
        conn.commit()

    print(f"Payment confirmed for reference: {reference}, transaction ID: {transaction_id}")

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
        referral_counts = c.fetchall()

        c.execute('SELECT * FROM withdrawals')
        withdrawals = c.fetchall()

    return render_template('admin.html', payments=payments, referrals=referral_counts, withdrawals=withdrawals)

@app.route('/login', methods=['GET', 'POST'])
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
            else:
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

    return render_template('dashboard.html',
                           member=member,
                           total_earnings=total_earnings,
                           referral_count=referral_count,
                           total_withdrawn=total_withdrawn,
                           withdrawals=withdrawals)

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

# --------------------------
# Main entry
# --------------------------
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
