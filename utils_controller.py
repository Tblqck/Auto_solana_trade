# utils_controller.py
import pandas as pd

def get_controller_status(file="controller.csv"):
    df = pd.read_csv(file)
    return df.iloc[0]["status"].strip().upper()

def set_controller_status(value: str, file="controller.csv"):
    df = pd.read_csv(file)
    df.at[0, "status"] = value.upper()
    df.to_csv(file, index=False)

def flip_status2(file, value: str):
    df = pd.read_csv(file)
    df.at[0, "status2"] = value.upper()
    df.to_csv(file, index=False)
