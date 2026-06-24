import requests
import os
import random
import base64
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEYS = [k.strip() for k in os.getenv('GEMINI_API_KEYS', '').split(',') if k.strip()]
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
quota_keys = set()


def call_gemini(prompt, image_bytes=None):
    available_keys = [k for k in GEMINI_API_KEYS if k not in quota_keys]
    if not available_keys:
        quota_keys.clear()
        available_keys = GEMINI_API_KEYS[:]
    if not available_keys:
        return "[]"
    for attempt in range(len(available_keys)):
        key = available_keys[attempt % len(available_keys)]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 65536, "temperature": 0.7}
        }
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode()
            payload["contents"][0]["parts"].append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
        try:
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                return data['candidates'][0]['content']['parts'][0]['text']
            elif resp.status_code == 429 or 'demand' in resp.text.lower() or 'quota' in resp.text.lower():
                quota_keys.add(key)
                continue
            else:
                print(f"Gemini error {resp.status_code}: {resp.text[:200]}")
                quota_keys.add(key)
                continue
        except Exception as e:
            print(f"Gemini exception: {e}")
            quota_keys.add(key)
            continue
    return "[]"


def get_healthy_key():
    available = [k for k in GEMINI_API_KEYS if k not in quota_keys]
    if not available:
        quota_keys.clear()
        available = GEMINI_API_KEYS[:]
    return random.choice(available) if available else ""
