import requests
import pandas as pd

BE_API = "http://127.0.0.1:8000/api/export/mistakes"

def fetch_mistakes():
    resp = requests.get(BE_API)
    data = resp.json()
    return pd.DataFrame(data)

df_mistakes = fetch_mistakes()
