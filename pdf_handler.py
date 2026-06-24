#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ATLAS BOT - PDF Handlers - FIXED ALL"""
import os, re, io, json, time, asyncio, logging, tempfile
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import db, check_permitted
from services import pdf_processor, generate_mcqs_from_image, mcqs_to_csv, format_progress, parse_csv_to_mcqs
from ocr_engine import ocr_image, is_scanned_pdf
from cache_handler import get_cached_mcqs, save_mcq_cache
from global_state import GLOBAL_PAUSE
from csv_poll_handler import get_pre_message, get_ending_message, get_message_link

logger = logging.getLogger(__name__)

QBM_EXTRACT_PROMPT = """YOU ARE A STRICT MCQ EXTRACTOR. YOUR ONLY JOB IS TO EXTRACT EXISTING MCQs. FOLLOW EVERY RULE WITHOUT EXCEPTION.

════════════════════════════════
🔴 ABSOLUTE FORBIDDEN RULES
════════════════════════════════
❌ NEVER create new questions from any text or information
❌ NEVER add extra MCQs beyond what exists in the image
❌ NEVER skip any existing MCQ — extract ALL of them
❌ NEVER guess an answer — only detect from image
❌ NEVER modify question text (only remove numbering)

════════════════════════════════
📌 EXTRACTION RULES
════════════════════════════════
✅ Extract ALL MCQs — Bangla, English, or mixed language
✅ Extract from any font style — printed, handwritten, bold, italic
✅ Extract from blurry, low quality, or scanned PDF images
✅ Perform MULTIPLE OCR passes — triple check every MCQ
✅ Remove question numbering only: (১., 1., Q1., Q.1, ক., a.) from question text
✅ Keep original question and option text intact
✅ If any major spelling mistake seen,corrrect it
════════════════════════════════
🎯 ANSWER DETECTION (ALL FORMATS)
════════════════════════════════
Format 1 — Answer beside question: detect circle/tick/underline/bold/star (★) on option
Format 2 — Answer box at page bottom: match question number → correct option letter
Format 3 — Answer key on different page (few pages later):
→ Scan ALL pages for answer keys
→ Match question number exactly → correct option
→ NEVER assume answer if not found in image
→ If answer not found anywhere → set answer as "A" and note in explanation "Answer not found in source"
Format 4 — Answer after each question block: read carefully
→ Convert all answer formats to A/B/C/D in output

════════════════════════════════
💡 EXPLANATION RULES
════════════════════════════════
- Why correct answer is correct (from Gemini latest real knowledge)
- Why each wrong option is wrong (briefly)
- Related topic info from latest real source
- Max 165 characters, Bengali language
- Must be factually accurate — use Gemini's real knowledge

════════════════════════════════
📤 OUTPUT FORMAT
════════════════════════════════
Output ONLY a valid JSON array. No extra text. No markdown. No explanation outside JSON.
If NO MCQ exists in image → return exactly: []

[{"question":"...","options":{"A":"...","B":"...","C":"...","D":"..."},"answer":"A/B/C/D","explanation":"... (max 165 chars Bengali)"}]"""

async def update_dashboard(msg, data: dict):
    pct = data.get('pct', 0)
    bar_len = 20
    filled = int(bar_len * pct / 100)
    bar = '█' * filled + '░' * (bar_len - filled)
    status = data.get('status', '⏳')
    target_info = ""
    if data.get('target_pages'):
        target_info = f"\n║ 🎯 Target: {data.get('target_pages',''):<27} ║"
    dashboard = f"""╔══════════════════════════════════╗
║     📊 ATLAS PDF PROCESSOR      ║
╠══════════════════════════════════╣
║ 📁 {data.get('pdf','N/A')[:30]:<30} ║
║ 📥 {data.get('dl','')[:32]:<32} ║
╠══════════════════════════════════╣
║ 📄 Pages: {data.get('pg','0/0'):<24} ║
║ 📝 MCQ: {data.get('mcq',0):<26} ║
║ 📤 Sent: {data.get('sent','0/0'):<25} ║
║ ⏱️ {data.get('time',''):<30} ║{target_info}
║ [{bar}] {pct}%{'':<10} ║
║ {status:<32} ║
╚══════════════════════════════════╝"""
    try:
        await msg.edit_text(f"```{dashboard}```", parse_mode='Markdown')
    except:
        await msg.edit_text(dashboard)


async def send_poll_robust(bot, chat_id, mcq, reply_to, uid, with_source=False):
    for attempt in range(10):
        while GLOBAL_PAUSE.get(uid, False):
            await asyncio.sleep(1)
        try:
            from csv_poll_handler import get_explanation, get_question_with_tags
            q_raw = mcq.get('question', '?')
            source_tag = ''
            if with_source:
                src_matches = re.findall(r'[\[\(][^\]\)]*?(?:BCS|DU|HSTU|Medical|Admission|Exam|Test|উন্মেষ|মেডিকেল|RU|JU|CU|GST)[^\]\)]*[\]\)]', q_raw, re.IGNORECASE)
                if src_matches: source_tag = ' ' + ' '.join(src_matches)
            q_no_num = re.sub(r'^\s*[\d০-৯]+\s*[.)\-:\s]+\s*', '', q_raw)
            q_no_num = re.sub(r'^\s*[Qq]\.?\s*[\d]+\s*[.)\-:\s]*\s*', '', q_no_num)
            q_clean = re.sub(r'\s*[\[\(].*?[\]\)]\s*$', '', q_no_num).strip() + source_tag
            q = await get_question_with_tags(q_clean)
            q = q[:300]
            opts = [mcq.get('options', {}).get(k, 'Option ' + k) for k in ['A', 'B', 'C', 'D']]
            ans = str(mcq.get('answer', '1')).upper()
            cid = {'A': 0, 'B': 1, 'C': 2, 'D': 3, '1': 0, '2': 1, '3': 2, '4': 3}.get(ans, 0)
            exp = await get_explanation(mcq)
            poll_msg = await bot.send_poll(
                chat_id=chat_id, question=q, options=opts,
                type='quiz', correct_option_id=cid, explanation=exp or None,
                is_anonymous=True, reply_to_message_id=reply_to
            )
            return poll_msg.message_id, True 
        except:
            if attempt < 9: await asyncio.sleep(3)
    return None, False


def parse_args(args):
    page_range, channel_id, title, mcq_count = None, None, "MCQ Practice", None
    i = 0
    while i < len(args):
        if args[i] == '-p' and i + 1 < len(args):
            page_range = args[i + 1]; i += 2
        elif args[i] == '-c' and i + 1 < len(args):
            channel_id = args[i + 1]; i += 2
        elif args[i] == '-m' and i + 1 < len(args):
            title = args[i + 1]; i += 2
        else:
            match = re.match(r'\[(\d+)\]', args[i])
            if match: mcq_count = int(match.group(1))
            i += 1
    return page_range, channel_id, title, mcq_count


async def pdfm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permitted(update.effective_user.id):
        await update.message.reply_text("❌ আপনার এই feature ব্যবহারের অনুমতি নেই।"); return
    if not update.message or not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ PDF ফাইলে reply করে `/pdfm` দাও"); return
    doc = update.message.reply_to_message.document
    if not doc.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("❌ শুধু PDF!"); return
    page_range, channel_id, title, mcq_count = parse_args(context.args)
    for k, v in [('pdf_title', title), ('pdf_channel', channel_id), ('pdf_mcq_count', mcq_count),
                 ('pdf_page_range', page_range), ('pdf_doc', doc.file_id)]:
        context.chat_data[k] = v
    buttons = [
        [InlineKeyboardButton("📸 Image Mood", callback_data="pdfm_mood_image")],
        [InlineKeyboardButton("📝 Topic Name Mood", callback_data="pdfm_mood_topic")],
        [InlineKeyboardButton("❌ Cancel", callback_data="pdfm_cancel")]
    ]
    await update.message.reply_text(
        f"📄 PDF MCQ Generation\n\n📁 {doc.file_name}\n📄 Pages: {page_range or 'All'}\n📝 {title}\n🎯 MCQ/Page: {mcq_count or 'Auto'}\n\nSelect Mood:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def qbm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permitted(update.effective_user.id):
        await update.message.reply_text("❌ আপনার এই feature ব্যবহারের অনুমতি নেই।"); return
    if not update.message or not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ PDF ফাইলে reply করে `/qbm` দাও"); return
    doc = update.message.reply_to_message.document
    if not doc.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("❌ শুধু PDF!"); return
    page_range, channel_id, title, mcq_count = parse_args(context.args)
    for k, v in [('qbm_doc', doc.file_id), ('qbm_page_range', page_range),
                 ('qbm_title', title), ('qbm_channel', channel_id), ('qbm_mcq_count', mcq_count)]:
        context.chat_data[k] = v
    buttons = [
        [InlineKeyboardButton("📸 Image Mood", callback_data="qbm_mood_image")],
        [InlineKeyboardButton("📝 Topic Name Mood", callback_data="qbm_mood_topic")],
    ]
    await update.message.reply_text(
        f"📋 QBM Extraction\n\n📄 Pages: {page_range or 'All'}\n🎯 MCQ/Page: {mcq_count or 'Auto'}\n\nSelect Mood:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def send_polls_to_channel(update, context, channel_id, mcqs, topic, mood, images=None):
    """Send polls to channel"""
    from csv_poll_handler import send_single_poll, get_pre_message, get_ending_message, get_message_link
    query = update.callback_query if hasattr(update, "callback_query") else None
    bot = context.bot
    total = len(mcqs)
    if mood == "image" and images:
        per_image = max(1, total // len(images))
        mcq_idx = 0
        for i, img_data in enumerate(images):
            img_bytes = img_data[1] if isinstance(img_data, tuple) else img_data
            img_msg = await bot.send_photo(chat_id=channel_id, photo=io.BytesIO(img_bytes if isinstance(img_bytes, bytes) else img_bytes))
            page_mcqs = mcqs[mcq_idx:mcq_idx + per_image]
            first_pid, psent = None, 0
            for mcq in page_mcqs:
                pid, ok = await send_single_poll(bot, channel_id, mcq, img_msg.message_id)
                if ok and not first_pid: first_pid = pid
                if ok: psent += 1
                await asyncio.sleep(1)
            mcq_idx += per_image
            first_link = await get_message_link(bot, channel_id, first_pid) if first_pid else ""
            ending = get_ending_message(f"{topic} (Page-{i + 1:02d})", psent, first_link)
            await bot.send_message(chat_id=channel_id, text=ending, reply_to_message_id=img_msg.message_id)
    else:
        pre_text = get_pre_message(topic, total)
        pre_msg = await bot.send_message(chat_id=channel_id, text=pre_text)
        first_pid, psent = None, 0
        for mcq in mcqs:
            pid, ok = await send_single_poll(bot, channel_id, mcq, pre_msg.message_id)
            if ok and not first_pid: first_pid = pid
            if ok: psent += 1
            await asyncio.sleep(1)
        first_link = await get_message_link(bot, channel_id, first_pid) if first_pid else ""
        ending = get_ending_message(topic, psent, first_link)
        await bot.send_message(chat_id=channel_id, text=ending, reply_to_message_id=pre_msg.message_id)
    if query:
        await query.message.reply_text(f"✅ {total} polls sent!")


async def process_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE, is_qbm: bool = False, mood: str = 'topic'):
    query = update.callback_query if hasattr(update, 'callback_query') else None
    uid = update.effective_user.id
    prefix = 'qbm' if is_qbm else 'pdf'
    title = context.chat_data.get(f'{prefix}_title') or context.chat_data.get('pdf_title', 'MCQ')
    channel_id = context.chat_data.get(f'{prefix}_channel') or context.chat_data.get('pdf_channel')
    mcq_count = context.chat_data.get(f'{prefix}_mcq_count') or context.chat_data.get('pdf_mcq_count')
    page_range_str = context.chat_data.get(f'{prefix}_page_range') or context.chat_data.get('pdf_page_range')
    doc_id = context.chat_data.get(f'{prefix}_doc') or context.chat_data.get('pdf_doc')
    with_source = context.chat_data.get('qbm_with_source', False)

    if not doc_id:
        if query: await query.edit_message_text("❌ PDF not found!")
        return

    msg_target = query.message if query else update.message
    start_time = time.time()
    if is_qbm:
        cnt_per_page = 0  # Extract ALL existing MCQ
    else:
        cnt_per_page = int(mcq_count) if mcq_count else 0  # 0 = HIGHEST possible

    dash_data = {
        'pdf': 'Loading...', 'dl': '', 'pg': '0/0', 'mcq': 0,
        'sent': '0/0', 'time': '', 'pct': 0, 'status': '📥 Downloading...',
        'target_pages': page_range_str or 'All', 
    }
    dash_msg = await msg_target.reply_text("⏳ Initializing...")
    await update_dashboard(dash_msg, dash_data)

    sp, ep = 1, None
    if page_range_str:
        try:
            m = re.match(r'^(\d+)-(\d+)$', page_range_str.strip())
            if m: sp, ep = int(m.group(1)), int(m.group(2))
            else: sp = ep = int(page_range_str.strip())
        except: pass

    try:
            file = await context.bot.get_file(doc_id)
            pdf_name = file.file_path.split('/')[-1] if file.file_path else "PDF"
            dash_data['pdf'] = pdf_name
            pdf_bytes = await file.download_as_bytearray()
            if isinstance(pdf_bytes, bytearray): pdf_bytes = bytes(pdf_bytes)
            dash_data['dl'] = f"Done {len(pdf_bytes) / 1024:.0f}KB"
    except:
        dash_data['status'] = '❌ Download Failed'
        await update_dashboard(dash_msg, dash_data)
        return

    pdf_path = f"data/temp/pdf_{int(time.time())}_{uid}.pdf"
    os.makedirs("data/temp", exist_ok=True)
    with open(pdf_path, 'wb') as f:
        f.write(pdf_bytes)

    total_pages = pdf_processor.get_page_count(pdf_path)
    if ep is None: ep = total_pages
    ep = min(ep, total_pages)
    total = ep - sp + 1

    dash_data['pg'] = f"0/{total}"
    dash_data['target_pages'] = f"{sp}-{ep} ({total} pages) | {cnt_per_page} MCQ/page"
    dash_data['status'] = '📄 Converting...'
    await update_dashboard(dash_msg, dash_data)

    images = await pdf_processor.pdf_to_images(pdf_path, sp, ep)

    if is_qbm and (not images or len(str(images[0][1])) < 100):
        dash_data['status'] = '🔍 OCR Scanning...'
        await update_dashboard(dash_msg, dash_data)
        ocr_images = []
        try:
            from pypdf import PdfReader
            reader = PdfReader(pdf_path)
            for pi in range(sp - 1, min(ep, len(reader.pages))):
                from pdf2image import convert_from_path
                pil_imgs = convert_from_path(pdf_path, first_page=pi + 1, last_page=pi + 1)
                if pil_imgs:
                    ocr_texts = []
                    for _ in range(3):
                        buf = io.BytesIO()
                        pil_imgs[0].save(buf, format='JPEG', quality=90)
                        ocr_texts.append(ocr_image(buf.getvalue()))
                    best = max(ocr_texts, key=len) if ocr_texts else ""
                    if best: ocr_images.append((pi + 1, best.encode('utf-8')))
        except:
            pass
        if ocr_images: images = ocr_images

    if not images:
        dash_data['status'] = '❌ No Content'
        await update_dashboard(dash_msg, dash_data)
        try: os.remove(pdf_path)
        except: pass
        return

    all_mcqs = []
    page_links = {}
    sent_count = 0

    # Active prompts
    if is_qbm:
        active_prompts = [QBM_EXTRACT_PROMPT]
    else:
        rows = await db.fetchall('SELECT content FROM prompts WHERE is_active = 1')
        if not rows:
            await msg_target.reply_text("❌ No Active Prompt!")
            return
        active_prompts = [r[0] for r in rows]
        # Add count instruction
        count_instruction = f"CRITICAL: You MUST generate EXACTLY {cnt_per_page} MCQs. Verify count. If you cannot, return []."
        active_prompts.append(count_instruction)
        # Add count instruction
        count_instruction = f"CRITICAL: You MUST generate EXACTLY {cnt_per_page} MCQs. Verify count. If you cannot, return []."
        active_prompts.append(count_instruction)

    for idx, (page_num, img_bytes) in enumerate(images):
        while GLOBAL_PAUSE.get(uid, False):
            dash_data['status'] = '⏸️ PAUSED'
            await update_dashboard(dash_msg, dash_data)
            await asyncio.sleep(1)

        page_mcqs = []
        for retry in range(3 if is_qbm else 2):
            try:
                img_data = img_bytes if isinstance(img_bytes, bytes) else img_bytes
                page_mcqs = await generate_mcqs_from_image(img_data, active_prompts, cnt_per_page)
                if page_mcqs and cnt_per_page > 0:
                    page_mcqs = page_mcqs[:cnt_per_page]
                if page_mcqs:
                    break
            except:
                await asyncio.sleep(2)

        if page_mcqs:
            # Trim to exact count
            for mcq_clean in page_mcqs:
                q_clean = mcq_clean.get('question', '')
                q_clean = re.sub(r'\s*[\[\(].*?[\]\)]\s*$', '', q_clean)
                q_clean = re.sub(r'^\s*[\d০-৯]+\s*[.)\-:\s]+\s*', '', q_clean)
                q_clean = re.sub(r'^\s*[Qq]\.?\s*[\d]+\s*[.)\-:\s]*\s*', '', q_clean)
                q_clean = re.sub(r'^\s*\(?\s*[\d০-৯]+\s*\)?\s*[.)\-:\s]*\s*', '', q_clean)
                mcq_clean['question'] = q_clean.strip()
            all_mcqs.extend(page_mcqs)

            dash_data['mcq'] = len(all_mcqs)
            dash_data['pg'] = f"{page_num}/{total}"
            dash_data['pct'] = int(page_num / total * 100)

            if channel_id:
                page_label = f"Page-{page_num:02d}"
                if mood == 'image':
                    caption = f"🎯Topic: {title}\n🌟{page_label}\n⚡Join: @MediAtlas\n🔗Visit: Atlascourses.com"
                    img_raw = img_bytes if isinstance(img_bytes, bytes) else img_bytes
                    img_msg = await context.bot.send_photo(
                        chat_id=channel_id,
                        photo=io.BytesIO(img_raw),
                        caption=caption
                    )
                    reply_to = img_msg.message_id
                else:
                    pre_text = f"🎯Topic: {title}\n🌟{page_label}\n⚡Join: @MediAtlas\n🔗Visit: Atlascourses.com"
                    pre_msg = await context.bot.send_message(chat_id=channel_id, text=pre_text)
                    reply_to = pre_msg.message_id

                first_pid, psent = None, 0
                for mcq in page_mcqs:
                    pid, ok = await send_poll_robust(context.bot, channel_id, mcq, reply_to, uid, with_source)
                    if ok:
                        if not first_pid: first_pid = pid
                        psent += 1
                        sent_count += 1
                        dash_data['sent'] = f"{sent_count}/{len(all_mcqs)}"
                    await update_dashboard(dash_msg, dash_data)
                    await asyncio.sleep(1)

                first_link = await get_message_link(context.bot, channel_id, first_pid) if first_pid else ""
                ending = get_ending_message(f"{title} ({page_label})", psent, first_link)
                await context.bot.send_message(
                    chat_id=channel_id, text=ending,
                    reply_to_message_id=reply_to, disable_web_page_preview=True
                )
                page_links[page_num] = first_link

        dash_data['time'] = f"{int(time.time() - start_time)}s"
        await update_dashboard(dash_msg, dash_data)

    try: os.remove(pdf_path)
    except: pass

    dash_data['status'] = '📊 CSV...'
    await update_dashboard(dash_msg, dash_data)

    csv_bytes = mcqs_to_csv(all_mcqs)
    await msg_target.reply_document(
        document=csv_bytes,
        filename=f"{title}.csv",
        caption=f"✅ {len(all_mcqs)} MCQ | {len(images)} pages"
    )

    if channel_id and len(page_links) > 1:
        summary = f"🟥পেইজভিত্তিক Important Poll Solve By ATLAS\n🌟Topic: {title}\n\n✅নিচে সিরিয়ালী সাজিয়ে দেওয়া হলো:\n\n"
        for pg, link in sorted(page_links.items()):
            summary += f"📍Page-{pg:02d}:\n{link}\n\n"
        await context.bot.send_message(chat_id=channel_id, text=summary, disable_web_page_preview=True)

    dash_data['status'] = '✅ COMPLETE!'
    dash_data['pct'] = 100
    await update_dashboard(dash_msg, dash_data)

    context.user_data['last_csv'] = csv_bytes
    context.user_data["last_mcqs"] = all_mcqs.copy()

    if not channel_id and all_mcqs:
        channels = await db.fetchall('SELECT channel_id, channel_name FROM channels')
        if channels:
            buttons = []
            for ch_id, ch_name in channels:
                buttons.append([InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"pdfm_send_{ch_id}")])
            buttons.append([InlineKeyboardButton("❌ Skip", callback_data="pdfm_skip")])
            await msg_target.reply_text("✅ CSV Ready!\n\nSend Polls to Channel?", reply_markup=InlineKeyboardMarkup(buttons))


async def handle_pdf_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith('pdfm_mood_') or data.startswith('qbm_mood_'):
        is_qbm = data.startswith('qbm')
        mood = data.split('_')[-1]
        if mood == 'cancel':
            await query.edit_message_text("❌ Cancelled!")
            return
        if is_qbm:
            context.chat_data['qbm_mood'] = mood
            buttons = [
                [InlineKeyboardButton("📝 With Source", callback_data="qbm_source_yes")],
                [InlineKeyboardButton("📝 Without Source", callback_data="qbm_source_no")],
            ]
            await query.edit_message_text(
                "📋 Source Option:\n\nWith Source = প্রশ্নে [BCS] tag সহ\nWithout Source = tag বাদে\n\nCSV সবসময় Without Source",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await query.edit_message_text("⏳ Processing...")
            await process_pdf(update, context, False, mood)

    elif data.startswith('qbm_source_'):
        context.chat_data['qbm_with_source'] = (data == 'qbm_source_yes')
        mood = context.chat_data.get('qbm_mood', 'topic')
        await query.edit_message_text("⏳ QBM Extracting...")
        await process_pdf(update, context, True, mood)

    elif data == 'qbm_skip' or data == 'pdfm_skip':
        await query.edit_message_text("✅ CSV saved! Poll skipped.")

    elif data.startswith('qbm_send_') or data.startswith('pdfm_send_'):
        channel_id = data.split('_send_')[1]
        context.chat_data['qbm_channel'] = channel_id
        mcqs = context.user_data.get('last_mcqs', [])
        topic = context.user_data.get('last_topic', 'MCQ')
        mood = context.chat_data.get('qbm_mood', 'topic')
        with_source = context.chat_data.get('qbm_with_source', False)
        if mcqs:
            await query.edit_message_text(f"📤 Sending {len(mcqs)} polls...")
            await send_polls_to_channel(update, context, channel_id, mcqs, topic, mood, None)
        else:
            await query.edit_message_text("❌ No MCQs!")

    elif data in ('pdfm_cancel', 'qbm_cancel'):
        await query.edit_message_text("❌ Cancelled!")


# ============================================================
# OCR BATCH PROCESSOR
# ============================================================
async def process_batch_ocr(ocr_images, batch_size=2):
    """Process OCR text in batches to save Gemini keys"""
    batches = []
    for i in range(0, len(ocr_images), batch_size):
        batch = ocr_images[i:i + batch_size]
        combined_text = "\n---\n".join([
            text.decode('utf-8') if isinstance(text, bytes) else text
            for _, text in batch
        ])
        batches.append(combined_text)
    return batches
