# utils_controller.py
from core.db_utils import get_db_connection


def get_controller_status(module_name: str = "WATCHER") -> str:
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name=?", (module_name,))
    row = cur.fetchone()
    conn.close()
    return row[0].strip().upper() if row else "OFF"


def set_controller_status(value: str, module_name: str = "WATCHER"):
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO module_control (module_name, status) VALUES (?, ?)
        ON CONFLICT(module_name) DO UPDATE SET status=excluded.status
    """, (module_name, value.upper()))
    conn.commit()
    conn.close()
