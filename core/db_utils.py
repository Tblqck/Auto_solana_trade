import sqlite3
import yaml

# Load config
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

DB_PATH = config["DB_PATH"]

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    return conn

def get_db_connection2():
    """
    Return a connection to the SQLite database.
    Automatic timestamp parsing disabled to avoid errors with weird formats.
    """
    return sqlite3.connect(DB_PATH, detect_types=0)

