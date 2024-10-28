import os
import requests

try:
    TELEGRAM_API_KEY = os.environ["TELEGRAM_API_KEY"]
except KeyError:
    raise ValueError("TELEGRAM_API_KEY not set")


def send_message(chat_id, message):
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_API_KEY}/sendMessage",
        data={"chat_id": chat_id, "text": message},
    )

    resp.raise_for_status()
