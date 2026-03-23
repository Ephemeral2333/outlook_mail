import re
import threading
from flask import Flask, request, jsonify, send_from_directory
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import config
from database import Database
from outlook_service import get_access_token, fetch_emails, fetch_email_detail

app = Flask(__name__, static_folder='../public', static_url_path='')
db = Database()

# ── 工具函数 ──────────────────────────────────────────────

def extract_email(text):
    match = re.search(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}', text, re.IGNORECASE)
    return match.group(0).lower() if match else None

def extract_id(text):
    match = re.match(r'^#(\d+)$', text.strip())
    return int(match.group(1)) if match else None

def parse_add_lines(text):
    records, failures = [], []
    for i, line in enumerate(text.strip().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = line.split('----')
        if len(parts) < 4:
            failures.append(f'第{i}行格式错误')
            continue
        email, password, client_id, refresh_token = parts[0], parts[1], parts[2], parts[3]
        if not email or not client_id or not refresh_token:
            failures.append(f'第{i}行缺少必要字段')
            continue
        records.append({'email': email, 'client_id': client_id, 'refresh_token': refresh_token})
    return records, failures

def verify_request_token():
    """验证请求中的 access token，返回 mailbox 或 None"""
    token = request.args.get('token') or request.headers.get('X-Access-Token')
    if not token:
        return None
    return db.verify_access_token(token)

def verify_admin_token():
    """验证管理员固定 token（用于 /import 页面）"""
    token = request.args.get('token')
    return token == config.ADMIN_TOKEN

# ── Flask 路由 ────────────────────────────────────────────

@app.route('/health')
def health():
    return jsonify({'ok': True})

@app.route('/mail')
def mail_page():
    mailbox = verify_request_token()
    if not mailbox:
        return '链接无效或已过期，请重新向 Bot 发送邮箱地址获取新链接。', 401
    return send_from_directory(app.static_folder, 'mail.html')

@app.route('/api/messages')
def get_messages():
    mailbox = verify_request_token()
    if not mailbox:
        return jsonify({'error': '链接无效或已过期，请重新获取'}), 401

    refresh_token = db.decrypt_token(mailbox['refresh_token_encrypted'])
    access_token = get_access_token(mailbox['client_id'], refresh_token)
    if not access_token:
        return jsonify({'error': 'Failed to refresh access token'}), 500

    messages = fetch_emails(mailbox['email'], access_token)
    return jsonify({'ok': True, 'mailboxEmail': mailbox['email'], 'messages': messages})

@app.route('/api/message/<email_id>')
def get_message_detail(email_id):
    mailbox = verify_request_token()
    if not mailbox:
        return jsonify({'error': '链接无效或已过期，请重新获取'}), 401

    refresh_token = db.decrypt_token(mailbox['refresh_token_encrypted'])
    access_token = get_access_token(mailbox['client_id'], refresh_token)
    if not access_token:
        return jsonify({'error': 'Failed to refresh access token'}), 500

    detail = fetch_email_detail(mailbox['email'], access_token, email_id)
    return jsonify({'ok': True, 'message': detail})

@app.route('/import')
def import_page():
    if not verify_admin_token():
        return '无效的管理员 Token', 401
    return send_from_directory(app.static_folder, 'import.html')

@app.route('/api/import', methods=['POST'])
def api_import():
    if not verify_admin_token():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    text = data.get('text', '')
    records, failures = parse_add_lines(text)
    for r in records:
        db.add_mailbox(r['email'], r['client_id'], r['refresh_token'])

    return jsonify({
        'ok': True,
        'imported': len(records),
        'failed': len(failures),
        'failures': failures
    })

# ── Telegram Bot ──────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in config.TELEGRAM_ALLOWED_USER_IDS:
        return

    text = update.message.text.strip()

    # /adds 返回导入页面链接
    if text.startswith('/adds'):
        url = f"{config.APP_BASE_URL}/import?token={config.ADMIN_TOKEN}"
        await update.message.reply_text(f'批量导入页面：\n\n{url}')
        return

    # /add 批量导入
    if text.startswith('/add'):
        payload = re.sub(r'^/add(@\S+)?', '', text).strip()
        if not payload:
            await update.message.reply_text(
                '请在 /add 后粘贴内容，每行格式：\n邮箱----密码----clientid----refresh_token'
            )
            return
        records, failures = parse_add_lines(payload)
        for r in records:
            db.add_mailbox(r['email'], r['client_id'], r['refresh_token'])
        msg = f'导入完成：成功 {len(records)} 条，失败 {len(failures)} 条。'
        if failures:
            msg += '\n' + '\n'.join(failures)
        await update.message.reply_text(msg)
        return

    # #编号
    mailbox_id = extract_id(text)
    if mailbox_id:
        mailbox = db.get_mailbox_by_id(mailbox_id)
        if mailbox:
            token = db.create_access_token(mailbox['id'], ttl_seconds=config.ACCESS_TOKEN_TTL)
            url = f"{config.APP_BASE_URL}/mail?token={token}"
            await update.message.reply_text(
                f"#{mailbox['id']} {mailbox['email']}\n链接有效期 {config.ACCESS_TOKEN_TTL // 60} 分钟\n\n{url}"
            )
        else:
            await update.message.reply_text(f'编号 #{mailbox_id} 不存在')
        return

    # 邮箱地址
    email = extract_email(text)
    if email:
        candidates = db.find_by_email(email)
        if len(candidates) == 1:
            m = candidates[0]
            token = db.create_access_token(m['id'], ttl_seconds=config.ACCESS_TOKEN_TTL)
            url = f"{config.APP_BASE_URL}/mail?token={token}"
            await update.message.reply_text(
                f"{m['email']} (#{m['id']})\n链接有效期 {config.ACCESS_TOKEN_TTL // 60} 分钟\n\n{url}"
            )
        elif len(candidates) > 1:
            lines = '\n'.join([f"#{m['id']}  {m['email']}" for m in candidates])
            await update.message.reply_text(f'找到多条记录，请发送编号：\n{lines}')
        else:
            await update.message.reply_text(f'邮箱 {email} 未导入，请先 /add 导入')
        return

    await update.message.reply_text('请发送邮箱地址、#编号，或用 /add 导入')

def start_bot():
    bot_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.TEXT, handle_message))
    bot_app.run_polling()

# ── 启动 ──────────────────────────────────────────────────

if __name__ == '__main__':
    threading.Thread(target=start_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=config.PORT, debug=False)
