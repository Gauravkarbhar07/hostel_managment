import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '12345678')
DB_NAME = os.getenv('DB_NAME', 'hostel_management')

if not DB_NAME:
    print('DB_NAME not set in environment; aborting')
    exit(1)

try:
    db = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME)
    cursor = db.cursor()
    tables = ['attendance', 'student_profiles']
    for t in tables:
        cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (DB_NAME, t))
        if cursor.fetchone()[0] > 0:
            cursor.execute(f"DROP TABLE `{t}`")
            print(f"Dropped table: {t}")
        else:
            print(f"Table not found, skipping: {t}")
    db.commit()
    cursor.close()
    db.close()
except Exception as e:
    print('Error:', e)
    exit(2)
