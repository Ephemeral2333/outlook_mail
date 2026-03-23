import imaplib
import email
import chardet
from email.header import decode_header
import requests


def get_access_token(client_id, refresh_token):
    url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
    data = {
        'client_id': client_id,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        return response.json().get('access_token')
    return None


def generate_auth_string(user, token):
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


def _decode_str(value):
    """安全解码邮件头字段"""
    if value is None:
        return ''
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or 'utf-8', errors='replace'))
            except Exception:
                detected = chardet.detect(part)
                result.append(part.decode(detected.get('encoding') or 'utf-8', errors='replace'))
        else:
            result.append(part)
    return ''.join(result)


def _decode_payload(part):
    """安全解码邮件正文"""
    raw = part.get_payload(decode=True)
    if not raw:
        return ''
    charset = part.get_content_charset() or 'utf-8'
    try:
        return raw.decode(charset, errors='replace')
    except Exception:
        detected = chardet.detect(raw)
        return raw.decode(detected.get('encoding') or 'utf-8', errors='replace')


def _imap_connect(email_address, access_token):
    mail = imaplib.IMAP4_SSL('outlook.office365.com')
    auth_string = generate_auth_string(email_address, access_token)
    mail.authenticate('XOAUTH2', lambda x: auth_string)
    return mail


# 要拉取的文件夹列表，名称是 Outlook IMAP 的标准文件夹名
FETCH_FOLDERS = [
    ('INBOX',                '收件箱'),
    ('Junk',                 '垃圾邮件'),
    ('Junk Email',           '垃圾邮件'),   # 部分账号用这个名字
]

def _parse_message(raw_email, flags_raw, folder_name, email_id_str):
    """解析一封原始邮件，返回结构化数据"""
    is_read = '\\Seen' in flags_raw
    msg = email.message_from_bytes(raw_email)

    subject     = _decode_str(msg.get('Subject', ''))
    from_header = _decode_str(msg.get('From', 'Unknown'))
    to_header   = _decode_str(msg.get('To', ''))
    date_str    = msg.get('Date', '')

    # 解析时间用于排序
    from email.utils import parsedate_to_datetime
    try:
        date_dt = parsedate_to_datetime(date_str)
        date_ts = date_dt.timestamp()
    except Exception:
        date_ts = 0

    html_body   = ''
    text_body   = ''
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition  = str(part.get('Content-Disposition', ''))
            if 'attachment' in disposition:
                filename = _decode_str(part.get_filename() or '')
                attachments.append({
                    'filename': filename,
                    'contentType': content_type,
                    'size': len(part.get_payload(decode=True) or b'')
                })
            elif content_type == 'text/html' and not html_body:
                html_body = _decode_payload(part)
            elif content_type == 'text/plain' and not text_body:
                text_body = _decode_payload(part)
    else:
        if msg.get_content_type() == 'text/html':
            html_body = _decode_payload(msg)
        else:
            text_body = _decode_payload(msg)

    preview = (text_body or html_body)[:200].strip()

    return {
        'id': email_id_str,
        'folder': folder_name,
        'subject': subject or '(no subject)',
        'from': from_header,
        'to': to_header,
        'receivedAt': date_str,
        '_ts': date_ts,
        'isRead': is_read,
        'hasAttachments': len(attachments) > 0,
        'preview': preview,
        'htmlBody': html_body,
        'textBody': text_body,
        'attachments': attachments
    }


def fetch_emails(email_address, access_token, limit=20):
    try:
        mail = _imap_connect(email_address, access_token)
        result = []
        seen_folders = set()

        for folder_imap, folder_label in FETCH_FOLDERS:
            # 同一个文件夹可能有多个别名，只取一次
            if folder_label in seen_folders:
                continue

            status, _ = mail.select(folder_imap, readonly=True)
            if status != 'OK':
                continue

            seen_folders.add(folder_label)

            _, messages = mail.search(None, 'ALL')
            email_ids = messages[0].split()
            if not email_ids:
                continue

            # 每个文件夹取最近 limit 封
            recent_ids = email_ids[-limit:]

            for email_id in reversed(recent_ids):
                _, msg_data = mail.fetch(email_id, '(RFC822 FLAGS)')
                if not msg_data or not msg_data[0]:
                    continue
                raw_email = msg_data[0][1]
                flags_raw = msg_data[0][0].decode() if msg_data[0][0] else ''
                parsed = _parse_message(raw_email, flags_raw, folder_label, email_id.decode())
                result.append(parsed)

        mail.logout()

        # 按时间倒序，最终只取最新的 limit 封
        result.sort(key=lambda x: x['_ts'], reverse=True)
        for item in result:
            del item['_ts']

        return result[:limit]

    except Exception as e:
        print(f'IMAP fetch_emails error: {e}')
        raise


def fetch_email_detail(email_address, access_token, email_id):
    """获取单封邮件完整内容"""
    try:
        mail = _imap_connect(email_address, access_token)
        mail.select('inbox')

        _, msg_data = mail.fetch(email_id.encode(), '(RFC822 FLAGS)')
        msg = email.message_from_bytes(msg_data[0][1])
        flags_raw = msg_data[0][0].decode() if msg_data[0][0] else ''

        subject = _decode_str(msg.get('Subject', ''))
        from_header = _decode_str(msg.get('From', 'Unknown'))
        to_header = _decode_str(msg.get('To', ''))
        date = msg.get('Date', '')
        is_read = '\\Seen' in flags_raw

        html_body = ''
        text_body = ''
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get('Content-Disposition', ''))

                if 'attachment' in disposition:
                    filename = _decode_str(part.get_filename() or '')
                    attachments.append({
                        'filename': filename,
                        'contentType': content_type,
                        'size': len(part.get_payload(decode=True) or b'')
                    })
                elif content_type == 'text/html' and not html_body:
                    html_body = _decode_payload(part)
                elif content_type == 'text/plain' and not text_body:
                    text_body = _decode_payload(part)
        else:
            content_type = msg.get_content_type()
            if content_type == 'text/html':
                html_body = _decode_payload(msg)
            else:
                text_body = _decode_payload(msg)

        mail.close()
        mail.logout()

        return {
            'id': email_id,
            'subject': subject or '(no subject)',
            'from': from_header,
            'to': to_header,
            'receivedAt': date,
            'isRead': is_read,
            'hasAttachments': len(attachments) > 0,
            'htmlBody': html_body,
            'textBody': text_body,
            'attachments': attachments
        }
    except Exception as e:
        print(f'IMAP fetch_email_detail error: {e}')
        raise
