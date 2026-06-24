#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ATLAS BOT - Config, Database (Supabase), Key Managers"""

import os
import random
import base64
import requests
from dotenv import load_dotenv
from typing import Optional, List, Any
from supabase import create_client, Client

load_dotenv()


class Config:
    """Bot configuration"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    OWNER_ID = int(os.getenv('OWNER_ID', 0))
    GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    GEMINI_API_KEYS = os.getenv('GEMINI_API_KEYS', '').split(',')
    IMGBB_API_KEYS = os.getenv('IMGBB_API_KEYS', '').split(',')
    API_ID = os.getenv('TELEGRAM_API_ID')
    API_HASH = os.getenv('TELEGRAM_API_HASH')
    SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://wbdyjpjbczfunyhhmtry.supabase.co')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')
    TEMP_PATH = 'data/temp'
    THUMB_PATH = 'data/thumbnails'


class FakeRow(tuple):
    """Mimics sqlite3.Row — supports both index and key access"""
    def __new__(cls, data: dict):
        instance = super().__new__(cls, data.values())
        instance._data = data
        return instance

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._data[key]
        return super().__getitem__(key)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()


class FakeCursor:
    """Mimics aiosqlite cursor"""
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount
        self.lastrowid = None

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows


class Database:
    """Supabase database manager — same API as aiosqlite"""

    def __init__(self):
        os.makedirs('data', exist_ok=True)
        os.makedirs(Config.TEMP_PATH, exist_ok=True)
        os.makedirs(Config.THUMB_PATH, exist_ok=True)
        self._client: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)

    async def initialize(self):
        """No-op — tables already exist in Supabase"""
        await self._insert_default_exp()
        await self._insert_default_sheet_formats()

    async def _insert_default_exp(self):
        try:
            res = self._client.table('exp_settings').select('id').eq('id', 1).execute()
            if not res.data:
                self._client.table('exp_settings').insert({'id': 1, 'mode': 'auto', 'custom_text': '', 'tag_name': ''}).execute()
        except:
            pass

    async def _insert_default_sheet_formats(self):
        formats = [
            ('format_01', 'Practice Sheet (প্রশ্ন + উত্তর + ব্যাখ্যা)'),
            ('format_02', 'Solve Sheet (সাইডবারে উত্তর)'),
            ('format_03', 'Exam Style (Answer টেবিল)'),
            ('format_04', 'Mixed Style'),
            ('format_05', 'Summary + Answer Key'),
        ]
        try:
            existing = self._client.table('sheet_formats').select('format_id').execute()
            existing_ids = {r['format_id'] for r in existing.data}
            for fid, fname in formats:
                if fid not in existing_ids:
                    self._client.table('sheet_formats').insert({'format_id': fid, 'format_name': fname, 'is_active': 1}).execute()
        except:
            pass

    def _parse_sql(self, query: str, params: tuple):
        """Parse SQL query to Supabase operations"""
        q = query.strip()
        ql = q.lower()

        # SELECT
        if ql.startswith('select'):
            return self._handle_select(q, params)
        # INSERT
        elif ql.startswith('insert'):
            return self._handle_insert(q, params)
        # UPDATE
        elif ql.startswith('update'):
            return self._handle_update(q, params)
        # DELETE
        elif ql.startswith('delete'):
            return self._handle_delete(q, params)
        # CREATE TABLE / pragma — ignore
        elif ql.startswith('create') or ql.startswith('pragma'):
            return FakeCursor()
        else:
            return FakeCursor()

    def _extract_table(self, query: str) -> str:
        """Extract table name from SQL"""
        import re
        ql = query.lower()
        if 'from' in ql:
            m = re.search(r'from\s+(\w+)', ql)
        elif 'into' in ql:
            m = re.search(r'into\s+(\w+)', ql)
        elif 'update' in ql:
            m = re.search(r'update\s+(\w+)', ql)
        elif 'delete from' in ql:
            m = re.search(r'delete\s+from\s+(\w+)', ql)
        else:
            m = None
        return m.group(1) if m else ''

    def _handle_select(self, query: str, params: tuple) -> FakeCursor:
        import re
        table = self._extract_table(query)
        if not table:
            return FakeCursor()

        # Extract columns
        col_match = re.search(r'select\s+(.*?)\s+from', query, re.IGNORECASE | re.DOTALL)
        columns = col_match.group(1).strip() if col_match else '*'

        try:
            req = self._client.table(table).select(columns)

            # WHERE conditions
            where_match = re.search(r'where\s+(.*?)(?:order|limit|$)', query, re.IGNORECASE | re.DOTALL)
            if where_match and params:
                where_str = where_match.group(1).strip()
                conditions = re.findall(r'(\w+)\s*=\s*\?', where_str)
                for i, col in enumerate(conditions):
                    if i < len(params):
                        val = params[i]
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            pass
                        req = req.eq(col, val)
            # ORDER BY
            order_match = re.search(r'order\s+by\s+(\w+)(?:\s+(asc|desc))?', query, re.IGNORECASE)
            if order_match:
                col = order_match.group(1)
                desc = order_match.group(2) and order_match.group(2).lower() == 'desc'
                req = req.order(col, desc=desc)

            # LIMIT
            limit_match = re.search(r'limit\s+(\d+)', query, re.IGNORECASE)
            if limit_match:
                req = req.limit(int(limit_match.group(1)))

            res = req.execute()
            rows = [FakeRow(r) for r in res.data] if res.data else []
            return FakeCursor(rows)
        except Exception as e:
            return FakeCursor()

    def _handle_insert(self, query: str, params: tuple) -> FakeCursor:
        import re
        table = self._extract_table(query)
        if not table:
            return FakeCursor()

        try:
            col_match = re.search(r'\(([^)]+)\)\s+values', query, re.IGNORECASE)
            if not col_match:
                return FakeCursor()
            cols = [c.strip() for c in col_match.group(1).split(',')]
            data = dict(zip(cols, params))

            ignore = 'or ignore' in query.lower() or 'on conflict' in query.lower()
            if ignore:
                self._client.table(table).upsert(data).execute()
            else:
                self._client.table(table).insert(data).execute()

            cur = FakeCursor()
            cur.lastrowid = 0
            return cur
        except Exception as e:
            return FakeCursor()

    def _handle_update(self, query: str, params: tuple) -> FakeCursor:
        import re
        table = self._extract_table(query)
        if not table:
            return FakeCursor()

        try:
            set_match = re.search(r'set\s+(.*?)\s+where', query, re.IGNORECASE | re.DOTALL)
            where_match = re.search(r'where\s+(.*?)$', query, re.IGNORECASE | re.DOTALL)

            if not set_match:
                return FakeCursor()

            # Parse SET columns — only pick cols with ? (ignore CURRENT_TIMESTAMP etc)
            set_str = set_match.group(1)
            set_cols = []
            for part in set_str.split(','):
                part = part.strip()
                if '= ?' in part or '=?' in part:
                    col = part.split('=')[0].strip()
                    set_cols.append(col)

            where_cols = re.findall(r'(\w+)\s*=\s*\?', where_match.group(1)) if where_match else []

            set_params = params[:len(set_cols)]
            where_params = params[len(set_cols):]

            data = dict(zip(set_cols, set_params))

            # Handle CURRENT_TIMESTAMP
            if 'updated_at' in set_str and 'CURRENT_TIMESTAMP' in set_str:
                from datetime import datetime
                data['updated_at'] = datetime.utcnow().isoformat()

            req = self._client.table(table).update(data)

            for i, col in enumerate(where_cols):
                if i < len(where_params):
                    val = where_params[i]
                    try:
                        val = int(val)
                    except (ValueError, TypeError):
                        pass
                    req = req.eq(col, val)
            req.execute()
            return FakeCursor()
        except Exception as e:
            return FakeCursor()

    def _handle_delete(self, query: str, params: tuple) -> FakeCursor:
        import re
        table = self._extract_table(query)
        if not table:
            return FakeCursor()
        try:
            where_match = re.search(r'where\s+(.*?)$', query, re.IGNORECASE | re.DOTALL)
            req = self._client.table(table).delete()
            if where_match and params:
                where_cols = re.findall(r'(\w+)\s*=\s*\?', where_match.group(1))
                for i, col in enumerate(where_cols):
                    if i < len(params):
                        val = params[i]
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            pass
                        req = req.eq(col, val)
            else:
                req = req.neq('id', -999999)
            req.execute()
            return FakeCursor()
        except Exception as e:
            return FakeCursor()
    async def execute(self, query: str, params: tuple = ()) -> Any:
        """Execute query — returns cursor-like object"""
        return self._parse_sql(query, params)

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[FakeRow]:
        """Fetch one result"""
        cursor = self._parse_sql(query, params)
        return await cursor.fetchone()

    async def fetchall(self, query: str, params: tuple = ()) -> List[FakeRow]:
        """Fetch all results"""
        cursor = self._parse_sql(query, params)
        return await cursor.fetchall()

    async def commit(self):
        """No-op — Supabase auto-commits"""
        pass

    async def close(self):
        """No-op"""
        pass


class GeminiKeyManager:
    """Gemini API key rotation manager"""

    def __init__(self):
        raw = os.getenv('GEMINI_API_KEYS', '')
        self.keys = {
            k.strip(): {'success': 0, 'fail': 0, 'healthy': True}
            for k in raw.replace('\n', ',').split(',') if k.strip()
        }

    def get_healthy_key(self) -> str:
        healthy = [k for k, v in self.keys.items() if v['healthy']]
        if not healthy:
            for k in self.keys:
                self.keys[k]['healthy'] = True
            healthy = list(self.keys.keys())
        return random.choice(healthy)

    def record_success(self, key: str):
        if key in self.keys:
            self.keys[key]['success'] += 1
            self.keys[key]['healthy'] = True

    def record_failure(self, key: str):
        if key in self.keys:
            self.keys[key]['fail'] += 1
            if self.keys[key]['fail'] >= 3:
                self.keys[key]['healthy'] = False

    async def call(self, prompt: str, image=None, retries: int = 3) -> str:
        from google import genai
        for attempt in range(retries):
            key = self.get_healthy_key()
            try:
                client = genai.Client(api_key=key)
                contents = [image, prompt] if image else [prompt]
                resp = client.models.generate_content(
                    model=Config.GEMINI_MODEL,
                    contents=contents
                )
                self.record_success(key)
                return resp.text
            except Exception as e:
                self.record_failure(key)
                if attempt == retries - 1:
                    raise e
        return ""

    def get_stats(self):
        healthy = len([k for k, v in self.keys.items() if v.get('healthy')])
        return {'total': len(self.keys), 'healthy': healthy}


class ImgBBKeyManager:
    """ImgBB API key rotation manager"""

    def __init__(self):
        raw = os.getenv('IMGBB_API_KEYS', '')
        self.keys = [k.strip() for k in raw.split(',') if k.strip()]
        self.index = 0

    def upload(self, image_bytes: bytes, retries: int = 3) -> str:
        b64 = base64.b64encode(image_bytes).decode('utf-8')
        for attempt in range(retries):
            key = self.keys[self.index % len(self.keys)]
            self.index += 1
            try:
                resp = requests.post(
                    'https://api.imgbb.com/1/upload',
                    data={'key': key, 'image': b64},
                    timeout=30
                )
                data = resp.json()
                if data.get('success'):
                    return data['data']['url']
            except Exception:
                if attempt == retries - 1:
                    raise
        return ""


# Global instances
gemini_manager = GeminiKeyManager()
imgbb_manager = ImgBBKeyManager()
db = Database()

async def check_permitted(user_id: int) -> bool:
    """Check if user is owner or permitted admin"""
    if user_id == Config.OWNER_ID:
        return True
    try:
        r = db._client.table('admins').select('user_id').eq('user_id', int(user_id)).execute()
        return bool(r.data)
    except:
        return False
