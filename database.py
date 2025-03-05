# database.py
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "db", "saves.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            user_id INTEGER,
            slot INTEGER,
            threshold REAL DEFAULT 0,
            notif_type TEXT DEFAULT 'none',
            PRIMARY KEY (user_id, slot)
        )
    """)
    conn.commit()

init_db()