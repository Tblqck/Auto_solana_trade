# update_aws_.py — sync pipeline with file logging

import sys
import datetime
from pathlib import Path

_SYNC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SYNC_DIR))

from sync_from_aws import sync_all_tables
from cleanup_aws import cleanup_aws_db
from cleanup_stale_ai_thought import cleanup_stale_ai_thought
from sync_local_to_aws import sync_all as sync_local_to_aws_run


class Logger:
    def __init__(self, logfile):
        self.terminal = sys.stdout
        self.log = open(logfile, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()


timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = f"sync_pipeline_{timestamp}.log"
sys.stdout = sys.stderr = Logger(log_file)

print(f"\n=== Sync pipeline started at {datetime.datetime.now()} ===\n")


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
    print(f"\n=== Sync pipeline finished at {datetime.datetime.now()} ===")
    sys.stdout.log.close()