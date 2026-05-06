# update_aws_.py

import sys
import datetime
from get_pairs import run_all as get_pairs_run
from sync_from_aws import sync_all_tables
from cleanup_aws import cleanup_aws_db
from cleanup_stale_ai_thought import cleanup_stale_ai_thought
from sync_local_to_aws import sync_all as sync_local_to_aws_run

# -------------------------
# Logger class to print to console + file with UTF-8
# -------------------------
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

# -------------------------
# Setup logging
# -------------------------
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = f"update_pipeline_{timestamp}.log"
sys.stdout = sys.stderr = Logger(log_file)

print(f"\n=== Pipeline started at {datetime.datetime.now()} ===\n")

# -------------------------
# Update pipeline function
# -------------------------
def run_update_pipeline():
    try:
        print("🚀 Starting full update pipeline...\n")

        # Step 1: Scrape Dex and update DB
        print("🔹 Step 1: Running Dex scraper (get_pairs)...")
        #get_pairs_run()
        print("✅ Step 1 complete.\n")

        # Step 2: Sync AWS tables to local DB
        print("🔹 Step 2: Syncing tables from AWS...")
        #sync_all_tables()
        print("✅ Step 2 complete.\n")

        # Step 3: Cleanup AWS DB
        print("🔹 Step 3: Cleaning up AWS DB...")
        #cleanup_aws_db()
        print("✅ Step 3 complete.\n")

        # Step 4: Cleanup stale AI thoughts
        print("🔹 Step 4: Cleaning up stale AI thoughts...")
        #cleanup_stale_ai_thought()
        print("✅ Step 4 complete.\n")

        # Step 5: Sync local DB back to AWS
        print("🔹 Step 5: Syncing local DB -> AWS...")
        #sync_local_to_aws_run()
        print("✅ Step 5 complete.\n")

        print("🎉 Update pipeline finished successfully!")

    except Exception as e:
        print(f"❌ Pipeline stopped due to an error: {e}")

# -------------------------
# Run pipeline directly
# -------------------------
if __name__ == "__main__":
    run_update_pipeline()
    print(f"\n=== Pipeline finished at {datetime.datetime.now()} ===")
    sys.stdout.log.close()  # Close the log file safely
