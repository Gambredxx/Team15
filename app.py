from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import random

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Replace with a secure key

# --------------------------
# Database initialization
# --------------------------
def init_db():
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()

        # Payments table
        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                nin TEXT NOT NULL,
                phone TEXT NOT NULL,
                amount INTEGER NOT NULL,
                member_id TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Referrals table
        c.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_member_id TEXT NOT NULL,
                referred_member_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Earnings table
        c.execute('''
            CREATE TABLE IF NOT EXISTS earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                type TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Withdrawals table
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
    amount = request.form.get('amount', 15000)
    member_id = generate_member_id()

    # Store in payments
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("INSERT INTO payments (name, nin, phone, amount, member_id) VALUES (?, ?, ?, ?, ?)",
                  (name, nin, phone, amount, member_id))
        conn.commit()

    return redirect(url_for('thankyou', member_id=member_id, name=name))

@app.route('/thankyou')
def thankyou():
    member_id = request.args.get('member_id')
    name = request.args.get('name')
    return render_template('thankyou.html', member_id=member_id, name=name)

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
            c.execute("SELECT * FROM payments WHERE member_id = ?", (member_id,))
            member = c.fetchone()
            if member:
                session['member_id'] = member_id
                return redirect(url_for('dashboard'))
            else:
                error = "Invalid Member ID. Please check and try again."
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
# Webhook Endpoint
# --------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("✅ Webhook received:", data)

    # Validate secret
    received_secret = data.get('secret')
    if received_secret != '7377396e883e612a':
        print("❌ Invalid secret!")
        return "Invalid secret", 403

    # Extract payment info
    name = data.get('name', 'Unknown')
    phone = data.get('phone', 'Unknown')
    amount = data.get('amount', 0)
    member_id = generate_member_id()

    # Store payment record
    with sqlite3.connect('database.db') as conn:
        c = conn.cursor()
        c.execute("INSERT INTO payments (name, nin, phone, amount, member_id) VALUES (?, ?, ?, ?, ?)",
                  (name, "N/A", phone, amount, member_id))
        conn.commit()

    # Log to file
    with open("webhook_log.txt", "a") as f:
        f.write(str(data) + "\n")

    return "Webhook processed", 200

# --------------------------
# Main entry
# --------------------------
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
