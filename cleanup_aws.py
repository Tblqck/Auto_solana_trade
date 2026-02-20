from data_loops.bridge_aws import RemoteSQLiteBridge

# Tables to clean
TABLES_TO_CLEAN = ["tokens", "supported_tokens", "ohlc_data"]

def cleanup_aws_db(batch_size=500):
    """
    Deletes rows in AWS DB tables that do NOT have a matching contract/pair_id in ai_thought.
    Preserves only rows that exist in ai_thought.
    """
    bridge = RemoteSQLiteBridge()
    bridge.connect()

    # 1️⃣ Fetch all pair_ids from ai_thought
    df_ai = bridge.select(
        "ai_thought",
        columns=["pair_id"],
        limit=1_000_000
    )

    if df_ai is None or df_ai.empty:
        print("⚠️ ai_thought table is empty or unreadable. No cleanup performed.")
        bridge.close()
        return

    preserve_ids = (
        df_ai["pair_id"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    print(f"🧩 Preserving {len(preserve_ids)} pair_ids from ai_thought")

    # 2️⃣ Clean dependent tables
    for table in TABLES_TO_CLEAN:
        if table == "ohlc_data":
            column = "pair_id"
        else:
            column = "Contract"

        print(f"\n🧹 Cleaning table: {table}")
        # ✅ positional args only
        bridge.batch_delete_not_in(table, column, preserve_ids, batch_size)

    bridge.close()
    print("\n✅ AWS DB cleanup complete!")

# ---------------- RUN AS SCRIPT ----------------
if __name__ == "__main__":
    cleanup_aws_db()
