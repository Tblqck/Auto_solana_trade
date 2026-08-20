# sync/archive_ohlc.py
"""
Moves old OHLC rows off the live EC2 instance so the SQLite DB there doesn't
grow unbounded. Exports rows older than --days to a local CSV (still usable
for retraining via train_models.py --csv), verifies the download landed
intact, and only then deletes those rows from the remote DB.

Run manually / on-demand from your local machine (not wired into the live
24/7 engine -- disk maintenance shouldn't touch the trading process):

  python sync/archive_ohlc.py                # archive rows older than 30 days
  python sync/archive_ohlc.py --days 60
  python sync/archive_ohlc.py --dry-run       # export + verify only, no delete

Does NOT run VACUUM. Deleting rows frees logical space but the SQLite file
won't shrink on disk until VACUUM runs, and VACUUM needs an exclusive lock
on a DB the live engine is reading/writing every few seconds -- run that
separately, manually, during a quiet moment (see bottom of --help output).
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import paramiko

RETENTION_DAYS_DEFAULT = 30
REMOTE_HOST = "54.206.109.26"
REMOTE_USER = "ec2-user"
REMOTE_PROJECT_DIR = "/home/ec2-user/Auto_solana_trade"
REMOTE_TMP_DIR = f"{REMOTE_PROJECT_DIR}/tmp_archive"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ARCHIVE_DIR = PROJECT_ROOT / "db_files" / "archive"


def _find_key(key_name="sol_trade.pem") -> Path:
    for base in [PROJECT_ROOT, PROJECT_ROOT.parent / "sol_trade"]:
        p = base / "keys" / key_name
        if p.exists():
            return p
    raise FileNotFoundError(f"SSH key '{key_name}' not found in keys/ folder")


def _connect() -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=REMOTE_HOST, username=REMOTE_USER, key_filename=str(_find_key()))
    return ssh


def _run(ssh: paramiko.SSHClient, command: str) -> tuple[str, str]:
    _, stdout, stderr = ssh.exec_command(command)
    return stdout.read().decode(), stderr.read().decode()


def archive_old_ohlc(days: int = RETENTION_DAYS_DEFAULT, dry_run: bool = False) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    remote_csv = f"{REMOTE_TMP_DIR}/ohlc_archive_{ts_tag}.csv"

    ssh = _connect()
    try:
        print(f"[Archive] Exporting ohlc_data rows older than {cutoff} ...")
        _run(ssh, f"mkdir -p {REMOTE_TMP_DIR}")

        out, err = _run(
            ssh,
            f"cd {REMOTE_PROJECT_DIR} && python -m sync.archive_ohlc_remote "
            f"--mode export --cutoff '{cutoff}' --out '{remote_csv}'",
        )
        if err.strip():
            raise RuntimeError(f"Remote export failed: {err.strip()}")
        row_count = int(out.strip().splitlines()[-1])
        print(f"[Archive] {row_count} rows exported remotely")

        if row_count == 0:
            print("[Archive] Nothing to archive.")
            _run(ssh, f"rm -f {remote_csv}")
            return {"archived": 0}

        LOCAL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        local_csv = LOCAL_ARCHIVE_DIR / f"ohlc_archive_{ts_tag}.csv"
        sftp = ssh.open_sftp()
        sftp.get(remote_csv, str(local_csv))
        sftp.close()

        with open(local_csv, encoding="utf-8") as f:
            local_lines = sum(1 for _ in f) - 1  # minus header
        if local_lines != row_count:
            raise RuntimeError(
                f"Download mismatch: remote exported {row_count} rows, "
                f"local file has {local_lines}. Aborting delete for safety."
            )
        print(f"[Archive] Downloaded to {local_csv} ({local_lines} rows confirmed)")

        if dry_run:
            print("[Archive] Dry run — remote rows NOT deleted.")
            return {"archived": row_count, "deleted": False, "local_file": str(local_csv)}

        out, err = _run(
            ssh,
            f"cd {REMOTE_PROJECT_DIR} && python -m sync.archive_ohlc_remote "
            f"--mode delete --cutoff '{cutoff}'",
        )
        if err.strip():
            raise RuntimeError(f"Remote delete failed: {err.strip()}")
        deleted = int(out.strip().splitlines()[-1])
        print(f"[Archive] Deleted {deleted} rows from the live remote DB")

        _run(ssh, f"rm -f {remote_csv}")

        return {"archived": row_count, "deleted": True, "local_file": str(local_csv)}
    finally:
        ssh.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=RETENTION_DAYS_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = archive_old_ohlc(days=args.days, dry_run=args.dry_run)
    print(result)

    if result.get("deleted"):
        print(
            "\n[Archive] Rows are deleted but the SQLite file on the server hasn't "
            "shrunk yet — run VACUUM manually during a quiet moment to reclaim disk:\n"
            "  ssh -i keys/sol_trade.pem ec2-user@54.206.109.26 \\\n"
            "    \"cd Auto_solana_trade && sqlite3 db_files/dex_pipeline.db 'VACUUM;'\"\n"
            "(VACUUM needs an exclusive lock — expect it to briefly block the live engine.)"
        )
