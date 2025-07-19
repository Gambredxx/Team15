from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
from functools import wraps
import psycopg2
import psycopg2.extras
import logging
import requests
import os
import hashlib
import json
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key_here')

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# EasyPay Configuration
EASYPAY_CLIENT_ID = os.getenv('EASYPAY_CLIENT_ID', '331d3b1290d90f31')
EASYPAY_SECRET = os.getenv('EASYPAY_SECRET', '7377396e883e612a')
EASYPAY_API_URL = os.getenv('EASYPAY_API_URL', 'https://www.easypay.co.ug/api/')
EASYPAY_IPN_URL = os.getenv('EASYPAY_IPN_URL', 'https://your-render-app.onrender.com/easypay-webhook')

# Database connection
def get_db_connection():
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        conn.set_session(autocommit=False)
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise

# Generate unique member ID
def generate_member_id():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT member_id FROM users WHERE member_id LIKE 'T15-%'")
            existing_ids = [int(row['member_id'].split('-')[1]) for row in c.fetchall() if row['member_id']]
            next_id = max(existing_ids, default=1000) + 1
            conn.commit()
        return f"T15-{next_id}"

# Admin login decorator
def admin_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'logged_in' not in session or not session.get('is_admin'):
            flash('Admin access required', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

# Initialize DB
def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as c:
            # Create users table
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    fullname TEXT NOT NULL,
                    phone TEXT NOT NULL UNIQUE,
                    referral_id TEXT NOT NULL,
                    password TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT FALSE,
                    balance NUMERIC DEFAULT 0,
                    member_id TEXT UNIQUE,
                    registration_date TIMESTAMP,
                    activated_by TEXT,
                    activation_date TIMESTAMP,
                    is_admin BOOLEAN DEFAULT FALSE
                )
            ''')

            # Create referrals table
            c.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    referred_id INTEGER REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            # Create payments table
            c.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    amount NUMERIC,
                    payment_date TIMESTAMP,
                    transaction_id TEXT,
                    reference TEXT,
                    status TEXT DEFAULT 'pending'
                )
            ''')

            # Create withdrawals table
            c.execute('''
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    amount NUMERIC,
                    status TEXT DEFAULT 'pending',
                    request_date TIMESTAMP,
                    processed_by INTEGER REFERENCES users(id),
                    process_date TIMESTAMP,
                    member_id TEXT,
                    fullname TEXT
                )
            ''')

            # Insert default admins
            admins = [
                {'phone': '0701618842', 'member_id': 'TM00001', 'password': 'admin123', 'balance': 13000},
                {'phone': '0394005261', 'member_id': 'TM00002', 'password': 'admin123', 'balance': 0},
            ]
            for admin in admins:
                c.execute("SELECT id FROM users WHERE phone = %s", (admin['phone'],))
                if not c.fetchone():
                    registration_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    c.execute('''
                        INSERT INTO users 
                        (fullname, phone, referral_id, password, is_active, 
                         balance, member_id, registration_date, is_admin)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        f"Admin {admin['member_id']}", admin['phone'], 'SYSTEM', 
                        admin['password'], True, admin['balance'], admin['member_id'], 
                        registration_date, True
                    ))
            conn.commit()

init_db()

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
                c.execute("SELECT * FROM users WHERE phone = %s AND password = %s", (phone, password))
                user = c.fetchone()
                conn.commit()
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
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
                    c.execute("SELECT id FROM users WHERE phone = %s", (phone,))
                    if c.fetchone():
                        flash('Phone number already exists.', 'warning')
                        return redirect(url_for('register'))
                    c.execute("SELECT id FROM users WHERE member_id = %s", (referral_id,))
                    referrer = c.fetchone()
                    if not referrer:
                        flash('Invalid referral ID.', 'warning')
                        return redirect(url_for('register'))
                    member_id = generate_member_id()
                    registration_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    c.execute('''
                        INSERT INTO users 
                        (fullname, phone, referral_id, password, is_active, 
                         balance, member_id, registration_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (fullname, phone, referral_id, password, False, 0, member_id, registration_date))
                    user_id = c.fetchone()['id']
                    c.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (%s, %s)", 
                             (referrer['id'], user_id))
                    conn.commit()
                    session['user_id'] = user_id
                    session['logged_in'] = True
                    session['is_admin'] = False
                    session['member_id'] = member_id
                    return redirect(url_for('initiate_payment'))
        except Exception as e:
            flash('Registration failed: ' + str(e), 'danger')
            return redirect(url_for('register'))
    return render_template('register.html')

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
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = c.fetchone()
            c.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE user_id = %s", (user_id,))
            total_earnings = c.fetchone()['total']
            c.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM withdrawals WHERE user_id = %s AND status = 'paid'", (user_id,))
            total_withdrawals = c.fetchone()['total']
            c.execute("SELECT COUNT(*) AS count FROM referrals WHERE referrer_id = %s", (user_id,))
            direct_referrals = c.fetchone()['count']
            conn.commit()
            user = dict(user)
            user['total_earnings'] = total_earnings
            user['total_withdrawals'] = total_withdrawals
            user['direct_referrals'] = direct_referrals
    return render_template('user/dashboard.html', user=user)

@app.route('/initiate-payment', methods=['GET', 'POST'])
def initiate_payment():
    if 'logged_in' not in session or session.get('is_admin'):
        flash('Please log in to initiate payment.', 'danger')
        return redirect(url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        amount = request.form.get('amount', type=float)
        phone = request.form.get('phone')

        if not amount or amount <= 0:
            flash('Please enter a valid amount.', 'warning')
            return redirect(url_for('initiate_payment'))

        if not phone:
            flash('Please provide a valid phone number.', 'warning')
            return redirect(url_for('initiate_payment'))

        try:
            reference = f"REF{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{user_id}"

            with get_db_connection() as conn:
                with conn.cursor() as c:
                    payment_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    c.execute('''
                        INSERT INTO payments (user_id, amount, payment_date, transaction_id, reference, status)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (user_id, amount, payment_date, reference, reference, 'pending'))
                    conn.commit()

            payload = {
                "username": EASYPAY_CLIENT_ID,
                "password": EASYPAY_SECRET,
                "action": "mmdeposit",
                "amount": amount,
                "currency": "UGX",
                "phone": phone,
                "reference": reference,
                "reason": f"Team15 payment for user {session['member_id']}"
            }

            response = requests.post(EASYPAY_API_URL, json=payload, timeout=5)
            res_data = response.json()

            if res_data.get('success') == 1:
                flash('Payment initiated. Please approve the mobile money prompt on your phone, then log in to continue.', 'success')
                return redirect(url_for('login'))
            else:
                flash(f"Payment initiation failed: {res_data.get('errormsg', 'Unknown error')}. Please try again or contact support.", 'danger')
                return redirect(url_for('initiate_payment'))

        except requests.exceptions.ReadTimeout:
            flash('Payment request sent. Please approve the mobile money prompt on your phone, then log in to continue.', 'info')
            return redirect(url_for('login'))

        except Exception as e:
            logger.error(f"Payment error: {e}")
            flash(f'Payment initiation failed: {e}. Please try again or contact support.', 'danger')
            return redirect(url_for('initiate_payment'))

    return render_template('user/initiate_payment.html')

@app.route('/easypay-webhook', methods=['POST'])
def easypay_callback():
    try:
        data = request.get_json()
        reference = data.get('reference')
        amount = float(data.get('amount', 0))
        phone = data.get('phone')
        transaction_id = data.get('transactionId')

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
                c.execute("SELECT user_id FROM payments WHERE reference = %s", (reference,))
                payment = c.fetchone()
                if not payment:
                    return jsonify({'status': 'error', 'message': 'Payment not found'}), 404

                user_id = payment['user_id']

                c.execute("UPDATE payments SET status = 'completed', transaction_id = %s WHERE reference = %s", (transaction_id, reference))
                c.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, user_id))
                conn.commit()

        logger.info(f"Payment completed for reference {reference}")
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logger.error(f"IPN error: {e}")
        return jsonify({'status': 'error', 'message': 'Internal error'}), 500

@app.route('/withdraw', methods=['POST'])
def withdraw():
    if 'logged_in' not in session or session.get('is_admin'):
        flash('Login required', 'danger')
        return redirect(url_for('login'))
    user_id = session['user_id']
    amount = request.form.get('amount', type=float)
    method = request.form.get('method')
    if not amount or amount <= 0:
        flash('Please enter a valid withdrawal amount.', 'warning')
        return redirect(url_for('user_dashboard'))
    if method not in ['mtn', 'airtel']:
        flash('Invalid withdrawal method selected.', 'warning')
        return redirect(url_for('user_dashboard'))
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT balance, member_id, fullname FROM users WHERE id = %s", (user_id,))
            user = c.fetchone()
            if not user:
                flash('User not found.', 'danger')
                return redirect(url_for('login'))
            if amount > user['balance']:
                flash('Insufficient balance for withdrawal.', 'warning')
                return redirect(url_for('user_dashboard'))
            new_balance = user['balance'] - amount
            c.execute("UPDATE users SET balance = %s WHERE id = %s", (new_balance, user_id))
            request_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''
                INSERT INTO withdrawals (user_id, amount, status, request_date, member_id, fullname)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (user_id, amount, 'pending', request_date, user['member_id'], user['fullname']))
            conn.commit()
    flash('Withdrawal request submitted successfully!', 'success')
    return redirect(url_for('user_dashboard'))

@app.route('/admin/dashboard')
@admin_login_required
def admin_dashboard():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute('''
                SELECT u.*, COUNT(r.referred_id) as referrals_count
                FROM users u
                LEFT JOIN referrals r ON u.id = r.referrer_id
                GROUP BY u.id
                ORDER BY u.registration_date DESC
            ''')
            users = c.fetchall()
            c.execute('''
                SELECT w.*, u.member_id, u.fullname 
                FROM withdrawals w
                JOIN users u ON w.user_id = u.id
                ORDER BY w.request_date DESC
            ''')
            withdrawals = c.fetchall()
            conn.commit()
    return render_template('admin/dashboard.html', users=users, withdrawals=withdrawals)

@app.route('/admin/edit-user', methods=['POST'])
@admin_login_required
def admin_edit_user():
    try:
        user_id = request.form.get('user_id', type=int)
        fullname = request.form.get('fullname')
        phone = request.form.get('phone')
        referral_id = request.form.get('referral_id')
        balance = request.form.get('balance', type=float)

        if not all([user_id, fullname, phone, balance is not None]):
            flash('All required fields must be filled.', 'danger')
            return redirect(url_for('admin_dashboard'))

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
                c.execute("SELECT id FROM users WHERE phone = %s AND id != %s", (phone, user_id))
                if c.fetchone():
                    flash('Phone number already exists for another user.', 'warning')
                    return redirect(url_for('admin_dashboard'))

                if referral_id:
                    c.execute("SELECT id FROM users WHERE member_id = %s", (referral_id,))
                    if not c.fetchone():
                        flash('Invalid referral ID.', 'warning')
                        return redirect(url_for('admin_dashboard'))

                c.execute('''
                    UPDATE users 
                    SET fullname = %s, phone = %s, referral_id = %s, balance = %s
                    WHERE id = %s
                ''', (fullname, phone, referral_id or 'SYSTEM', balance, user_id))
                conn.commit()

        flash('User updated successfully!', 'success')
    except Exception as e:
        logger.error(f"User edit failed: {e}")
        flash(f'User update failed: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete-user/<int:user_id>')
@admin_login_required
def admin_delete_user(user_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
                c.execute("SELECT is_admin, balance FROM users WHERE id = %s", (user_id,))
                user = c.fetchone()
                if not user:
                    flash('User not found.', 'danger')
                    return redirect(url_for('admin_dashboard'))
                if user['is_admin']:
                    flash('Cannot delete an admin account.', 'warning')
                    return redirect(url_for('admin_dashboard'))
                if user['balance'] > 0:
                    flash('Cannot delete user with positive balance.', 'warning')
                    return redirect(url_for('admin_dashboard'))
                c.execute("SELECT id FROM withdrawals WHERE user_id = %s AND status = 'pending'", (user_id,))
                if c.fetchone():
                    flash('Cannot delete user with pending withdrawals.', 'warning')
                    return redirect(url_for('admin_dashboard'))
                c.execute("DELETE FROM users WHERE id = %s", (user_id,))  # Cascades to referrals, payments, withdrawals
                conn.commit()
        flash('User deleted successfully!', 'success')
    except Exception as e:
        logger.error(f"User deletion failed: {e}")
        flash(f'User deletion failed: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/activate-user/<int:user_id>')
@admin_login_required
def admin_activate_user(user_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
                activation_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                c.execute('''
                    UPDATE users 
                    SET is_active = TRUE, 
                        activation_date = %s,
                        activated_by = %s
                    WHERE id = %s
                ''', (activation_date, session['user_id'], user_id))
                c.execute('''
                    SELECT referrer_id 
                    FROM referrals 
                    WHERE referred_id = %s
                ''', (user_id,))
                referrer = c.fetchone()
                if referrer:
                    c.execute('''
                        UPDATE users 
                        SET balance = balance + %s 
                        WHERE id = %s
                    ''', (5000, referrer['referrer_id']))
                    payment_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    c.execute('''
                        INSERT INTO payments (user_id, amount, payment_date, status)
                        VALUES (%s, %s, %s, %s)
                    ''', (referrer['referrer_id'], 5000, payment_date, 'completed'))
                conn.commit()
        flash('User activated successfully! Referrer received 5000 bonus.', 'success')
    except Exception as e:
        logger.error(f"Activation failed: {e}")
        flash(f'Activation failed: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/deactivate-user/<int:user_id>')
@admin_login_required
def admin_deactivate_user(user_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
            user = c.fetchone()
            if not user:
                flash('User not found.', 'danger')
                return redirect(url_for('admin_dashboard'))
            if user['is_admin']:
                flash('Cannot deactivate an admin account.', 'warning')
                return redirect(url_for('admin_dashboard'))
            c.execute('''
                UPDATE users 
                SET is_active = FALSE,
                    activation_date = NULL,
                    activated_by = NULL
                WHERE id = %s
            ''', (user_id,))
            conn.commit()
    flash('User deactivated successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/process-withdrawal/<int:withdrawal_id>')
@admin_login_required
def admin_process_withdrawal(withdrawal_id):
    with get_db_connection() as conn:
        with conn.cursor() as c:
            process_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''
                UPDATE withdrawals 
                SET status = 'paid',
                    processed_by = %s,
                    process_date = %s
                WHERE id = %s
            ''', (session['user_id'], process_date, withdrawal_id))
            conn.commit()
    flash('Withdrawal processed successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/fix-payments-schema')
def fix_payments_schema():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                c.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'payments_backup')")
                if not c.fetchone()[0]:
                    c.execute("CREATE TABLE payments_backup AS SELECT * FROM payments")
                c.execute("DROP TABLE IF EXISTS payments")
                c.execute('''
                    CREATE TABLE payments (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        amount NUMERIC,
                        payment_date TIMESTAMP,
                        transaction_id TEXT,
                        reference TEXT,
                        status TEXT DEFAULT 'pending'
                    )
                ''')
                conn.commit()
        return '✅ Payments table dropped and recreated successfully.'
    except Exception as e:
        return f'❌ Failed to recreate payments table: {e}'

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))