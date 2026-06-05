import sqlite3
from datetime import datetime

DATABASE = "dashboard.db"

def get_db():   # open a new database connection
    conn =  sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row   # so we can access columns by name
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    conn.close()
    print("Database initialized.")

def save_scan(app_name, repo, push_time, risk_level, files_scanned, report):
    conn = get_db()
    conn.execute("""
        INSERT INTO scans (app_name, repo, push_time, scan_time, risk_level, files_scanned, report)
        VALUES (?,?, ?, ?, ?, ?, ?)
    """, (
        app_name, repo, push_time, datetime.strftime("%Y-%m-%d %H:%M:%S"), risk_level, files_scanned, report
    ))
    conn.commit()
    conn.close()

def get_scans():
    # return all scans
    conn = get_db()
    scans = conn.execute("""
        SELECT * FROM scans ORDER BY scan_time DESC    
        """).fetchall()
    conn.close()
    return [dict(s) for s in scans]

def get_last_scan():
    # return the most recent scan
    conn = get_db()
    # group by app and get the max id in each group to get latest scan
    scans = conn.execute("""
        SELECT * FROM scans
        WHERE id IN (SELECT MAX(id) FROM scans GROUP BY app_name)
        ORDER BY scan_time DESC
    """).fetchall()
    conn.close()
    return [dict(s) for s in scans]

if __name__ == "__main__":
    init_db()