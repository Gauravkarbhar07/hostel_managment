from flask import Flask, render_template, request, redirect, jsonify, session
import mysql.connector
from werkzeug.utils import secure_filename
import os
from datetime import date, datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------- CONFIG ----------------
UPLOAD_FOLDER = 'static/complaint_photos'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'please-change-this-secret')

# Create upload directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# MySQL Connection (configured via environment variables)
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '12345678')
DB_NAME = os.getenv('DB_NAME', 'hostel_management')

try:
    db = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
except mysql.connector.Error as err:
    print("Error connecting to database:", err)
    raise

# Ensure hostel leaves table exists
cursor = db.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS hostel_leaves (
        id INT AUTO_INCREMENT PRIMARY KEY,
        student_name VARCHAR(255),
        student_id VARCHAR(100),
        room_number VARCHAR(100),
        from_date DATE,
        to_date DATE,
        reason TEXT,
        parent_contact VARCHAR(100),
        status VARCHAR(50) DEFAULT 'Pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS turf_bookings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        student_id VARCHAR(100),
        group_name VARCHAR(255),
        slot_time VARCHAR(100),
        booking_date DATE,
        amount INT DEFAULT 280,
        payment_method VARCHAR(100),
        utr_number VARCHAR(255),
        payment_status VARCHAR(50) DEFAULT 'Pending',
        booking_status VARCHAR(50) DEFAULT 'Pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS canteen_menu (
        id INT AUTO_INCREMENT PRIMARY KEY,
        menu_date DATE NOT NULL,
        breakfast TEXT,
        lunch TEXT,
        dinner TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    -- student_profiles and attendance tables removed (simplified project)
""")

# Make sure existing table has required columns
required_columns = [
    ("group_name", "VARCHAR(255)"),
    ("amount", "INT DEFAULT 280"),
    ("payment_method", "VARCHAR(100)"),
    ("utr_number", "VARCHAR(255)"),
    ("payment_status", "VARCHAR(50) DEFAULT 'Pending'"),
    ("booking_status", "VARCHAR(50) DEFAULT 'Pending'"),
    ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
]
for column_name, column_type in required_columns:
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        ("hostel_management", "turf_bookings", column_name)
    )
    if cursor.fetchone()[0] == 0:
        cursor.execute(f"ALTER TABLE turf_bookings ADD COLUMN {column_name} {column_type}")

# Ensure existing student_id and amount columns use the expected types
cursor.execute(
    "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, COLUMN_DEFAULT FROM information_schema.COLUMNS "
    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME IN ('student_id', 'amount')",
    ("hostel_management", "turf_bookings")
)
for column_name, data_type, column_type, column_default in cursor.fetchall():
    if column_name == 'student_id' and (data_type.lower() != 'varchar' or column_type.lower() != 'varchar(10)'):
        cursor.execute("ALTER TABLE turf_bookings MODIFY COLUMN student_id VARCHAR(10)")
    if column_name == 'amount' and (data_type.lower() != 'int' or column_default != '280'):
        cursor.execute("ALTER TABLE turf_bookings MODIFY COLUMN amount INT DEFAULT 280")

# Ensure users table has the expected columns and rename legacy columns if needed
cursor.execute(
    "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
    ("hostel_management", "users")
)
existing_user_columns = {row[0] for row in cursor.fetchall()}

if 'student_name' not in existing_user_columns and 'name' in existing_user_columns:
    cursor.execute("ALTER TABLE users CHANGE COLUMN name student_name VARCHAR(255)")
    existing_user_columns.add('student_name')
    existing_user_columns.discard('name')

if 'student_id' not in existing_user_columns:
    cursor.execute("ALTER TABLE users ADD COLUMN student_id VARCHAR(50)")
    existing_user_columns.add('student_id')

if 'created_at' not in existing_user_columns:
    cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    existing_user_columns.add('created_at')

cursor.close()

# ---------------- HOME PAGE ----------------
@app.route('/')
def home():
    message = request.args.get('message')
    return render_template("login.html", message=message)

# ---------------- REGISTER SYSTEM ----------------
@app.route('/register')
def register_get():
    message = request.args.get('message')
    return render_template('register.html', message=message)

@app.route('/register', methods=['POST'])
def register_post():
    student_name = request.form.get('student_name', '').strip()
    student_id = request.form.get('student_id', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not student_name or not student_id or not email or not password:
        return redirect('/register?message=Please+fill+all+fields')

    if password != confirm_password:
        return redirect('/register?message=Passwords+do+not+match')

    cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
    if cursor.fetchone():
        cursor.close()
        return redirect('/register?message=Email+already+registered')

    cursor.execute(
        "INSERT INTO users (student_name, student_id, email, password, role) VALUES (%s, %s, %s, %s, 'student')",
        (student_name, student_id, email, password)
    )
    db.commit()
    cursor.close()
    return redirect('/?message=Registration+successful.+Please+login.')

# ---------------- LOGIN SYSTEM ----------------
@app.route('/login', methods=['POST'])
def login():
    email = request.form['email'].strip().lower()
    password = request.form['password']

    cursor = db.cursor()
    cursor.execute("SELECT role FROM users WHERE email=%s AND password=%s", (email, password))
    user = cursor.fetchone()
    cursor.close()

    if user:
        role = user[0]
        if role == "student":
            return redirect("/student")
        elif role == "admin":
            return redirect("/admin")
        elif role == "director":
            return redirect("/director")

    return redirect('/?message=Invalid+email+or+password')

# ---------------- STUDENT DASHBOARD ----------------
@app.route('/student')
def student():
    cursor = db.cursor()
    cursor.execute("SELECT message FROM alerts ORDER BY id DESC LIMIT 1")
    latest_alert = cursor.fetchone()

    cursor.execute(
        "SELECT breakfast, lunch, dinner, menu_date FROM canteen_menu WHERE menu_date = CURDATE() ORDER BY id DESC LIMIT 1"
    )
    canteen_menu = cursor.fetchone()
    cursor.close()

    return render_template("student_dashboard.html", latest_alert=latest_alert, canteen_menu=canteen_menu)

# ---------------- SUBMIT COMPLAINT ----------------
@app.route('/submit_complaint', methods=['POST'])
def submit_complaint():
    student_id = request.form['student_id']
    complaint_text = request.form['complaint']
    caption = request.form.get('caption', '')
    photo_file = request.files.get('photo', None)

    filename = None
    if photo_file and photo_file.filename != '':
        filename = secure_filename(photo_file.filename)
        photo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    cursor = db.cursor()
    query = "INSERT INTO complaints (student_id, complaint_text, status, caption, photo) VALUES (%s,%s,'Pending',%s,%s)"
    cursor.execute(query, (student_id, complaint_text, caption, filename))
    db.commit()
    cursor.close()

    return redirect("/student")

# ---------------- HOSTEL LEAVE APPLICATION ----------------
@app.route('/hostel_leave', methods=['POST'])
def hostel_leave():
    student_name = request.form['student_name']
    student_id = request.form['student_id']
    room_number = request.form['room_number']
    from_date = request.form['from_date']
    to_date = request.form['to_date']
    reason = request.form['reason']
    parent_contact = request.form['parent_contact']

    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hostel_leaves (
            id INT AUTO_INCREMENT PRIMARY KEY,
            student_name VARCHAR(255),
            student_id VARCHAR(100),
            room_number VARCHAR(100),
            from_date DATE,
            to_date DATE,
            reason TEXT,
            parent_contact VARCHAR(100),
            status VARCHAR(50) DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(
        "INSERT INTO hostel_leaves (student_name, student_id, room_number, from_date, to_date, reason, parent_contact) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (student_name, student_id, room_number, from_date, to_date, reason, parent_contact)
    )
    db.commit()
    cursor.close()

    return redirect("/student")

# ---------------- ADMIN DASHBOARD ----------------
@app.route('/admin')
def admin():
    cursor = db.cursor()
    cursor.execute("SELECT * FROM complaints ORDER BY id DESC")
    all_complaints = cursor.fetchall()
    latest_complaint = all_complaints[0] if all_complaints else None

    cursor.execute("SELECT * FROM turf_bookings ORDER BY id DESC")
    all_bookings = cursor.fetchall()
    latest_booking = all_bookings[0] if all_bookings else None

    cursor.execute("SELECT * FROM hostel_leaves ORDER BY id DESC")
    all_leave_apps = cursor.fetchall()
    latest_leave = all_leave_apps[0] if all_leave_apps else None

    cursor.execute("SELECT COUNT(*) FROM dinner WHERE status='Available'")
    dinner_count = cursor.fetchone()[0]

    total_students = 300
    available_students = max(0, total_students - len(all_leave_apps))

    cursor.execute("SELECT message FROM alerts ORDER BY id DESC")
    alerts = cursor.fetchall()

    cursor.execute(
        "SELECT breakfast, lunch, dinner, menu_date, updated_at FROM canteen_menu WHERE menu_date = CURDATE() ORDER BY id DESC LIMIT 1"
    )
    today_menu = cursor.fetchone()
    
    cursor.close()

    return render_template(
        "admin_dashboard.html",
        latest_complaint=latest_complaint,
        all_complaints=all_complaints,
        latest_booking=latest_booking,
        all_bookings=all_bookings,
        latest_leave=latest_leave,
        all_leave_apps=all_leave_apps,
        dinner_count=dinner_count,
        available_students=available_students,
        alerts=alerts,
        today_menu=today_menu
    )

# ---------------- SOLVE COMPLAINT ----------------
@app.route('/solve/<int:id>')
def solve(id):
    cursor = db.cursor()
    cursor.execute("UPDATE complaints SET status='Solved' WHERE id=%s", (id,))
    db.commit()
    cursor.close()
    return redirect("/admin")

# ---------------- UPDATE CANTEEN MENU ----------------
@app.route('/update_canteen_menu', methods=['POST'])
def update_canteen_menu():
    breakfast = request.form.get('breakfast', '').strip()
    lunch = request.form.get('lunch', '').strip()
    dinner = request.form.get('dinner', '').strip()
    menu_date = request.form.get('menu_date', '').strip() or date.today().isoformat()

    cursor = db.cursor()
    cursor.execute(
        "SELECT id FROM canteen_menu WHERE menu_date = %s",
        (menu_date,)
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            "UPDATE canteen_menu SET breakfast=%s, lunch=%s, dinner=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            (breakfast, lunch, dinner, existing[0])
        )
    else:
        cursor.execute(
            "INSERT INTO canteen_menu (menu_date, breakfast, lunch, dinner) VALUES (%s, %s, %s, %s)",
            (menu_date, breakfast, lunch, dinner)
        )
    db.commit()
    cursor.close()

    return redirect('/admin')

# ---------------- DIRECTOR DASHBOARD ----------------
@app.route('/director')
def director():
    return render_template("director_dashboard.html")

# ---------------- TURF PAGE ----------------
@app.route('/turf')
def turf():
    return render_template("turf_booking.html")

# ---------------- BOOK TURF ----------------
@app.route('/book_turf', methods=['POST'])
def book_turf():
    student_id = request.form['student_id']
    group_name = request.form['group_name']
    slot_time = request.form['slot_time']
    booking_date = request.form['booking_date']
    payment_method = request.form.get('payment_method')
    utr_number = request.form.get('utr_number', '').strip()
    amount = 280

    if not student_id.isdigit() or len(student_id) != 10:
        return "Student mobile number must be exactly 10 digits.", 400

    if not payment_method:
        return "Payment method is required.", 400

    if not utr_number:
        return "UTR number is required after payment is completed.", 400

    if not utr_number.isdigit() or len(utr_number) != 12:
        return "UTR number must be exactly 12 digits.", 400

    if payment_method not in ['PhonePe', 'GPay']:
        return "Invalid payment method.", 400

    booking_status = 'Completed'
    payment_status = 'Completed'

    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO turf_bookings (student_id, group_name, slot_time, booking_date, amount, payment_method, utr_number, payment_status, booking_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (student_id, group_name, slot_time, booking_date, amount, payment_method, utr_number, payment_status, booking_status)
    )
    booking_id = cursor.lastrowid
    db.commit()
    cursor.close()

    return redirect(f"/turf_receipt/{booking_id}")

# ---------------- TURF RECEIPT ----------------
@app.route('/turf_receipt/<int:booking_id>')
def turf_receipt(booking_id):
    cursor = db.cursor()
    cursor.execute(
        "SELECT id, student_id, group_name, slot_time, booking_date, amount, payment_method, utr_number, payment_status, booking_status, created_at FROM turf_bookings WHERE id=%s",
        (booking_id,)
    )
    booking = cursor.fetchone()
    cursor.close()
    if not booking:
        return "Booking receipt not found.", 404

    return render_template('turf_receipt.html', booking=booking)

# ---------------- DINNER PAGE ----------------
@app.route('/dinner')
def dinner():
    return render_template("dinner.html")

# ---------------- SUBMIT DINNER ----------------
@app.route('/submit_dinner', methods=['POST'])
def submit_dinner():
    student_id = request.form['student_id']
    status = request.form['status']
    date = request.form['date']

    cursor = db.cursor()
    cursor.execute("INSERT INTO dinner (student_id, status, date) VALUES (%s,%s,%s)", (student_id, status, date))
    db.commit()
    cursor.close()

    return redirect("/student")

# ---------------- SEND ALERT ----------------
@app.route('/send_alert', methods=['POST'])
def send_alert():
    message = request.form['message']
    cursor = db.cursor()
    cursor.execute("INSERT INTO alerts (message) VALUES (%s)", (message,))
    db.commit()
    cursor.close()
    return redirect('/admin')

# Attendance and face-recognition routes removed to simplify the project

# ---------------- RUN SERVER ----------------
if __name__ == "__main__":
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=debug_mode)