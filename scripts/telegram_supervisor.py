# scripts/telegram_supervisor.py
"""
Always-on Telegram control panel for sol_trade. Runs independently of
main.py so /startengine, /state, /liquidate etc. all work even when the
trading engine itself is fully stopped -- main.py has no listener of its
own anymore (see notify/commands.py header).

Run this once, in its own persistent session (tmux/screen/systemd), and
leave it running indefinitely:

    python -m scripts.telegram_supervisor

It does not launch main.py on its own startup -- use /startengine for
that once you're ready.
"""
import time

from notify.commands import start_command_listener


if __name__ == "__main__":
    print("[Supervisor] Starting Telegram control panel...")
    start_command_listener()
    print("[Supervisor] Listening. Ctrl-C to stop (this does NOT stop the "
          "trading engine if it's running separately -- use /shutdown for that).")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[Supervisor] Stopped.")
