from fastapi import FastAPI
from fastapi.responses import Response
import subprocess, os, threading

app = FastAPI()

@app.get("/")
def home():
    return {"status": "ATLAS Bot Running!"}

@app.head("/")
async def head_root():
    return Response(status_code=200)

@app.post("/webhook")
async def webhook(request: dict):
    return {"ok": True}

def start_bot():
    os.system("python bot.py")

threading.Thread(target=start_bot, daemon=True).start()
