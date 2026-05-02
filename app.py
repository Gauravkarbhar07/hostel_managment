from flask import Flask, render_template, request, redirect, jsonify, session
import mysql.connector
from werkzeug.utils import secure_filename
import os
from datetime import date, datetime
import cv2
import face_recognition
import numpy as np
import pandas as pd
import base64
import json
from io import BytesIO
from PIL import Image
import math

# Hostel location (you can change these coordinates to your actual hostel location)
HOSTEL_LAT = 20.0367
HOSTEL_LNG = 73.7847
HOSTEL_RADIUS_METERS = 500  # 500 meters radius around hostel

def is_within_hostel_area(lat, lng):
    """Check if the given coordinates are within the hostel area"""
    if not lat or not lng:
        return False

    # Calculate distance using Haversine formula
    lat1, lon1 = math.radians(HOSTEL_LAT), math.radians(HOSTEL_LNG)
    lat2, lon2 = math.radians(float(lat)), math.radians(float(lng))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    distance = 6371000 * c  # Earth radius in meters
    return distance <= HOSTEL_RADIUS_METERS

from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------- CONFIG ----------------
UPLOAD_FOLDER = 'static/complaint_photos'
FACE_FOLDER = 'static/faces'
EXCEL_FOLDER = 'static/excel'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['FACE_FOLDER'] = FACE_FOLDER
app.config['EXCEL_FOLDER'] = EXCEL_FOLDER
app.config['SECRET_KEY'] = 'your-secret-key-here'

# Create directories if they don't exist
for folder in [UPLOAD_FOLDER, FACE_FOLDER, EXCEL_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# MySQL Connection
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="12345678",
    database="hostel_management"
)

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
    CREATE TABLE IF NOT EXISTS student_profiles (
        id INT AUTO_INCREMENT PRIMARY KEY,
        student_id VARCHAR(50),
        full_name VARCHAR(255),
        college VARCHAR(100),
        year VARCHAR(50),
        face_encoding TEXT,
        face_image_path VARCHAR(255),
        location_lat DECIMAL(10, 8),
        location_lng DECIMAL(11, 8),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INT AUTO_INCREMENT PRIMARY KEY,
        student_id VARCHAR(50),
        attendance_date DATE,
        check_in_time TIME,
        check_out_time TIME,
        status VARCHAR(20) DEFAULT 'Present',
        location_lat DECIMAL(10, 8),
        location_lng DECIMAL(11, 8),
        face_verified BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
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

# ---------------- ATTENDANCE SYSTEM ----------------

# Profile Management Routes
@app.route('/profile')
def profile():
    # Check if profile already exists (simplified - in real app, get student_id from session)
    cursor = db.cursor()
    cursor.execute("SELECT face_encoding FROM student_profiles WHERE student_id='test_student'")  # Replace with actual student_id from session
    existing_profile = cursor.fetchone()
    cursor.close()

    profile_registered = existing_profile is not None and existing_profile[0] is not None
    return render_template('profile.html', profile_registered=profile_registered)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    student_id = request.form['student_id']
    full_name = request.form['full_name']
    college = request.form['college']
    year = request.form['year']
    face_image = request.files.get('face_image')
    location_lat = request.form.get('location_lat')
    location_lng = request.form.get('location_lng')

    face_encoding = None
    face_image_path = None

    if face_image:
        # Save face image
        filename = secure_filename(f"{student_id}_face.jpg")
        face_path = os.path.join(app.config['FACE_FOLDER'], filename)
        face_image.save(face_path)
        face_image_path = filename

        # Generate face encoding
        image = face_recognition.load_image_file(face_path)
        encodings = face_recognition.face_encodings(image)
        if encodings:
            face_encoding = json.dumps(encodings[0].tolist())

    cursor = db.cursor()

    # Check if profile exists
    cursor.execute("SELECT id, face_encoding FROM student_profiles WHERE student_id=%s", (student_id,))
    existing = cursor.fetchone()

    if existing:
        # Check if face is already registered - if so, prevent updates
        if existing[1] is not None:  # face_encoding exists
            cursor.close()
            return redirect('/profile?message=Profile+already+registered.+Face+cannot+be+updated+for+security+reasons.')

        # Allow updating profile without face if face not registered yet
        cursor.execute("""
            UPDATE student_profiles
            SET full_name=%s, college=%s, year=%s, face_encoding=%s, face_image_path=%s,
                location_lat=%s, location_lng=%s, updated_at=CURRENT_TIMESTAMP
            WHERE student_id=%s
        """, (full_name, college, year, face_encoding, face_image_path, location_lat, location_lng, student_id))
    else:
        # Create new profile
        cursor.execute("""
            INSERT INTO student_profiles (student_id, full_name, college, year, face_encoding, face_image_path, location_lat, location_lng)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (student_id, full_name, college, year, face_encoding, face_image_path, location_lat, location_lng))

    db.commit()
    cursor.close()
    return redirect('/profile?message=Profile+updated+successfully')

# Attendance Routes
@app.route('/attendance')
def attendance():
    return render_template('attendance.html')

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    data = request.get_json()
    face_image_data = data.get('face_image')
    location_lat = data.get('location_lat')
    location_lng = data.get('location_lng')

    if not face_image_data:
        return jsonify({'success': False, 'message': 'No face image provided'})

    # Decode base64 image
    try:
        image_data = base64.b64decode(face_image_data.split(',')[1])
        image = Image.open(BytesIO(image_data))
        image_np = np.array(image)

        # Find faces in the image
        face_locations = face_recognition.face_locations(image_np)
        face_encodings = face_recognition.face_encodings(image_np, face_locations)

        if not face_encodings:
            return jsonify({'success': False, 'message': 'No face detected in image'})

        if len(face_encodings) > 1:
            return jsonify({'success': False, 'message': 'Please show only one face at a time'})

        face_encoding = face_encodings[0]

        # Get all known face encodings from database
        cursor = db.cursor()
        cursor.execute("SELECT student_id, face_encoding FROM student_profiles WHERE face_encoding IS NOT NULL")
        known_faces = cursor.fetchall()

        recognized_student = None
        best_distance = None
        threshold = 0.25  # Much stricter threshold for high accuracy

        encodings = []
        student_ids = []
        for student_id, encoding_json in known_faces:
            known_encoding = np.array(json.loads(encoding_json))
            encodings.append(known_encoding)
            student_ids.append(student_id)

        if encodings:
            distances = face_recognition.face_distance(encodings, face_encoding)
            best_idx = int(np.argmin(distances))
            best_distance = float(distances[best_idx])

            # Check if the best match is significantly better than others
            sorted_distances = np.sort(distances)
            if len(sorted_distances) > 1:
                ratio = sorted_distances[1] / sorted_distances[0] if sorted_distances[0] > 0 else float('inf')
                if best_distance <= threshold and ratio > 1.5:  # Best match is 50% better than second best
                    recognized_student = student_ids[best_idx]
            elif best_distance <= threshold:
                recognized_student = student_ids[best_idx]

        if not recognized_student:
            return jsonify({'success': False, 'message': 'Face not recognized or does not match registered student. Please register your face again.'})

        # Check if student is within hostel area
        if not is_within_hostel_area(location_lat, location_lng):
            return jsonify({'success': False, 'message': 'Attendance can only be marked from within the hostel premises.'})

        # Check if already marked attendance today
        today = date.today()
        cursor.execute("""
            SELECT id FROM attendance
            WHERE student_id=%s AND attendance_date=%s
        """, (recognized_student, today))

        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Attendance already marked for today'})

        # Mark attendance
        cursor.execute("""
            INSERT INTO attendance (student_id, attendance_date, check_in_time, status, location_lat, location_lng, face_verified)
            VALUES (%s, %s, %s, 'Present', %s, %s, TRUE)
        """, (recognized_student, today, datetime.now().time(), location_lat, location_lng))

        db.commit()
        cursor.close()

        return jsonify({'success': True, 'message': f'Attendance marked for student {recognized_student}'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error processing image: {str(e)}'})

@app.route('/get_attendance_report')
def get_attendance_report():
    student_id = request.args.get('student_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    cursor = db.cursor()
    query = """
        SELECT attendance_date, check_in_time, check_out_time, status, location_lat, location_lng, face_verified
        FROM attendance
        WHERE 1=1
    """
    params = []

    if student_id:
        query += " AND student_id=%s"
        params.append(student_id)

    if start_date:
        query += " AND attendance_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND attendance_date <= %s"
        params.append(end_date)

    query += " ORDER BY attendance_date DESC"

    cursor.execute(query, params)
    records = cursor.fetchall()
    cursor.close()

    formatted_records = []
    for row in records:
        formatted_records.append([
            row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0]),
            str(row[1]) if row[1] is not None else None,
            str(row[2]) if row[2] is not None else None,
            row[3],
            float(row[4]) if row[4] is not None else None,
            float(row[5]) if row[5] is not None else None,
            bool(row[6])
        ])

    return jsonify({'records': formatted_records})

@app.route('/get_attendance_records')
def get_attendance_records():
    """Get ALL attendance records for admin dashboard"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    cursor = db.cursor()
    query = """
        SELECT a.student_id, sp.full_name, sp.college, sp.year, a.attendance_date,
               a.check_in_time, a.check_out_time, a.status, a.face_verified
        FROM attendance a
        LEFT JOIN student_profiles sp ON a.student_id = sp.student_id
        WHERE 1=1
    """
    params = []

    if start_date:
        query += " AND a.attendance_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND a.attendance_date <= %s"
        params.append(end_date)

    query += " ORDER BY a.attendance_date DESC, a.student_id"

    cursor.execute(query, params)
    records = cursor.fetchall()
    cursor.close()

    formatted_records = []
    for row in records:
        formatted_records.append([
            row[0],  # student_id
            row[1],  # full_name
            row[2],  # college
            row[3],  # year
            row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]),  # attendance_date
            row[5],  # check_in_time
            row[6],  # check_out_time
            row[7],  # status
            row[8]   # face_verified
        ])

    return jsonify({'records': formatted_records})

@app.route('/export_attendance_excel')
def export_attendance_excel():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    cursor = db.cursor()
    query = """
        SELECT a.student_id, sp.full_name, sp.college, sp.year, a.attendance_date,
               a.check_in_time, a.check_out_time, a.status, a.face_verified
        FROM attendance a
        LEFT JOIN student_profiles sp ON a.student_id = sp.student_id
        WHERE 1=1
    """
    params = []

    if start_date:
        query += " AND a.attendance_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND a.attendance_date <= %s"
        params.append(end_date)

    query += " ORDER BY a.attendance_date DESC, a.student_id"

    cursor.execute(query, params)
    records = cursor.fetchall()
    cursor.close()

    # Create DataFrame
    df = pd.DataFrame(records, columns=[
        'Student ID', 'Full Name', 'College', 'Year', 'Date',
        'Check In Time', 'Check Out Time', 'Status', 'Face Verified'
    ])

    # Save to Excel
    filename = f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = os.path.join(app.config['EXCEL_FOLDER'], filename)
    df.to_excel(filepath, index=False)

    return jsonify({'success': True, 'filename': filename})

# ---------------- RUN SERVER ----------------
if __name__ == "__main__":
    app.run(debug=True)