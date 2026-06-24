#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ATLAS BOT - MHTML/HTML Handler - IMPROVED v2"""

import os, re, pandas as pd, email, requests, base64, time, io, sys, gc, asyncio, urllib.parse, logging
from bs4 import BeautifulSoup
from datetime import datetime
from email import policy
from PIL import Image
from telegram import Update
from telegram.ext import ContextTypes
from config import db, imgbb_manager

logger = logging.getLogger(__name__)

# ============================================================
# QUEUE SYSTEM
# ============================================================
mhtml_queue = asyncio.Queue()
processing_queue = asyncio.Queue()
is_processing = False

# ============================================================
# IMGBB UPLOAD (using bot's imgbb_manager)
# ============================================================
def compress_image(b64_str):
    try:
        img_data = base64.b64decode(b64_str)
        img = Image.open(io.BytesIO(img_data))
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        out_buffer = io.BytesIO()
        img.save(out_buffer, format="JPEG", optimize=True, quality=70)
        return base64.b64encode(out_buffer.getvalue()).decode('utf-8')
    except: return b64_str

def upload_to_imgbb(b64):
    if not b64: return ""
    try:
        compressed = compress_image(b64)
        return imgbb_manager.upload(base64.b64decode(compressed))
    except: return ""

# ============================================================
# UNICODE MAPS
# ============================================================
SUB_MAP = str.maketrans("0123456789+-=()aeoxhklmnpst", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ")
SUP_MAP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻₌⁽⁾ⁿ")
SUP_TO_NORMAL = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

# LaTeX → Unicode symbols
LATEX_SYMBOLS = {
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\epsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η', r'\theta': 'θ',
    r'\iota': 'ι', r'\kappa': 'κ', r'\lambda': 'λ', r'\mu': 'μ',
    r'\nu': 'ν', r'\xi': 'ξ', r'\pi': 'π', r'\rho': 'ρ',
    r'\sigma': 'σ', r'\tau': 'τ', r'\phi': 'φ', r'\chi': 'χ',
    r'\psi': 'ψ', r'\omega': 'ω', r'\Gamma': 'Γ', r'\Delta': 'Δ',
    r'\Theta': 'Θ', r'\Lambda': 'Λ', r'\Pi': 'Π', r'\Sigma': 'Σ',
    r'\Phi': 'Φ', r'\Psi': 'Ψ', r'\Omega': 'Ω',
    r'\infty': '∞', r'\times': '×', r'\div': '÷', r'\pm': '±',
    r'\mp': '∓', r'\leq': '≤', r'\geq': '≥', r'\neq': '≠',
    r'\approx': '≈', r'\equiv': '≡', r'\propto': '∝',
    r'\sqrt': '√', r'\int': '∫', r'\oint': '∮', r'\iint': '∬',
    r'\sum': '∑', r'\prod': '∏', r'\partial': '∂', r'\nabla': '∇',
    r'\rightarrow': '→', r'\leftarrow': '←', r'\leftrightarrow': '↔',
    r'\Rightarrow': '⇒', r'\Leftarrow': '⇐', r'\Leftrightarrow': '⇔',
    r'\uparrow': '↑', r'\downarrow': '↓',
    r'\sin': 'sin', r'\cos': 'cos', r'\tan': 'tan',
    r'\cot': 'cot', r'\sec': 'sec', r'\csc': 'csc',
    r'\log': 'log', r'\ln': 'ln', r'\lim': 'lim',
    r'\cdot': '·', r'\bullet': '•', r'\circ': '°',
    r'\therefore': '∴', r'\because': '∵',
    r'\in': '∈', r'\notin': '∉', r'\subset': '⊂', r'\supset': '⊃',
    r'\cup': '∪', r'\cap': '∩', r'\emptyset': '∅',
    r'\forall': '∀', r'\exists': '∃',
}

def convert_to_english_numbers(text):
    return text.translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789"))

def aggressive_clean(text):
    if not text: return ""
    text = convert_to_english_numbers(text)

    # Fractions
    text = re.sub(r'\\frac\s*\{([^}]+)\}\s*\{([^}]+)\}', r'\1/\2', text)
    text = re.sub(r'\\frac\s*(\S+)\s*(\S+)', r'\1/\2', text)

    # LaTeX symbols → unicode
    for latex, uni in LATEX_SYMBOLS.items():
        text = text.replace(latex, uni)

    # Subscript/superscript with braces
    text = re.sub(r'_\{\s*([^}]+)\s*\}', lambda m: m.group(1).translate(SUB_MAP), text)
    text = re.sub(r'\^\{\s*([^}]+)\s*\}', lambda m: m.group(1).translate(SUP_MAP), text)

    # Subscript/superscript without braces
    text = re.sub(r'_([0-9a-zA-Z+\-]+)', lambda m: m.group(1).translate(SUB_MAP), text)
    text = re.sub(r'\^([0-9a-zA-Z+\-]+)', lambda m: m.group(1).translate(SUP_MAP), text)

    # Degree fix
    text = re.sub(r'([⁰¹²³⁴⁵⁶⁷⁸⁹]+)°', lambda m: m.group(1).translate(SUP_TO_NORMAL) + '°', text)
    text = text.replace('^\\circ', '°').replace('^{\\circ}', '°').replace('∘', '°')
    text = text.replace('° C', '°C').replace('^ C', '°C')

    # Sub char cleanup: NaHCO₃ fix
    text = text.translate(str.maketrans("ₐₑₒₓₕₖₗₘₙₚₛₜ", "aeoxhklmnpst"))

    # Spacing fixes
    text = re.sub(r'\s+([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎]+)', r'\1', text)
    text = text.replace('₍', '(').replace('₎', ')')
    text = re.sub(r'(?<=[A-Za-z])\s+(?=[a-z](?:\s|$|[^a-zA-Z]))', '', text)
    text = re.sub(r'(?<=\d)\s+(?=[A-Z])', '', text)
    text = re.sub(r'(?<=[A-Z])\s+(?=[A-Z])', '', text)
    text = re.sub(r'(?<=[A-Z])\s+(?=[a-z](?:\s|$|[^a-zA-Z]))', '', text)
    text = re.sub(r'(?<=[A-Z][a-z])\s+(?=[A-Z])', '', text)
    text = re.sub(r'(?<=[₀-₉⁰-⁹])\s+(?=[A-Z])', '', text)
    text = text.replace(' . ', '.').replace(' .', '.').replace('. ', '.')

    # Remove remaining LaTeX
    text = re.sub(r'\\[a-zA-Z]+\s*\{?', ' ', text)
    text = re.sub(r'([A-Z][a-z]?)\s+([₀-₉⁰-⁹⁺⁻])', r'\1\2', text)

    # Units spacing
    units = r'(mL|L|m³|cm³|g|kg|mol|M|Pa|atm|J|K|V|A|W|N|C|Hz|eV|nm|mm|cm|m)'
    text = re.sub(r'(\d+)\s*' + units + r'\b', r'\1 \2', text)

    text = re.sub(r'[\{\}]', '', text)

    # Clean zero-width chars
    text = text.replace('\ufeff', '').replace('\u200b', '').replace('\u200c', '')

    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def format_content(element, img_map):
    if not element: return ""

    for hidden in element.find_all(['annotation', 'script', 'mjx-assistive-mathml']):
        hidden.decompose()
    for hidden in element.find_all('span', class_=['katex-html', 'MJX_Assistive_MathML', 'MathJax_Preview']):
        hidden.decompose()

    for mfrac in element.find_all('mfrac'):
        contents = mfrac.find_all(recursive=False)
        if len(contents) == 2:
            num = contents[0].get_text(strip=True)
            den = contents[1].get_text(strip=True)
            mfrac.replace_with(f"{num}/{den}")

    for sub in element.find_all(['sub', 'msub']):
        sub.replace_with(sub.get_text(strip=True).translate(SUB_MAP))
    for sup in element.find_all(['sup', 'msup']):
        sup.replace_with(sup.get_text(strip=True).translate(SUP_MAP))

    for img in element.find_all('img'):
        src = img.get('src', '') or img.get('data-src', '')
        if not src:
            img.decompose()
            continue

        url = ""
        b64 = ""
        if src.startswith('http'):
            url = src
        elif src.startswith('data:image'):
            try:
                if 'base64,' in src:
                    b64 = src.split('base64,')[1]
            except: pass
        else:
            decoded_src = urllib.parse.unquote(src)
            b64 = img_map.get(src) or img_map.get(decoded_src) or ""

        if b64 and not url:
            url = upload_to_imgbb(b64)

        if url:
            img.replace_with(f" img_s{url}img_e ")
        else:
            img.decompose()

    raw_text = element.get_text(separator=" ", strip=True)
    img_markers = []

    def img_repl(match):
        img_markers.append(match.group(0))
        return f" ZZZIMG{len(img_markers)-1}ZZZ "

    raw_text = re.sub(r'img_s.*?img_e', img_repl, raw_text)
    cleaned_text = aggressive_clean(raw_text)

    for i, marker in enumerate(img_markers):
        cleaned_text = cleaned_text.replace(f"ZZZIMG{i}ZZZ", marker)

    return re.sub(r'img_s(.*?)img_e', r'<img class="qimg" src="\1">', cleaned_text)


# ============================================================
# POST PROCESSING: Remove empty + duplicates
# ============================================================
def post_process(results: list) -> list:
    # Remove empty questions
    results = [r for r in results if r.get('questions', '').strip()]
    # Remove duplicates
    seen = set()
    unique = []
    for r in results:
        key = r.get('questions', '').strip()[:120]
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ============================================================
# PREMIUM DASHBOARD
# ============================================================
async def update_dashboard(msg, data: dict):
    pct = data.get('pct', 0)
    bar_len = 20
    filled = int(bar_len * pct / 100)
    bar = '█' * filled + '░' * (bar_len - filled)
    status = data.get('status', '⏳')
    elapsed = data.get('elapsed', '')
    eta = data.get('eta', '')
    dashboard = f"""╔══════════════════════════════════╗
║    📊 ATLAS MHTML PROCESSOR     ║
╠══════════════════════════════════╣
║ 📁 {data.get('file','N/A')[:30]:<30} ║
║ 🌐 {data.get('source','Unknown'):<32} ║
╠══════════════════════════════════╣
║ 📝 MCQ: {str(data.get('mcq',0)) + '/' + str(data.get('total',0)):<26} ║
║ ⏱️  Time: {elapsed:<27} ║
║ ⏳ ETA:  {eta:<27} ║
║ [{bar}] {pct}%{'':<10} ║
║ {status:<32} ║
╚══════════════════════════════════╝"""
    try:
        await msg.edit_text(f"```{dashboard}```", parse_mode='Markdown')
    except:
        try: await msg.edit_text(dashboard)
        except: pass


# ============================================================
# PROCESS FILE
# ============================================================
async def process_file(message, file_path, file_name):
    status_msg = await message.reply_text("🔍 Parsing file structure...")
    img_map, html_body = {}, ""

    with open(file_path, 'rb') as f:
        file_bytes = f.read()

    if file_name.endswith(('.mhtml', '.mht')):
        try:
            msg = email.message_from_bytes(file_bytes, policy=policy.default)
            for part in msg.walk():
                if part.get_content_type() == 'text/html':
                    html_body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or 'utf-8', errors='ignore')
                elif part.get_content_type().startswith('image/'):
                    loc, raw = part.get('Content-Location', ''), part.get_payload(decode=True)
                    if loc and raw:
                        b64_data = base64.b64encode(raw).decode('utf-8')
                        img_map[loc] = b64_data
                        img_map[urllib.parse.unquote(loc)] = b64_data
        except Exception as e:
            await status_msg.edit_text(f"❌ MHTML Parse Error: {e}")
            return
    else:
        html_body = file_bytes.decode('utf-8', errors='ignore')

    soup = BeautifulSoup(html_body, 'html.parser')

    # ============================================================
    # CHORCHA.NET
    # ============================================================
    chorcha_cards = soup.find_all('div', class_=lambda x: x and 'p-5' in x and 'rounded-xl' in x)

    if chorcha_cards:
        total_mcq = len(chorcha_cards)
        results = []
        start_time, last_ui = time.time(), time.time()
        ans_map = {'ক': '1', 'খ': '2', 'গ': '3', 'ঘ': '4'}

        dash_data = {'file': file_name[:30], 'source': 'Chorcha.net',
                     'mcq': 0, 'total': total_mcq, 'elapsed': '0s', 'eta': '...', 'pct': 0, 'status': '📝 Processing...'}
        await update_dashboard(status_msg, dash_data)

        for idx, card in enumerate(chorcha_cards, 1):
            q_div = card.find('div', class_=lambda x: x and 'font-medium' in x)
            if not q_div: continue
            q_text = re.sub(r'^\s*[0-9০-৯]+\s*[\.\)\-ঃ:]\s*', '', format_content(q_div, img_map))
            if not q_text.strip(): continue

            options, ans_idx = [], "1"
            for i, btn in enumerate(card.find_all('button', class_=lambda x: x and 'p-2' in x), 1):
                lbl = btn.find('span', class_=lambda x: x and 'rounded-full' in x)
                opt_content = btn.find('div', class_='flex-1')
                if opt_content:
                    options.append(format_content(opt_content, img_map))
                    if any(c in str(btn) for c in ['#017A47', 'border-[#017A47]', '#E2A03F', '#F59E0B', 'border-[#F59E0B]']):
                        ans_idx = ans_map.get(lbl.get_text(strip=True) if lbl else "", str(i))

            while len(options) < 5: options.append("")
            if options[4].strip() and ans_idx == "5": options[3], ans_idx = options[4], "4"

            exp_div = card.find('div', class_=lambda x: x and 'prose' in x)
            exp_text = format_content(exp_div, img_map) if exp_div else ""

            results.append({"questions": q_text, "option1": options[0], "option2": options[1],
                             "option3": options[2], "option4": options[3], "option5": "",
                             "answer": ans_idx, "explanation": exp_text, "type": 1, "section": 1})

            if idx % 10 == 0 or idx == total_mcq:
                now = time.time()
                if now - last_ui > 5:
                    elapsed = now - start_time
                    eta = (elapsed / idx) * (total_mcq - idx) if idx > 0 else 0
                    dash_data.update({
                        'mcq': len(results), 'pct': int(idx / total_mcq * 100),
                        'elapsed': f"{int(elapsed)}s",
                        'eta': f"{int(eta//60):02d}:{int(eta%60):02d}",
                        'status': f'📝 {idx}/{total_mcq}'
                    })
                    await update_dashboard(status_msg, dash_data)
                    last_ui = now

        results = post_process(results)
        df = pd.DataFrame(results)
        csv_buf = io.BytesIO()
        df.to_csv(csv_buf, index=False, encoding='utf-8-sig')
        csv_buf.seek(0)
        csv_buf.name = f"ATLAS_Chorcha_{file_name}.csv"

        dash_data.update({'mcq': len(results), 'pct': 100, 'status': '✅ COMPLETE!'})
        await update_dashboard(status_msg, dash_data)
        await message.reply_document(document=csv_buf,
                                     caption=f"✅ Done: `{file_name}`\n📊 Total MCQ: {len(results)}")
        await status_msg.delete()
        gc.collect()
        return

    # ============================================================
    # TESTMOZ
    # ============================================================
    cards = soup.find_all('div', class_=lambda x: x and 'rounded-lg' in x and 'shadow-md' in x)
    total_mcq = len(cards)
    results = []
    start_time, last_ui = time.time(), time.time()

    dash_data = {'file': file_name[:30], 'source': 'Testmoz',
                 'mcq': 0, 'total': total_mcq, 'elapsed': '0s', 'eta': '...', 'pct': 0, 'status': '📝 Processing...'}
    await update_dashboard(status_msg, dash_data)

    for idx, card in enumerate(cards, 1):
        q_p = card.find('p', class_='text-[17px]')
        q_text = re.sub(r'^\s*[0-9০-৯]+\s*[\.\)\-ঃ:]\s*', '',
                        format_content(q_p, img_map)) if q_p else ""
        if not q_text.strip(): continue

        opt_divs = card.find_all('div', class_=lambda x: x and 'cursor-pointer' in x and 'col-span-2' in x)
        exp_div = card.find('div', class_=lambda x: x and 'col-span-2' in x
                             and 'font-semibold' in x and 'cursor-pointer' not in x)

        for img in card.find_all('img'):
            if q_p and img in q_p.descendants: continue
            in_opt = any(img in opt.descendants for opt in opt_divs)
            in_exp = exp_div and img in exp_div.descendants
            if not in_opt and not in_exp:
                dummy = BeautifulSoup(str(img), 'html.parser')
                q_text += " " + format_content(dummy, img_map)

        options, ans_idx = [], "1"
        for i, opt in enumerate(opt_divs, 1):
            text_sm = opt.find('div', class_='text-sm')
            opt_text = format_content(text_sm, img_map) if text_sm else ""
            for img in opt.find_all('img'):
                if text_sm and img not in text_sm.descendants:
                    dummy = BeautifulSoup(str(img), 'html.parser')
                    opt_text += " " + format_content(dummy, img_map)
            options.append(opt_text)
            if opt.find('div', class_=lambda x: x and 'bg-green-500' in x) or opt.find('svg'):
                ans_idx = str(i)

        while len(options) < 5: options.append("")
        if options[4].strip() and ans_idx == "5": options[3], ans_idx = options[4], "4"

        exp_text = format_content(exp_div, img_map) if exp_div else ""
        results.append({"questions": q_text, "option1": options[0], "option2": options[1],
                         "option3": options[2], "option4": options[3], "option5": "",
                         "answer": ans_idx, "explanation": exp_text, "type": 1, "section": 1})

        if idx % 10 == 0 or idx == total_mcq:
            now = time.time()
            if now - last_ui > 5:
                elapsed = now - start_time
                eta = (elapsed / idx) * (total_mcq - idx) if idx > 0 else 0
                dash_data.update({
                    'mcq': len(results), 'pct': int(idx / total_mcq * 100),
                    'elapsed': f"{int(elapsed)}s",
                    'eta': f"{int(eta//60):02d}:{int(eta%60):02d}",
                    'status': f'📝 {idx}/{total_mcq}'
                })
                await update_dashboard(status_msg, dash_data)
                last_ui = now

    results = post_process(results)
    df = pd.DataFrame(results)
    csv_buf = io.BytesIO()
    df.to_csv(csv_buf, index=False, encoding='utf-8-sig')
    csv_buf.seek(0)
    csv_buf.name = f"ATLAS_{file_name}.csv"

    dash_data.update({'mcq': len(results), 'pct': 100, 'status': '✅ COMPLETE!'})
    await update_dashboard(status_msg, dash_data)
    await message.reply_document(document=csv_buf,
                                 caption=f"✅ Done: `{file_name}`\n📊 Total MCQ: {len(results)}")
    await status_msg.delete()
    gc.collect()


# ============================================================
# WORKER SYSTEM (Queue)
# ============================================================
async def mhtml_worker():
    while True:
        try:
            update, context = await mhtml_queue.get()
            doc = update.message.document
            # Download file
            status = await update.message.reply_text(f"📥 Downloading `{doc.file_name}`...")
            file = await context.bot.get_file(doc.file_id)
            file_bytes = await file.download_as_bytearray()
            await status.delete()

            # Save temp
            tmp_path = f"/app/data/temp/mhtml_{int(time.time())}_{doc.file_name}"
            os.makedirs("/app/data/temp", exist_ok=True)
            with open(tmp_path, 'wb') as f:
                f.write(file_bytes)

            await process_file(update.message, tmp_path, doc.file_name)

            if os.path.exists(tmp_path):
                os.remove(tmp_path)

            mhtml_queue.task_done()
        except Exception as e:
            logger.error(f"MHTML worker error: {e}")
            mhtml_queue.task_done()


async def queue_mhtml(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📥 File added to queue...")
    await mhtml_queue.put((update, context))


async def mhtml_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await queue_mhtml(update, context)


def parse_mhtml_old_to_parts(file_bytes: bytes, filename: str):
    """Legacy compat function"""
    img_map = {}
    html_body = ""
    if filename.endswith(('.mhtml', '.mht')):
        try:
            msg = email.message_from_bytes(file_bytes, policy=policy.default)
            for part in msg.walk():
                if part.get_content_type() == 'text/html':
                    html_body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or 'utf-8', errors='ignore')
                elif part.get_content_type().startswith('image/'):
                    loc = part.get('Content-Location', '')
                    raw = part.get_payload(decode=True)
                    if loc and raw:
                        b64_data = base64.b64encode(raw).decode('utf-8')
                        img_map[loc] = b64_data
                        img_map[urllib.parse.unquote(loc)] = b64_data
        except Exception as e:
            logger.error(f"Parse error: {e}")
    else:
        html_body = file_bytes.decode('utf-8', errors='ignore')
    return html_body, img_map