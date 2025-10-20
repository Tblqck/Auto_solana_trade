# run_watcher_test.py
from watcher import watcher

if __name__ == "__main__":
    controller_file = "controller.csv"   # 👈 make sure this file exists
    watcher(controller_file, interval=5) # run with 5s interval
