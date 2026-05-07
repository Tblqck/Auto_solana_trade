# update_pipeline.py

import sys
from pathlib import Path

_SYNC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SYNC_DIR))

from sync_from_aws import sync_all_tables
from cleanup_aws import cleanup_aws_db
from cleanup_stale_ai_thought import cleanup_stale_ai_thought
from sync_local_to_aws import sync_all as sync_local_to_aws_run


def run_update_pipeline():
    try:
        print("Starting sync pipeline...")

        print("Step 1: Syncing tables from AWS -> local...")
        sync_all_tables()
        print("Step 1 complete.\n")

        print("Step 2: Cleaning up stale AI thoughts on AWS...")
        cleanup_stale_ai_thought()
        print("Step 2 complete.\n")

        print("Step 3: Cleaning up orphaned rows on AWS...")
        cleanup_aws_db()
        print("Step 3 complete.\n")

        print("Step 4: Pushing local DB -> AWS...")
        sync_local_to_aws_run()
        print("Step 4 complete.\n")

        print("Sync pipeline finished successfully!")

    except Exception as e:
        print(f"Pipeline error: {e}")


if __name__ == "__main__":
    run_update_pipeline()