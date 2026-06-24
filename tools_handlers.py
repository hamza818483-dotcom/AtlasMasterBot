import asyncio
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ATLAS BOT - Tools Handlers (All File & System Tools)"""

import os
import re
import csv
import io
import json
import time
import tempfile
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from config import db, Config, gemini_manager, imgbb_manager
from services import (
    mcqs_to_csv, parse_csv_to_mcqs, format_progress,
    AsyncPDFExporter, SHEET_TEMPLATES, poll_collector,
    add_watermark_to_pdf
)

BOT_START_TIME = datetime.now()

# ============================================================
# HELPER: Direct Supabase calls for tag/exp
# ============================================================

def _sb():
    """Shortcut to Supabase client"""
    return db._client


async def _get_exp():
    """Get exp_settings row, create if missing"""
    try:
        res = _sb().table('exp_settings').select('*').eq('id', 1).execute()
        if res.data:
            return res.data[0]
    except:
        pass
    # Insert default
    try:
        _sb().table('exp_settings').insert({'id': 1, 'mode': 'auto', 'custom_text': '', 'tag_name': ''}).execute()
    except:
        pass
    return {'id': 1, 'mode': 'auto', 'custom_text': '', 'tag_name': ''}


async def _set_exp(**kwargs):
    """Update exp_settings by direct Supabase"""
    try:
        _sb().table('exp_settings').update(kwargs).eq('id', 1).execute()
        return True
    except Exception as e:
        return False


async def _get_tags():
    """Get all tags ordered by id"""
    try:
        res = _sb().table('tag_settings').select('*').order('id').execute()
        return res.data or []
    except:
        return []


async def _toggle_tag(tag_id: int):
    """Toggle is_active for a tag"""
    try:
        res = _sb().table('tag_settings').select('is_active').eq('id', tag_id).execute()
        if not res.data:
            return None
        current = res.data[0]['is_active']
        new_val = 0 if current else 1
        _sb().table('tag_settings').update({'is_active': new_val}).eq('id', tag_id).execute()
        return new_val
    except:
        return None


async def _update_tag_name(tag_id: int, name: str):
    try:
        _sb().table('tag_settings').update({'tag_name': name}).eq('id', tag_id).execute()
        return True
    except:
        return False


async def _delete_tag(tag_id: int):
    try:
        _sb().table('tag_settings').delete().eq('id', tag_id).execute()
        return True
    except:
        return False


async def _add_tag(tag_type: str, tag_name: str):
    try:
        _sb().table('tag_settings').insert({
            'tag_type': tag_type,
            'tag_name': tag_name,
            'position': tag_type,
            'is_active': 1
        }).execute()
        return True
    except:
        return False


def _build_tag_keyboard(tags: list):
    """Build tag management keyboard"""
    buttons = []
    for tag in tags:
        tid = tag['id']
        ttype = tag.get('tag_type', '')
        tname = tag.get('tag_name', '')
        is_active = tag.get('is_active', 0)
        icon = "✅" if is_active == 1 else "❌"
        buttons.append([
            InlineKeyboardButton(f"{icon} {ttype}: {tname[:20]}", callback_data=f"tag_toggle_{tid}"),
            InlineKeyboardButton("✏️", callback_data=f"tag_edit_{tid}"),
            InlineKeyboardButton("🗑️", callback_data=f"tag_delete_{tid}")
        ])
    buttons.append([InlineKeyboardButton("➕ New Tag", callback_data="tag_add")])
    return InlineKeyboardMarkup(buttons)


def _build_tag_text(tags: list):
    pos_labels = {
        'tag1': 'উপরে (গ্যাপ সহ)',
        'tag2': 'নিচে (গ্যাপ সহ)',
        'tag3': 'পাশে inline',
        'tag4': 'উপরে (গ্যাপ ছাড়া)'
    }
    text = "🏷️ Tag Settings\n\n"
    if not tags:
        text += "কোনো ট্যাগ নেই!\n\nTag Types:\n"
        for k, v in pos_labels.items():
            text += f"• {k} — {v}\n"
    else:
        for tag in tags:
            icon = "✅" if tag.get('is_active') == 1 else "❌"
            ttype = tag.get('tag_type', '')
            tname = tag.get('tag_name', '')
            pos = pos_labels.get(ttype, ttype)
            text += f"{icon} {ttype} — {pos}\n   Name: {tname}\n\n"
    return text


# ============================================================
# /split HANDLER
# ============================================================
async def split_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ CSV/JSON ফাইলে reply করে `/split 20` দাও")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ সংখ্যা দাও! যেমন: `/split 20`")
        return
    chunk_size = int(args[0])
    progress = await update.message.reply_text("⏳ ফাইল ডাউনলোড হচ্ছে...")
    file = await update.message.reply_to_message.document.get_file()
    content = await file.download_as_bytearray()
    content_str = content.decode('utf-8-sig')
    filename = update.message.reply_to_message.document.file_name
    mcqs = parse_csv_to_mcqs(content_str)
    if not mcqs:
        await progress.edit_text("❌ ফাইলে কোনো MCQ পাওয়া যায়নি!")
        return
    total = len(mcqs)
    total_parts = (total + chunk_size - 1) // chunk_size
    await progress.edit_text(f"⏳ {total}টি MCQ → {total_parts}টি ফাইলে ভাগ হচ্ছে...")
    for i in range(total_parts):
        chunk = mcqs[i * chunk_size:(i + 1) * chunk_size]
        csv_bytes = mcqs_to_csv(chunk)
        part_name = filename.replace('.csv', f'_part{i+1:02d}.csv').replace('.json', f'_part{i+1:02d}.csv')
        await update.message.reply_document(
            document=csv_bytes, filename=part_name,
            caption=f"📄 Part-{i+1:02d} | 📊 {len(chunk)}টি MCQ"
        )
        await asyncio.sleep(0.5)
    await progress.delete()
    await update.message.reply_text(f"✅ সম্পন্ন! {total}টি MCQ → {total_parts}টি ফাইল")


# ============================================================
# /merge HANDLER
# ============================================================
async def merge_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args if context.args else []
    if 'merge_files' not in context.user_data:
        context.user_data['merge_files'] = []
    if args and args[0] == 'done':
        files = context.user_data.get('merge_files', [])
        if not files:
            await update.message.reply_text("❌ কোনো ফাইল জমা হয়নি!")
            return
        await update.message.reply_text(f"🔄 {len(files)}টি ফাইল মার্জ হচ্ছে...")
        all_mcqs = []
        for content in files:
            all_mcqs.extend(parse_csv_to_mcqs(content))
        if not all_mcqs:
            await update.message.reply_text("❌ কোনো MCQ পাওয়া যায়নি!")
            return
        csv_bytes = mcqs_to_csv(all_mcqs)
        await update.message.reply_document(
            document=csv_bytes, filename="merged.csv",
            caption=f"✅ {len(all_mcqs)}টি MCQ মার্জ! ({len(files)} files)"
        )
        context.user_data['merge_files'] = []
        return
    doc = None
    if update.message.reply_to_message and update.message.reply_to_message.document:
        doc = update.message.reply_to_message.document
    elif update.message.document:
        doc = update.message.document
    if doc:
        if not doc.file_name.endswith(('.csv', '.json')):
            await update.message.reply_text("❌ শুধু CSV/JSON ফাইল!")
            return
        file = await doc.get_file()
        content = await file.download_as_bytearray()
        context.user_data['merge_files'].append(content.decode('utf-8-sig'))
        count = len(context.user_data['merge_files'])
        await update.message.reply_text(f"📥 {doc.file_name}\n📊 Total: {count} file{'s' if count>1 else ''}\n\n➕ আরো পাঠাও\n✅ /merge done")
    else:
        context.user_data['merge_files'] = []
        await update.message.reply_text("📁 Merge Mode Started!\n\nCSV/JSON ফাইলে reply করে /merge দাও।\nশেষে /merge done দাও।")


# ============================================================
# /convert HANDLER
# ============================================================
async def convert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ CSV/JSON ফাইলে reply করে `/convert` দাও")
        return
    file = await update.message.reply_to_message.document.get_file()
    content = await file.download_as_bytearray()
    content_str = content.decode('utf-8-sig')
    filename = update.message.reply_to_message.document.file_name
    if filename.endswith('.csv'):
        mcqs = parse_csv_to_mcqs(content_str)
        json_data = [{"question": m['question'], "options": m['options'], "correct_answer": m['answer'], "explanation": m.get('explanation', '')} for m in mcqs]
        json_bytes = json.dumps(json_data, ensure_ascii=False, indent=2).encode('utf-8')
        await update.message.reply_document(document=json_bytes, filename=filename.replace('.csv', '.json'), caption=f"✅ CSV → JSON | 📊 {len(mcqs)}টি MCQ")
    elif filename.endswith('.json'):
        data = json.loads(content_str)
        mcqs = [{'question': i.get('question', ''), 'options': i.get('options', {}), 'answer': i.get('correct_answer', '1'), 'explanation': i.get('explanation', '')} for i in data]
        csv_bytes = mcqs_to_csv(mcqs)
        await update.message.reply_document(document=csv_bytes, filename=filename.replace('.json', '.csv'), caption=f"✅ JSON → CSV | 📊 {len(mcqs)}টি MCQ")
    else:
        await update.message.reply_text("❌ শুধু .csv বা .json ফাইল সাপোর্টেড!")


# ============================================================
# /rename HANDLER
# ============================================================
async def rename_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text('❌ ফাইলে reply করে `/rename নতুন নাম` দাও')
        return
    args = context.args
    if not args:
        await update.message.reply_text('❌ নাম দাও! যেমন: `/rename নতুননাম`')
        return
    new_name = ' '.join(args)
    file = await update.message.reply_to_message.document.get_file()
    content = await file.download_as_bytearray()
    old_ext = update.message.reply_to_message.document.file_name.split('.')[-1]
    if not new_name.endswith(f'.{old_ext}'):
        new_name += f'.{old_ext}'
    await update.message.reply_document(document=bytes(content), filename=new_name, caption=f"✅ Renamed: {new_name}")


# ============================================================
# /watermark HANDLER
# ============================================================
async def watermark_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ PDF ফাইলে reply করে `/watermark টেক্সট` দাও")
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ ওয়াটারমার্ক টেক্সট দাও!")
        return
    watermark_text = ' '.join(args)
    progress = await update.message.reply_text("⏳ ওয়াটারমার্ক যোগ হচ্ছে...")
    file = await update.message.reply_to_message.document.get_file()
    pdf_bytes = await file.download_as_bytearray()
    watermarked = add_watermark_to_pdf(bytes(pdf_bytes), watermark_text)
    await progress.delete()
    await update.message.reply_document(
        document=watermarked,
        filename=f"watermarked_{update.message.reply_to_message.document.file_name}",
        caption=f"✅ ওয়াটারমার্ক যোগ সম্পন্ন!\n🔤 Text: {watermark_text}"
    )


# ============================================================
# /wm HANDLER
# ============================================================
async def wm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        try:
            res = _sb().table('fixed_watermark').select('text').eq('id', 1).execute()
            wm = res.data[0]['text'] if res.data else None
        except:
            wm = None
        if wm:
            await update.message.reply_text(f"🔒 Fixed Watermark: {wm}\n\n❌ Remove: /wm remove")
        else:
            await update.message.reply_text("❌ No fixed watermark set!\n\nSet: /wm আপনার_টেক্সট")
        return
    text = " ".join(args)
    if text.lower() == "remove":
        try:
            _sb().table('fixed_watermark').delete().eq('id', 1).execute()
        except:
            pass
        await update.message.reply_text("✅ Fixed Watermark Removed!")
        return
    try:
        _sb().table('fixed_watermark').upsert({'id': 1, 'text': text}).execute()
    except:
        pass
    await update.message.reply_text(f"✅ Fixed Watermark Set: {text}\n\nসব PDF-তে Auto Apply হবে!")


# ============================================================
# /exp HANDLER
# ============================================================
async def exp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exp = await _get_exp()
    mode = exp.get('mode', 'auto')
    custom = exp.get('custom_text', '') or ''
    tag = exp.get('tag_name', '') or ''

    mode_labels = {'auto': '🟢 AUTO', 'custom': '🔵 CUSTOM', 'tag': '🟡 TAG'}
    text = f"💬 Explanation Settings\n\n"
    text += f"Current Mode: {mode_labels.get(mode, mode.upper())}\n"
    if mode == 'custom' and custom:
        text += f"Custom Text: {custom[:80]}{'...' if len(custom)>80 else ''}\n"
    if mode == 'tag' and tag:
        text += f"Tag Name: {tag}\n"
    text += "\nModes:\n• Auto — MCQ এর নিজের explanation\n• Custom — নিজের লেখা text সব MCQ তে\n• Tag — explanation এর পরে tag name বসবে"

    buttons = [
        [InlineKeyboardButton(f"{'✅ ' if mode=='auto' else ''}💥 Auto", callback_data="exp_set_auto"),
         InlineKeyboardButton(f"{'✅ ' if mode=='custom' else ''}✏️ Custom", callback_data="exp_set_custom"),
         InlineKeyboardButton(f"{'✅ ' if mode=='tag' else ''}🏷️ Tag", callback_data="exp_set_tag")],
    ]
    if mode == 'custom':
        buttons.append([InlineKeyboardButton("📝 Custom Text পরিবর্তন করো", callback_data="exp_edit_custom")])
    if mode == 'tag':
        buttons.append([InlineKeyboardButton("📝 Tag Name পরিবর্তন করো", callback_data="exp_edit_tag")])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


# ============================================================
# /tag HANDLER
# ============================================================
async def tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tags = await _get_tags()
    text = _build_tag_text(tags)
    keyboard = _build_tag_keyboard(tags)
    await update.message.reply_text(text, reply_markup=keyboard)


# ============================================================
# /thumb HANDLER
# ============================================================
async def thumb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0] == 'remove':
        try:
            _sb().table('thumbnail').delete().eq('id', 1).execute()
        except:
            pass
        await update.message.reply_text("✅ থাম্বনেইল রিমুভ করা হয়েছে!")
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        try:
            res = _sb().table('thumbnail').select('file_id').eq('id', 1).execute()
            thumb = res.data[0]['file_id'] if res.data else None
        except:
            thumb = None
        if thumb:
            await update.message.reply_text(f"📌 বর্তমান থাম্বনেইল সেট আছে।\n\n/thumb remove — রিমুভ\nইমেজে reply করে /thumb — নতুন সেট")
        else:
            await update.message.reply_text("❌ ইমেজে reply করে /thumb দাও, অথবা /thumb remove।")
        return
    photo = update.message.reply_to_message.photo[-1]
    file_id = photo.file_id
    try:
        _sb().table('thumbnail').upsert({'id': 1, 'file_id': file_id}).execute()
    except:
        pass
    await update.message.reply_text("✅ থাম্বনেইল সেট করা হয়েছে!\n/thumb remove — রিমুভ করতে")


# ============================================================
# /sheet HANDLER
# ============================================================
async def sheet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ CSV ফাইলে reply করে /sheet দাও")
        return
    progress = await update.message.reply_text("⏳ ফাইল প্রসেসিং...")
    file = await update.message.reply_to_message.document.get_file()
    content = await file.download_as_bytearray()
    mcqs = parse_csv_to_mcqs(content.decode('utf-8-sig'))
    if not mcqs:
        await progress.edit_text("❌ ফাইলে কোনো MCQ পাওয়া যায়নি!")
        return
    context.user_data['sheet_mcqs'] = mcqs
    formats = await db.fetchall('SELECT format_id, format_name, is_active FROM sheet_formats')
    buttons = []
    for fid, fname, is_active in formats:
        buttons.append([InlineKeyboardButton(f"{'✅' if is_active else '❌'} {fname}", callback_data=f"sheet_toggle_{fid}")])
    buttons.append([InlineKeyboardButton("✅ Done — Generate PDF", callback_data="sheet_generate")])
    buttons.append([InlineKeyboardButton("📚 All Active Formats", callback_data="sheet_all")])
    context.user_data['sheet_selected'] = [fid for fid, _, is_active in formats if is_active]
    await progress.delete()
    await update.message.reply_text(
        f"📊 {len(mcqs)}টি MCQ পাওয়া গেছে!\n\nActive ফরম্যাট সিলেক্ট করো:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ============================================================
# /ping HANDLER
# ============================================================
async def ping_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.now() - BOT_START_TIME
    days = uptime.days
    hours, rem = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    try:
        import psutil
        ram_mb = psutil.Process().memory_info().rss / 1024 / 1024
        ram_text = f"🖥️ RAM: {ram_mb:.0f} MB"
    except:
        ram_text = "🖥️ RAM: N/A"
    await update.message.reply_text(f"🟢 Bot চালু আছে!\n\n⏱️ Uptime: {days}d {hours}h {minutes}m {seconds}s\n📅 Started: {BOT_START_TIME.strftime('%Y-%m-%d %H:%M:%S')}\n{ram_text}")


# ============================================================
# /error HANDLER
# ============================================================
async def error_handler_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = "🔍 Bot Health Check:\n\n"
    try:
        stats = gemini_manager.get_stats()
        report += f"✅ Gemini API: {stats['healthy']}/{stats['total']} keys active\n"
    except Exception as e:
        report += f"❌ Gemini API: {str(e)[:50]}\n"
    try:
        report += f"✅ ImgBB API: {len(imgbb_manager.keys)} keys\n"
    except Exception as e:
        report += f"❌ ImgBB API: {str(e)[:50]}\n"
    try:
        await db.fetchone('SELECT 1')
        report += "✅ Database: ঠিক আছে\n"
    except Exception as e:
        report += f"❌ Database: {str(e)[:50]}\n"
    channels = await db.fetchall('SELECT COUNT(*) FROM channels')
    report += f"\n📢 Channels: {channels[0][0]} connected\n"
    users = await db.fetchall('SELECT COUNT(*) FROM bot_users')
    report += f"👤 Users: {users[0][0]}\n"
    await update.message.reply_text(report)


# ============================================================
# /logs HANDLER
# ============================================================
async def logs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != Config.OWNER_ID:
        await update.message.reply_text("❌ Owner only!")
        return
    try:
        import subprocess
        result = subprocess.run(['journalctl', '-u', 'atlas-bot', '-n', '500'], capture_output=True, text=True)
        logs = result.stdout or "No systemd logs found."
    except:
        logs = "Cannot read systemd logs."
    await update.message.reply_document(document=logs.encode('utf-8'), filename='atlas_bot_logs.txt', caption="📋 Last 500 lines")


# ============================================================
# /collect, /done, /status, /cancel HANDLERS
# ============================================================
async def collect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_collector.start(update.effective_user.id)
    await update.message.reply_text("📥 Poll Collection শুরু!\n\nPoll পাঠাও।\n• /done — CSV পাবে\n• /status — count\n• /cancel — বাতিল")

async def done_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    polls = poll_collector.finish(update.effective_user.id)
    if not polls:
        await update.message.reply_text("❌ কোনো পোল সংগ্রহ করা হয়নি!")
        return
    mcq_list = [{'question': p.get('questions', p.get('question', '')), 'options': {'A': p.get('option1', ''), 'B': p.get('option2', ''), 'C': p.get('option3', ''), 'D': p.get('option4', '')}, 'answer': p.get('answer', '1'), 'explanation': p.get('explanation', '')} for p in polls]
    csv_bytes = mcqs_to_csv(mcq_list)
    await update.message.reply_document(document=csv_bytes, filename=f"collected_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", caption=f"✅ {len(polls)}টি পোল সংগ্রহ সম্পন্ন!")

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = poll_collector.get_count(update.effective_user.id)
    await update.message.reply_text(f"📊 Collected: {count} টি পোল")

async def cancel_collection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_collector.cancel(update.effective_user.id)
    await update.message.reply_text("❌ Collection বাতিল করা হয়েছে!")

async def pause_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from global_state import GLOBAL_PAUSE
    GLOBAL_PAUSE[update.effective_user.id] = True
    await update.message.reply_text("⏸️ পোল পাঠানো থামানো হয়েছে!\n▶️ /resume দিয়ে আবার চালু করো।")

async def resume_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from global_state import GLOBAL_PAUSE
    GLOBAL_PAUSE[update.effective_user.id] = False
    await update.message.reply_text("▶️ পোল পাঠানো আবার চালু হয়েছে!")


# ============================================================
# /update, /gemini, /addgkey, /restart HANDLERS
# ============================================================
async def update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != Config.OWNER_ID:
        await update.message.reply_text("❌ Owner only!"); return
    await update.message.reply_text("📤 Pushing to GitHub...")
    result = os.popen("cd ~/AtlasMasterBot && git add . && git commit -m 'Bot /update' && git push 2>&1").read()
    await update.message.reply_text(f"✅ Done!\n{result[:500]}")

async def gemini_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import requests
    keys = [k.strip() for k in os.getenv('GEMINI_API_KEYS', '').split(',') if k.strip()]
    msg = await update.message.reply_text(f"🔍 Checking {len(keys)} keys...")
    work = 0
    result = f"📊 Gemini API Keys Status\n\nTotal: {len(keys)} keys\n\n"
    for i, key in enumerate(keys, 1):
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}'
        try:
            r = requests.post(url, json={'contents': [{'parts': [{'text': 'hi'}]}]}, timeout=10)
            if r.status_code == 200:
                result += f"Key {i}: ✅ Working\n"; work += 1
            else:
                result += f"Key {i}: ❌ {r.json().get('error',{}).get('message','Unknown')[:50]}\n"
        except Exception as e:
            result += f"Key {i}: ❌ {str(e)[:40]}\n"
    result += f"\n✅ Working: {work}/{len(keys)}"
    await msg.edit_text(result)

async def addgkey_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != Config.OWNER_ID:
        await update.message.reply_text("❌ Owner only!"); return
    if not context.args:
        await update.message.reply_text("❌ /addgkey key1,key2,key3"); return
    new_keys = ' '.join(context.args).replace(' ', '')
    env_path = os.path.expanduser('~/AtlasMasterBot/.env')
    with open(env_path, 'r') as f:
        lines = f.readlines()
    with open(env_path, 'w') as f:
        for line in lines:
            if line.startswith('GEMINI_API_KEYS='):
                current = line.strip().replace('GEMINI_API_KEYS=', '')
                updated = f"GEMINI_API_KEYS={current},{new_keys}\n" if current else f"GEMINI_API_KEYS={new_keys}\n"
                f.write(updated)
            else:
                f.write(line)
    await update.message.reply_text(f"✅ Keys added!\nRestart: /restart")

async def restart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != Config.OWNER_ID:
        await update.message.reply_text("❌ Owner only!"); return
    await update.message.reply_text("🔄 Restarting...")
    pid = os.getpid()
    os.system("pkill -9 -f 'python bot.py' 2>/dev/null; sleep 2; cd ~/AtlasMasterBot && nohup python bot.py > /dev/null 2>&1 &")
    os.kill(pid, 9)


# ============================================================
# TOOLS CALLBACK HANDLER — fully fixed
# ============================================================
async def handle_tools_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── EXP CALLBACKS ──────────────────────────────────────

    if data in ('exp_set_auto', 'exp_set_custom', 'exp_set_tag'):
        mode = data.replace('exp_set_', '')
        ok = await _set_exp(mode=mode)
        if not ok:
            await query.answer("❌ Save failed!", show_alert=True)
            return

        if mode == 'auto':
            await query.edit_message_text(
                "✅ Auto Mode Activated!\nMCQ এর নিজের explanation যাবে।"
            )

        elif mode == 'custom':
            context.user_data['exp_waiting'] = 'custom'
            await query.edit_message_text(
                "✏️ Custom Explanation লিখো:\n(সব MCQ তে এই text টাই explanation হিসেবে যাবে)"
            )

        elif mode == 'tag':
            context.user_data['exp_waiting'] = 'tag'
            await query.edit_message_text(
                "🏷️ Tag Name লিখো:\n(explanation এর পরে এই text বসবে)"
            )
        return

    if data == 'exp_edit_custom':
        context.user_data['exp_waiting'] = 'custom'
        await query.edit_message_text("✏️ নতুন Custom Explanation লিখো:")
        return

    if data == 'exp_edit_tag':
        context.user_data['exp_waiting'] = 'tag'
        await query.edit_message_text("🏷️ নতুন Tag Name লিখো:")
        return

    # ── TAG CALLBACKS ──────────────────────────────────────

    elif data.startswith('tag_toggle_'):
        tag_id = int(data.replace('tag_toggle_', ''))
        new_state = await _toggle_tag(tag_id)
        if new_state is None:
            await query.answer("❌ Toggle failed!", show_alert=True)
            return
        await query.answer("✅ Active" if new_state == 1 else "❌ Inactive")
        # Refresh keyboard
        tags = await _get_tags()
        try:
            await query.edit_message_text(
                _build_tag_text(tags),
                reply_markup=_build_tag_keyboard(tags)
            )
        except:
            await query.edit_message_reply_markup(reply_markup=_build_tag_keyboard(tags))

    elif data.startswith('tag_edit_'):
        tag_id = int(data.replace('tag_edit_', ''))
        context.user_data['tag_waiting'] = 'edit'
        context.user_data['tag_edit_id'] = tag_id
        await query.edit_message_text("✏️ নতুন Tag Name লিখো:")

    elif data.startswith('tag_delete_'):
        tag_id = int(data.replace('tag_delete_', ''))
        ok = await _delete_tag(tag_id)
        if not ok:
            await query.answer("❌ Delete failed!", show_alert=True)
            return
        await query.answer("🗑️ Deleted!")
        tags = await _get_tags()
        try:
            await query.edit_message_text(
                _build_tag_text(tags),
                reply_markup=_build_tag_keyboard(tags)
            )
        except:
            pass

    elif data == 'tag_add':
        context.user_data['tag_waiting'] = 'type_select'
        buttons = [
            [InlineKeyboardButton("tag1 — উপরে (গ্যাপ সহ)", callback_data="tag_type_tag1")],
            [InlineKeyboardButton("tag2 — নিচে (গ্যাপ সহ)", callback_data="tag_type_tag2")],
            [InlineKeyboardButton("tag3 — পাশে inline", callback_data="tag_type_tag3")],
            [InlineKeyboardButton("tag4 — উপরে (গ্যাপ ছাড়া)", callback_data="tag_type_tag4")],
            [InlineKeyboardButton("❌ Cancel", callback_data="tag_add_cancel")],
        ]
        await query.edit_message_text("🏷️ Tag Type সিলেক্ট করো:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith('tag_type_'):
        tag_type = data.replace('tag_type_', '')
        context.user_data['tag_waiting'] = 'add_name'
        context.user_data['tag_new_type'] = tag_type
        await query.edit_message_text(f"✏️ {tag_type} এর Name লিখো:")

    elif data == 'tag_add_cancel':
        context.user_data.pop('tag_waiting', None)
        context.user_data.pop('tag_new_type', None)
        tags = await _get_tags()
        await query.edit_message_text(_build_tag_text(tags), reply_markup=_build_tag_keyboard(tags))

    # ── SHEET CALLBACKS ────────────────────────────────────

    elif data.startswith('sheet_toggle_'):
        fid = data.replace('sheet_toggle_', '')
        selected = context.user_data.get('sheet_selected', [])
        if fid in selected:
            selected.remove(fid)
        else:
            selected.append(fid)
        context.user_data['sheet_selected'] = selected
        await query.answer(f"{len(selected)} টি সিলেক্টেড")

    elif data == 'sheet_generate':
        selected = context.user_data.get('sheet_selected', [])
        mcqs = context.user_data.get('sheet_mcqs', [])
        if not selected or not mcqs:
            await query.edit_message_text("❌ কোনো ফরম্যাট বা MCQ নেই!")
            return
        await query.edit_message_text("📝 PDF এর Title লিখো:")
        context.user_data['sheet_formats'] = selected
        context.user_data['waiting_sheet_title'] = True

    elif data == 'sheet_all':
        formats = await db.fetchall('SELECT format_id FROM sheet_formats WHERE is_active = 1')
        context.user_data['sheet_selected'] = [f[0] for f in formats]
        await query.answer(f"All {len(formats)} Active Formats Selected!")


# ============================================================
# MESSAGE HANDLER FOR SETTINGS
# ============================================================
async def handle_settings_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # ── EXP text input ─────────────────────────────────────
    exp_waiting = context.user_data.get('exp_waiting')

    if exp_waiting == 'custom':
        ok = await _set_exp(custom_text=text)
        context.user_data.pop('exp_waiting', None)
        if ok:
            await update.message.reply_text("✅ Custom Explanation সেট হয়েছে!\nসব MCQ তে এটাই যাবে।")
        else:
            await update.message.reply_text("❌ Save failed! আবার চেষ্টা করো।")
        return

    if exp_waiting == 'tag':
        ok = await _set_exp(tag_name=text)
        context.user_data.pop('exp_waiting', None)
        if ok:
            await update.message.reply_text("✅ Tag Name সেট হয়েছে!\nExplanation এর পরে বসবে।")
        else:
            await update.message.reply_text("❌ Save failed! আবার চেষ্টা করো।")
        return

    # ── TAG text input ─────────────────────────────────────
    tag_waiting = context.user_data.get('tag_waiting')

    if tag_waiting == 'edit':
        tag_id = context.user_data.get('tag_edit_id')
        if tag_id:
            ok = await _update_tag_name(tag_id, text)
            context.user_data.pop('tag_waiting', None)
            context.user_data.pop('tag_edit_id', None)
            if ok:
                await update.message.reply_text("✅ Tag Name আপডেট হয়েছে!")
            else:
                await update.message.reply_text("❌ Update failed!")
        return

    if tag_waiting == 'add_name':
        tag_type = context.user_data.get('tag_new_type', 'tag1')
        ok = await _add_tag(tag_type, text)
        context.user_data.pop('tag_waiting', None)
        context.user_data.pop('tag_new_type', None)
        if ok:
            await update.message.reply_text(f"✅ নতুন Tag '{text}' ({tag_type}) যোগ হয়েছে!")
        else:
            await update.message.reply_text("❌ Add failed!")
        return

    # ── Sheet title ─────────────────────────────────────────
    if context.user_data.get('waiting_sheet_title'):
        title = text
        selected = context.user_data.get('sheet_formats', [])
        mcqs = context.user_data.get('sheet_mcqs', [])
        context.user_data.pop('waiting_sheet_title', None)
        if not mcqs:
            await update.message.reply_text("❌ MCQ সেশন শেষ!")
            return
        progress = await update.message.reply_text("🖨️ PDF তৈরি হচ্ছে...")
        for fid in selected:
            template_str = SHEET_TEMPLATES.get(fid)
            if template_str:
                from jinja2 import Template
                html = Template(template_str).render(title=title, mcqs=mcqs)
                pdf_path = f"data/temp/sheet_{fid}_{int(time.time())}.pdf"
                success = await AsyncPDFExporter.html_to_pdf(html, pdf_path)
                if success:
                    try:
                        res = _sb().table('thumbnail').select('file_id').eq('id', 1).execute()
                        thumb = res.data[0]['file_id'] if res.data else None
                    except:
                        thumb = None
                    with open(pdf_path, 'rb') as f:
                        await update.message.reply_document(document=f.read(), filename=f"{title}_{fid}.pdf", thumbnail=thumb)
                    os.remove(pdf_path)
        await progress.delete()
        await update.message.reply_text(f"✅ {len(selected)}টি ফরম্যাটে PDF তৈরি সম্পন্ন!")
        return
