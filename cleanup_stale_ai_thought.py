# cleanup_stale_ai_thought.py
from data_loops.bridge_aws import RemoteSQLiteBridge

TABLES_TO_CLEAN = ["tokens", "supported_tokens", "ohlc_data"]

def cleanup_stale_ai_thought(batch_size=500, delete_ai_thought_rows=True):
    """
    Deletes data for pair_id where:
    - ai_thought.decision = 0
    - ai_thought.time_queued is older than 24 hours
    """

    bridge = RemoteSQLiteBridge()
    bridge.connect()

    # 1️⃣ Find stale pair_ids (CORRECT COLUMN NAME)
    sql = """
        SELECT DISTINCT pair_id
        FROM ai_thought
        WHERE decision = 0
          AND time_queued <= datetime('now', '-24 hours');
    """

    df = bridge._exec_sql(sql)

    if df is None or df.empty:
        print("✅ No stale ai_thought pair_ids found")
        bridge.close()
        return

    stale_pair_ids = (
        df["pair_id"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    print(f"🧹 Found {len(stale_pair_ids)} stale pair_ids (decision=0, >24h)")

    # 2️⃣ Delete from dependent tables
    for table in TABLES_TO_CLEAN:
        column = "pair_id" if table == "ohlc_data" else "Contract"

        print(f"\n🧹 Cleaning table: {table}")
        for i in range(0, len(stale_pair_ids), batch_size):
            batch = stale_pair_ids[i:i + batch_size]
            batch_str = ",".join([f"'{x}'" for x in batch])
            sql = f"DELETE FROM {table} WHERE {column} IN ({batch_str});"
            bridge._exec_sql(sql, fetch=False)

    # 3️⃣ Optionally delete ai_thought rows themselves
    if delete_ai_thought_rows:
        print("\n🧹 Deleting stale rows from ai_thought")
        for i in range(0, len(stale_pair_ids), batch_size):
            batch = stale_pair_ids[i:i + batch_size]
            batch_str = ",".join([f"'{x}'" for x in batch])
            sql = f"""
                DELETE FROM ai_thought
                WHERE pair_id IN ({batch_str})
                  AND decision = 0
                  AND time_queued <= datetime('now', '-24 hours');
            """
            bridge._exec_sql(sql, fetch=False)

    bridge.close()
    print("\n✅ Stale AI-thought cleanup complete!")

# ---------------- RUN AS SCRIPT ----------------
if __name__ == "__main__":
    cleanup_stale_ai_thought()
