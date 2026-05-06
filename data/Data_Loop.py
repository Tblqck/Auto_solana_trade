import sys
import os
import threading
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data.Data_Loop_core import run_data_loop, LOOP_INTERVAL


class DataLoopAgent:
    def __init__(self, interval_seconds=LOOP_INTERVAL):
        self.interval_seconds = interval_seconds
        self.thread = None
        self.running = False
        self.lock = threading.Lock()

    def _loop(self):
        print(f"[DataLoop] Agent started. Interval: {self.interval_seconds}s")
        while self.running:
            try:
                run_data_loop()
            except Exception as e:
                print(f"[DataLoop] Error: {e}")
            if self.running:
                print(f"[DataLoop] Sleeping {self.interval_seconds}s before next run...")
                time.sleep(self.interval_seconds)
        print("[DataLoop] Agent stopped.")

    def start(self):
        with self.lock:
            if self.running:
                print("[DataLoop] Already running.")
                return
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            if not self.running:
                print("[DataLoop] Already stopped.")
                return
            self.running = False
            if self.thread:
                self.thread.join(timeout=30)

    def status(self):
        return {"running": self.running, "interval_seconds": self.interval_seconds}


if __name__ == "__main__":
    agent = DataLoopAgent()
    agent.start()

    while True:
        cmd = input("Command (status/stop): ").strip().lower()
        if cmd == "status":
            print(agent.status())
        elif cmd == "stop":
            agent.stop()
            break
