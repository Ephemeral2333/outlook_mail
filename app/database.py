import sqlite3
import base64
import hashlib
import secrets
import time
from cryptography.fernet import Fernet
import os
import config

def _make_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)

class Database:
    def __init__(self):
        os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
        self.conn = sqlite3.connect(config.DATABASE_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cipher = Fernet(_make_fernet_key(config.ENCRYPTION_KEY))
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS mailboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                client_id TEXT NOT NULL,
                refresh_token_encrypted TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(email, client_id)
            );

            CREATE TABLE IF NOT EXISTS access_tokens (
                token TEXT PRIMARY KEY,
                mailbox_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY(mailbox_id) REFERENCES mailboxes(id)
            );

            CREATE INDEX IF NOT EXISTS idx_access_tokens_expires
                ON access_tokens(expires_at);
        ''')
        self.conn.commit()

    # ── 邮箱 ────────────────────────────────────────────────

    def add_mailbox(self, email, client_id, refresh_token):
        encrypted = self.cipher.encrypt(refresh_token.encode()).decode()
        self.conn.execute('''
            INSERT OR REPLACE INTO mailboxes (email, client_id, refresh_token_encrypted)
            VALUES (?, ?, ?)
        ''', (email.strip().lower(), client_id.strip(), encrypted))
        self.conn.commit()
        return self.conn.execute(
            'SELECT * FROM mailboxes WHERE email=? AND client_id=?',
            (email.strip().lower(), client_id.strip())
        ).fetchone()

    def get_mailbox_by_id(self, mailbox_id):
        return self.conn.execute(
            'SELECT * FROM mailboxes WHERE id=?', (mailbox_id,)
        ).fetchone()

    def find_by_email(self, email):
        return self.conn.execute(
            'SELECT * FROM mailboxes WHERE email=?', (email.strip().lower(),)
        ).fetchall()

    def list_all(self):
        return self.conn.execute(
            'SELECT * FROM mailboxes ORDER BY id ASC'
        ).fetchall()

    def decrypt_token(self, encrypted):
        return self.cipher.decrypt(encrypted.encode()).decode()

    # ── 访问 token ──────────────────────────────────────────

    def create_access_token(self, mailbox_id: int, ttl_seconds: int = 3600) -> str:
        """生成随机访问 token，默认 1 小时有效"""
        self._purge_expired_tokens()
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + ttl_seconds
        self.conn.execute(
            'INSERT INTO access_tokens (token, mailbox_id, expires_at) VALUES (?, ?, ?)',
            (token, mailbox_id, expires_at)
        )
        self.conn.commit()
        return token

    def verify_access_token(self, token: str):
        """验证 token，返回对应 mailbox，失败返回 None"""
        row = self.conn.execute(
            'SELECT mailbox_id, expires_at FROM access_tokens WHERE token=?', (token,)
        ).fetchone()

        if not row:
            return None
        if int(time.time()) > row['expires_at']:
            self.conn.execute('DELETE FROM access_tokens WHERE token=?', (token,))
            self.conn.commit()
            return None

        return self.get_mailbox_by_id(row['mailbox_id'])

    def _purge_expired_tokens(self):
        """清理过期 token"""
        self.conn.execute(
            'DELETE FROM access_tokens WHERE expires_at < ?', (int(time.time()),)
        )
        self.conn.commit()
