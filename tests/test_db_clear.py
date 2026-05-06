from core.db_utils import get_db_connection

def clear_trade_tables():
    """Remove all data from pending_trades and live_trades tables."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM pending_trades")
        cur.execute("DELETE FROM live_trades")
        conn.commit()
        print("✅ All data cleared from pending_trades and live_trades.")
    except Exception as e:
        print(f"⚠️ Failed to clear tables: {e}")
    finally:
        conn.close()

# Run the function directly
if __name__ == "__main__":
    clear_trade_tables()
