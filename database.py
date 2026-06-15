import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone

DATABASE_URL = os.environ.get("DATABASE_URL")

IST = timezone(timedelta(hours=5, minutes=30))

def get_db():   # open a new database connection
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id SERIAL PRIMARY KEY,
            app_name TEXT NOT NULL,
            repo TEXT NOT NULL,
            push_time TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            files_scanned TEXT,
            report TEXT NOT NULL
            )
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Database initialized.")

def save_scan(app_name, repo, push_time, risk_level, files_scanned, report):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO scans (app_name, repo, push_time, scan_time, risk_level, files_scanned, report)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        app_name, repo, push_time, datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), risk_level, files_scanned, report
    ))
    conn.commit()
    cur.close()
    conn.close()

def get_scans():
    # return all scans
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM scans ORDER BY scan_time DESC")
    scans = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(s) for s in scans]

def get_last_scan():
    # return the most recent scan
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # group by app and get the max id in each group to get latest scan
    cur.execute("""
        SELECT * FROM scans
        WHERE id IN (SELECT MAX(id) FROM scans GROUP BY app_name)
        ORDER BY scan_time DESC
    """)
    scans = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(s) for s in scans]

if __name__ == "__main__":
    init_db()