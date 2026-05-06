from core.db_utils import get_db_connection2


def analyze_ohlc():
    conn = get_db_connection2()
    cur = conn.cursor()

    # Total rows
    cur.execute("SELECT COUNT(*) FROM ohlc_data")
    total_rows = cur.fetchone()[0]

    # Unique pairs
    cur.execute("SELECT COUNT(DISTINCT pair_id) FROM ohlc_data")
    total_pairs = cur.fetchone()[0]

    # Rows per pair + time range
    cur.execute("""
        SELECT 
            pair_id,
            COUNT(*) as total_rows,
            MIN(time) as first_time,
            MAX(time) as last_time
        FROM ohlc_data
        GROUP BY pair_id
        ORDER BY total_rows DESC
    """)

    rows = cur.fetchall()
    conn.close()

    return total_rows, total_pairs, rows


def print_analysis(total_rows, total_pairs, rows):
    print("\n📊 OHLC DATA ANALYSIS")
    print("=" * 60)

    print(f"Total Rows      : {total_rows}")
    print(f"Unique Pair IDs : {total_pairs}")

    print("\nPer Pair Breakdown:\n")

    header = f"{'pair_id':<20} {'rows':>10} {'first_time':<25} {'last_time':<25}"
    print(header)
    print("-" * len(header))

    for pair_id, count, first_time, last_time in rows:
        print(f"{str(pair_id):<20} {count:>10} {str(first_time):<25} {str(last_time):<25}")


if __name__ == "__main__":
    total_rows, total_pairs, rows = analyze_ohlc()
    print_analysis(total_rows, total_pairs, rows)