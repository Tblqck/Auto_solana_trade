import os
import time
import threading
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess

# -------------------------
# LOAD ENV
# -------------------------
load_dotenv()

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not OPENROUTER_KEY:
    raise ValueError("❌ OPENROUTER_API_KEY missing")

print("✅ KEYS LOADED")

# -------------------------
# CONFIG
# -------------------------
PROJECT_DIR = r"C:\Users\dark side\OneDrive\Documents\sol_trade - Copy"

PRIMARY_MODEL = "openrouter/qwen/qwen3-coder-next"
BACKUP_MODEL = "gpt-4o-mini"

STRUCTURE_FILE = os.path.join(PROJECT_DIR, "STRUCTURE.md")

MAX_WORKERS = 6  # 🔥 concurrency level (adjust 4–10)

SKIP_DIRS = {
    "keys", "tmp_sync", ".vscode", ".stfolder",
    ".pytest_cache", "db_files", ".git", "__pycache__"
}

SKIP_FILES = {".env"}

VALID_EXTENSIONS = (".py", ".js", ".ts", ".json")

# -------------------------
# PROMPT
# -------------------------
PROMPT_TEMPLATE = """
You are a code analysis engine.

CRITICAL RULES:
- DO NOT mention other files
- DO NOT explain process
- OUTPUT ONLY markdown block

FILE: {filename}

Return:

## {filename}

Purpose:
-

Key Components:
-

Inputs/Outputs:
-

Dependencies:
-
"""

# -------------------------
# FILE COLLECTION
# -------------------------
def should_skip(path):
    parts = path.split(os.sep)
    return any(p in SKIP_DIRS for p in parts) or os.path.basename(path) in SKIP_FILES


def get_files():
    files = []
    for root, dirs, filenames in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for f in filenames:
            full = os.path.join(root, f)
            if should_skip(full):
                continue
            if f.endswith(VALID_EXTENSIONS):
                files.append(full)

    return sorted(files)

# -------------------------
# MODEL CALL (FAST PATH)
# -------------------------
def call_model(prompt, model, key, is_openai=False):

    env = os.environ.copy()

    if is_openai:
        env["OPENAI_API_KEY"] = key
    else:
        env["OPENROUTER_API_KEY"] = key

    cmd = [
        "aider",
        "--model", model,
        "--message", prompt,
        "--no-git"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 🔥 reduced timeout for speed
            env=env
        )

        output = result.stdout.strip()

        if not output:
            return None

        return output

    except subprocess.TimeoutExpired:
        return None

    except Exception:
        return None

# -------------------------
# APPEND (thread-safe)
# -------------------------
lock = threading.Lock()

def append_to_structure(text):
    with lock:
        with open(STRUCTURE_FILE, "a", encoding="utf-8") as f:
            f.write("\n\n" + text.strip() + "\n")

# -------------------------
# PROCESS SINGLE FILE
# -------------------------
def process_file(file_path):

    filename = os.path.basename(file_path)

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()

        prompt = PROMPT_TEMPLATE.format(filename=filename) + "\n\nCODE:\n" + code

        # -------------------------
        # OpenRouter
        # -------------------------
        result = call_model(prompt, PRIMARY_MODEL, OPENROUTER_KEY)

        # -------------------------
        # OpenAI fallback
        # -------------------------
        if not result and OPENAI_KEY:
            result = call_model(prompt, BACKUP_MODEL, OPENAI_KEY, is_openai=True)

        if result:
            append_to_structure(result)
            print(f"✅ {filename}")
        else:
            print(f"❌ FAIL {filename}")

    except Exception as e:
        print(f"❌ ERROR {filename}: {e}")

# -------------------------
# MAIN PARALLEL ENGINE
# -------------------------
def main():

    if not os.path.exists(STRUCTURE_FILE):
        open(STRUCTURE_FILE, "w").close()

    files = get_files()

    print(f"\n📂 Files: {len(files)}")
    print(f"⚡ Workers: {MAX_WORKERS}\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_file, f) for f in files]

        for i, future in enumerate(as_completed(futures), 1):
            future.result()
            print(f"[{i}/{len(files)}] done")

    print("\n🎯 FAST SCAN COMPLETE")


if __name__ == "__main__":
    main()