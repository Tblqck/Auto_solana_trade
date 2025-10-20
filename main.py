# main.py
import os
import time
import pandas as pd
import subprocess
import datetime
import shutil

MASTER_FILE = "master_control.csv"
STATUS_FILE = "dataloop_status.csv"

# Files to back up
CSV_FILES = [
    "ai-thought.csv",
    "all_pairs_ohlc.csv",
    "buybook.csv",
    "fetched_pairs.csv",
    "filtered_contracts.csv",
    "pending.csv",
    "transactionbook.csv",
]

# Files to reset (instead of backup full)
RESET_FILES = {
    "controller.csv": ["status", "status2"]
}


def archive_csvs():
    """Archive CSVs into ./archive/<timestamp>/ before starting system."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = os.path.join("archive", ts)
    os.makedirs(archive_dir, exist_ok=True)

    # Copy & clean normal files
    for fname in CSV_FILES:
        if os.path.exists(fname):
            try:
                df = pd.read_csv(fname)
                # Keep headers only
                header_only = df.head(0)
                # Save backup full copy
                shutil.copy(fname, os.path.join(archive_dir, fname))
                # Truncate file but keep headers
                header_only.to_csv(fname, index=False)
                print(f"📦 Archived + cleaned {fname}")
            except Exception as e:
                print(f"⚠️ Failed to archive {fname}: {e}")

    # Reset special files
    for fname, headers in RESET_FILES.items():
        df_reset = pd.DataFrame([["OFF", "OFF"]], columns=headers)
        if os.path.exists(fname):
            shutil.copy(fname, os.path.join(archive_dir, fname))
        df_reset.to_csv(fname, index=False)
        print(f"🧹 Reset {fname} to OFF,OFF")

    print(f"✅ Archive completed at {archive_dir}")


def reset_master():
    df = pd.DataFrame([{"AI_BOT": "OFF", "WATCHER": "OFF", "DataLoop": "OFF", "Get-pairs": "OFF"}])
    df.to_csv(MASTER_FILE, index=False)
    print("🔄 Master control reset: all OFF.")


def set_master(ai="OFF", watcher="OFF", dataloop="OFF", getpairs="OFF"):
    df = pd.DataFrame([{"AI_BOT": ai, "WATCHER": watcher, "DataLoop": dataloop, "Get-pairs": getpairs}])
    df.to_csv(MASTER_FILE, index=False)
    print(f"✅ Master updated: AI_BOT={ai}, WATCHER={watcher}, DataLoop={dataloop}, Get-pairs={getpairs}")


def wait_for_dataloop_ready(timeout=300):
    """Wait until dataloop_status.csv shows a run."""
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(STATUS_FILE):
            try:
                df = pd.read_csv(STATUS_FILE)
                if "last_run" in df.columns and not df.empty:
                    print("📌 DataLoop ready. Proceeding...")
                    return True
            except Exception:
                pass
        print("⏳ Waiting for DataLoop first run...")
        time.sleep(5)
    return False


if __name__ == "__main__":
    # Step 0: archive before running
    archive_csvs()

    reset_master()

    # Step 1: run get-pairs once
    set_master(getpairs="ON")
    subprocess.run(["python", "get-pairs.py"])
    set_master(getpairs="OFF")

    # Step 2: start DataLoop
    set_master(dataloop="ON")
    dataloop_proc = subprocess.Popen(["python", "DataLoop.py"])

    # Step 3: wait for DataLoop to finish 1st run
    if not wait_for_dataloop_ready():
        print("❌ DataLoop did not complete first run in time.")
        dataloop_proc.terminate()
        exit(1)

    # Step 4: launch AI Bot (with Watcher ON in master only)
    set_master(ai="ON", watcher="ON", dataloop="ON")
    aibot_proc = subprocess.Popen(["python", "aibot.py"])

    # Step 5: let them run for 12 hours
    print("⏳ System running for 12 hours...")
    time.sleep(12 * 3600)

    # Step 6: stop everything
    print("🛑 12 hours reached. Shutting down...")
    set_master(ai="OFF", watcher="OFF", dataloop="OFF", getpairs="OFF")
    aibot_proc.terminate()
    dataloop_proc.terminate()
