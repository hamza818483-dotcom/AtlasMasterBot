import os, requests, json

async def addgkey_handler(update, context):
    """Add Gemini key + update HF Secrets"""
    if not await check_permitted(update.effective_user.id):
        await update.message.reply_text("❌ Access denied."); return
    
    if not context.args:
        await update.message.reply_text("Usage: /addgkey AIzaSy...")
        return
    
    new_key = context.args[0]
    current = os.getenv('GEMINI_API_KEYS', '')
    updated = f"{current},{new_key}" if current else new_key
    
    # Update HF Secret
    HF_TOKEN = os.getenv('HF_TOKEN', '')
    SPACE_ID = "HamzaHF1/ATLAS-Bot"
    
    resp = requests.post(
        f"https://huggingface.co/api/spaces/{SPACE_ID}/secrets",
        headers={"Authorization": f"Bearer {HF_TOKEN}"},
        json={"key": "GEMINI_API_KEYS", "value": updated}
    )
    
    if resp.status_code == 200:
        await update.message.reply_text(f"✅ Key added! Total keys: {len(updated.split(','))}\n🔄 Space restarting...")
    else:
        await update.message.reply_text(f"❌ Failed: {resp.text[:100]}")
