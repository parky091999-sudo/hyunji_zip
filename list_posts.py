import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from config import THREADS_ACCESS_TOKEN, THREADS_USER_ID
import requests

resp = requests.get(
    f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads",
    params={"fields": "id,text,permalink,timestamp", "limit": 20, "access_token": THREADS_ACCESS_TOKEN},
    timeout=15
)
data = resp.json()
for p in data.get("data", []):
    text_preview = str(p.get("text", ""))[:80].replace("\n", " ")
    print(f"ID: {p.get('id')} | {p.get('timestamp','')} | {text_preview}")
    print(f"  URL: {p.get('permalink','')}")
    print()
