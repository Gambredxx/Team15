import sqlite3

conn = sqlite3.connect('team15.db')
c = conn.cursor()

print("Disabling foreign keys...")
c.execute("PRAGMA foreign_keys=off;")

print("Renaming old payments table...")
c.execute("ALTER TABLE payments RENAME TO payments_old;")

print("Creating new payments table without phone column...")
c.execute('''
    CREATE TABLE payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        payment_date TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
''')

print("Copying data from old payments table...")
c.execute('''
    INSERT INTO payments (id, user_id, amount, payment_date)
    SELECT id, user_id, amount, payment_date FROM payments_old
''')

print("Dropping old payments table...")
c.execute("DROP TABLE payments_old;")

print("Enabling foreign keys...")
c.execute("PRAGMA foreign_keys=on;")

conn.commit()
conn.close()
print("Payments table schema fixed successfully.")
