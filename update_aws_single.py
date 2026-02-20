# aws_to_local_db_sync.py
#--just pulling aws db into local for test 
import os
import sys
import datetime
import paramiko

# =============================
# CONFIG
# =============================
AWS_HOST = "3.26.3.145"
AWS_USER = "ec2-user"
KEY_PATH = r"C:\Users\dark side\OneDrive\Documents\sol-trade\keys\instance_bd.pem"

REMOTE_DB_PATH = "/home/ec2-user/db_files/dex_pipeline.db"
LOCAL_DB_PATH = "db_files/dex_pipeline.db"

# =============================
# LOGGER
# =============================
class Logger:
    def __init__(self, logfile):
        self.console = sys.stdout
        self.file = open(logfile, "a", encoding="utf-8")

    def write(self, message):
        self.console.write(message)
        self.file.write(message)

    def flush(self):
        self.console.flush()
        self.file.flush()

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = f"aws_to_local_sync_{timestamp}.log"
sys.stdout = sys.stderr = Logger(log_file)

print(f"\n=== 🔄 AWS → LOCAL DB SYNC STARTED ({datetime.datetime.now()}) ===\n")

# =============================
# SYNC FUNCTION
# =============================
def sync_aws_db_to_local():
    print("🔐 Connecting to AWS EC2...")

    os.makedirs("db_files", exist_ok=True)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=AWS_HOST,
        username=AWS_USER,
        key_filename=KEY_PATH,
        timeout=10
    )

    print("📦 Downloading dex_pipeline.db from AWS...")

    sftp = ssh.open_sftp()

    # Backup local DB if it exists
    if os.path.exists(LOCAL_DB_PATH):
        backup_name = f"db_files/dex_pipeline_backup_{timestamp}.db"
        os.rename(LOCAL_DB_PATH, backup_name)
        print(f"🧾 Local DB backed up as {backup_name}")

    sftp.get(REMOTE_DB_PATH, LOCAL_DB_PATH)

    sftp.close()
    ssh.close()

    print("✅ AWS DB successfully synced to local.")

# =============================
# ENTRY POINT
# =============================
if __name__ == "__main__":
    try:
        sync_aws_db_to_local()
        print("\n🎉 SYNC COMPLETED SUCCESSFULLY")
    except Exception as e:
        print(f"\n❌ SYNC FAILED: {e}")

    print(f"\n=== 🏁 FINISHED ({datetime.datetime.now()}) ===")
    sys.stdout.file.close()
