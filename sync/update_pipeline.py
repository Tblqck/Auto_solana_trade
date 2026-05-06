# update_pipeline.py

from get_pairs import run_all as get_pairs_run
from sync_from_aws import sync_all_tables
from cleanup_aws import cleanup_aws_db
from cleanup_stale_ai_thought import cleanup_stale_ai_thought
from sync_local_to_aws import sync_all as sync_local_to_aws_run

def run_update_pipeline():
    try:
        print("🚀 Starting full update pipeline...\n")

        # -------------------------
        # Step 1: Scrape Dex and update DB
        # -------------------------
        print("🔹 Step 1: Running Dex scraper (get_pairs)...")
        get_pairs_run()
        print("✅ Step 1 complete.\n")

        # -------------------------
        # Step 2: Sync AWS tables to local DB
        # -------------------------
        print("🔹 Step 2: Syncing tables from AWS...")
        sync_all_tables()
        print("✅ Step 2 complete.\n")

        # -------------------------
        # Step 3: Cleanup AWS DB
        # -------------------------
        print("🔹 Step 3: Cleaning up AWS DB...")
        cleanup_aws_db()
        print("✅ Step 3 complete.\n")

        # -------------------------
        # Step 4: Cleanup stale AI thoughts
        # -------------------------
        print("🔹 Step 4: Cleaning up stale AI thoughts...")
        cleanup_stale_ai_thought()
        print("✅ Step 4 complete.\n")

        # -------------------------
        # Step 5: Sync local DB back to AWS
        # -------------------------
        print("🔹 Step 5: Syncing local DB -> AWS...")
        sync_local_to_aws_run()
        print("✅ Step 5 complete.\n")

        print("🎉 Update pipeline finished successfully!")

    except Exception as e:
        print(f"❌ Pipeline stopped due to an error: {e}")

# If run directly
if __name__ == "__main__":
    run_update_pipeline()
