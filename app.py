from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
from functools import wraps
import sqlite3
import logging

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ✅ Database connection
def get_db_connection():
    conn = sqlite3.connect('team15.db')
    conn.row_factory = sqlite3.Row
    return conn

# ✅ Generate unique member ID
def generate_member_id():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT member_id FROM users WHERE member_id LIKE 'T15-%'")
        existing_ids = [int(row['member_id'].split('-')[1]) for row in c.fetchall() if row['member_id']]
        next_id = max(existing_ids, default=1000) + 1
    return f"T15-{next_id}"

# ✅ Admin login decorator
def admin_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'logged_in' not in session or not session.get('is_admin'):
            flash('Admin access required', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

# ✅ Initialize DB
def init_db():
    with sqlite3.connect('team15.db') as conn:
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fullname TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            referral_id TEXT NOT NULL,
            password TEXT NOT NULL,
            is_active INTEGER DEFAULT 0,
            balance INTEGER DEFAULT 0,
            member_id TEXT UNIQUE,
            registration_date TEXT,
            activated_by TEXT,
            activation_date TEXT,
            is_admin INTEGER DEFAULT 0
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            FOREIGN KEY(referrer_id) REFERENCES users(id),
            FOREIGN KEY(referred_id) REFERENCES users(id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            payment_date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            request_date TEXT,
            processed_by INTEGER,
            process_date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(processed_by) REFERENCES users(id)
        )''')

        # Default admins
        admins = [
            {'phone': '0701618842', 'member_id': 'TM00001', 'password': 'admin123', 'balance': 13000},
            {'phone': '0394005261', 'member_id': 'TM00002', 'password': 'admin123', 'balance': 0},
            {'phone': '0762597375', 'member_id': 'TM00003', 'password': 'admin123', 'balance': 0}
        ]
        for admin in admins:
            c.execute("SELECT id FROM users WHERE phone = ?", (admin['phone'],))
            if not c.fetchone():
                registration_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                c.execute('''INSERT INTO users 
                    (fullname, phone, referral_id, password, is_active, 
                     balance, member_id, registration_date, is_admin)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (f"Admin {admin['member_id']}", admin['phone'], 'SYSTEM', admin['password'], 1,
                     admin['balance'], admin['member_id'], registration_date, 1))

        conn.commit()

init_db()

# ✅ Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE phone = ? AND password = ?", (phone, password))
            user = c.fetchone()

            if user:
                session['user_id'] = user['id']
                session['logged_in'] = True
                session['is_admin'] = user['is_admin']
                session['member_id'] = user['member_id']

                if user['is_admin']:
                    return redirect(url_for('admin_dashboard'))
                elif user['is_active']:
                    return redirect(url_for('user_dashboard'))
                else:
                    flash('Your account is not yet activated.', 'warning')
                    return redirect(url_for('login'))
            else:
                flash('Invalid credentials.', 'danger')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fullname = request.form.get('fullname')
        phone = request.form.get('phone')
        referral_id = request.form.get('referral_id')
        password = request.form.get('password')

        if not all([fullname, phone, referral_id, password]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        try:
            with get_db_connection() as conn:
                c = conn.cursor()

                c.execute("SELECT id FROM users WHERE phone = ?", (phone,))
                if c.fetchone():
                    flash('Phone number already exists.', 'warning')
                    return redirect(url_for('register'))

                c.execute("SELECT id FROM users WHERE member_id = ?", (referral_id,))
                referrer = c.fetchone()
                if not referrer:
                    flash('Invalid referral ID.', 'warning')
                    return redirect(url_for('register'))

                member_id = generate_member_id()
                registration_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                c.execute('''INSERT INTO users 
                             (fullname, phone, referral_id, password, is_active, 
                              balance, member_id, registration_date)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                          (fullname, phone, referral_id, password, 0, 0, member_id, registration_date))
                user_id = c.lastrowid

                c.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", 
                          (referrer['id'], user_id))

                conn.commit()
                return redirect(url_for('instructions'))

        except Exception as e:
            flash('Registration failed: ' + str(e), 'danger')
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/instructions')
def instructions():
    return render_template('instructions.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/dashboard')
def user_dashboard():
    if 'logged_in' not in session or session.get('is_admin'):
        return redirect(url_for('login'))

    user_id = session['user_id']
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = c.fetchone()

        c.execute("SELECT SUM(amount) FROM payments WHERE user_id = ?", (user_id,))
        total_earnings = c.fetchone()[0] or 0

        c.execute("SELECT SUM(amount) FROM withdrawals WHERE user_id = ? AND status = 'paid'", (user_id,))
        total_withdrawals = c.fetchone()[0] or 0

        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
        direct_referrals = c.fetchone()[0] or 0

        user = dict(user)
        user['total_earnings'] = total_earnings
        user['total_withdrawals'] = total_withdrawals
        user['direct_referrals'] = direct_referrals

    return render_template('user/dashboard.html', user=user)

@app.route('/withdraw', methods=['POST'])
def withdraw():
    if 'logged_in' not in session or session.get('is_admin'):
        flash('Login required', 'danger')
        return redirect(url_for('login'))

    user_id = session['user_id']
    amount = request.form.get('amount', type=int)
    method = request.form.get('method')

    if not amount or amount <= 0:
        flash('Please enter a valid withdrawal amount.', 'warning')
        return redirect(url_for('user_dashboard'))

    if method not in ['mtn', 'airtel']:
        flash('Invalid withdrawal method selected.', 'warning')
        return redirect(url_for('user_dashboard'))

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        user = c.fetchone()

        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('login'))

        if amount > user['balance']:
            flash('Insufficient balance for withdrawal.', 'warning')
            return redirect(url_for('user_dashboard'))

        new_balance = user['balance'] - amount
        c.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user_id))

        request_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''INSERT INTO withdrawals (user_id, amount, status, request_date)
                     VALUES (?, ?, ?, ?)''', (user_id, amount, 'pending', request_date))

        conn.commit()

    flash('Withdrawal request submitted successfully!', 'success')
    return redirect(url_for('user_dashboard'))

# 🔐 Admin Panel Routes
@app.route('/admin/dashboard')
@admin_login_required
def admin_dashboard():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''SELECT u.*, COUNT(r.referred_id) as referrals_count
                     FROM users u
                     LEFT JOIN referrals r ON u.id = r.referrer_id
                     GROUP BY u.id
                     ORDER BY u.registration_date DESC''')
        users = c.fetchall()

        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        active_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE is_active = 0")
        pending_users = c.fetchone()[0]

        c.execute("SELECT SUM(balance) FROM users")
        total_balance = c.fetchone()[0] or 0

    return render_template('admin/dashboard.html',
                           users=users,
                           total_users=total_users,
                           active_users=active_users,
                           pending_users=pending_users,
                           total_balance=total_balance)

@app.route('/admin/user-management')
@admin_login_required
def admin_user_management():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''SELECT u.*, COUNT(r.referred_id) as referrals_count
                     FROM users u
                     LEFT JOIN referrals r ON u.id = r.referrer_id
                     GROUP BY u.id
                     ORDER BY u.registration_date DESC''')
        users = c.fetchall()

    return render_template('admin/users.html', users=users)

@app.route('/admin/payment-management')
@admin_login_required
def admin_payment_management():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''SELECT p.*, u.member_id, u.fullname 
                     FROM payments p
                     JOIN users u ON p.user_id = u.id
                     ORDER BY p.payment_date DESC''')
        payments = c.fetchall()

    return render_template('admin/payments.html', payments=payments)

@app.route('/admin/withdrawal-management')
@admin_login_required
def admin_withdrawal_management():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''SELECT w.*, u.member_id, u.fullname 
                     FROM withdrawals w
                     JOIN users u ON w.user_id = u.id
                     ORDER BY w.request_date DESC''')
        withdrawals = c.fetchall()

    return render_template('admin/withdrawals.html', withdrawals=withdrawals)

@app.route('/admin/activate-user/<int:user_id>')
@admin_login_required
def admin_activate_user(user_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        activation_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Activate the user
        c.execute('''UPDATE users 
                     SET is_active = 1, 
                         activation_date = ?,
                         activated_by = ?
                     WHERE id = ?''',
                 (activation_date, session['user_id'], user_id))
        
        # Find the referrer
        c.execute('''SELECT referrer_id 
                     FROM referrals 
                     WHERE referred_id = ?''', (user_id,))
        referrer = c.fetchone()
        
        if referrer:
            # Add 5000 to referrer's balance
            c.execute('''UPDATE users 
                         SET balance = balance + 5000 
                         WHERE id = ?''', (referrer['referrer_id'],))
            
            # Log the referral bonus payment
            payment_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''INSERT INTO payments (user_id, amount, payment_date)
                         VALUES (?, ?, ?)''',
                     (referrer['referrer_id'], 5000, payment_date))

        conn.commit()

    flash('User activated successfully! Referrer received 5000 bonus.', 'success')
    return redirect(url_for('admin_user_management'))

@app.route('/admin/deactivate-user/<int:user_id>')
@admin_login_required
def admin_deactivate_user(user_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        # Check if user exists and is not an admin
        c.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
        user = c.fetchone()
        
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('admin_user_management'))
            
        if user['is_admin']:
            flash('Cannot deactivate an admin account.', 'warning')
            return redirect(url_for('admin_user_management'))
            
        # Deactivate the user
        c.execute('''UPDATE users 
                     SET is_active = 0,
                         activation_date = NULL,
                         activated_by = NULL
                     WHERE id = ?''',
                 (user_id,))
        conn.commit()

    flash('User deactivated successfully!', 'success')
    return redirect(url_for('admin_user_management'))

@app.route('/admin/process-withdrawal/<int:withdrawal_id>')
@admin_login_required
def admin_process_withdrawal(withdrawal_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        process_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''UPDATE withdrawals 
                     SET status = 'paid',
                         processed_by = ?,
                         process_date = ?
                     WHERE id = ?''',
                 (session['user_id'], process_date, withdrawal_id))
        conn.commit()

    flash('Withdrawal processed successfully!', 'success')
    return redirect(url_for('admin_withdrawal_management'))

# ✅ Run
if __name__ == '__main__':
    app.run(debug=True)