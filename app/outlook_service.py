import imaplib
import email
import re
import chardet
from email.header import decode_header
import requests


def get_access_token(client_id, refresh_token):
    """用 refresh_token 换取 access_token，同时返回新的 refresh_token（如有）"""
    url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
    data = {
        'client_id': client_id,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        result = response.json()
        access_token = result.get('access_token')
        new_refresh_token = result.get('refresh_token')
        return access_token, new_refresh_token
    return None, None


def get_graph_access_token(client_id, refresh_token):
    """换取 Graph API 专用的 access_token（需要 graph scope）"""
    data = {
        'client_id': client_id,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'scope': 'https://graph.microsoft.com/.default'
    }
    try:
        response = requests.post(
            'https://login.microsoftonline.com/consumers/oauth2/v2.0/token',
            data=data
        )
        if response.status_code == 200:
            result = response.json()
            return result.get('access_token'), result.get('refresh_token')
    except Exception as e:
        print(f'Graph token error: {e}')
    return None, None


def _fetch_via_graph(email_address, graph_token, limit=20):
    """通过 Graph API 拉取全部邮件（跨所有文件夹，按时间倒序）"""
    headers = {'Authorization': f'Bearer {graph_token}'}
    result = []

    url = (
        f'https://graph.microsoft.com/v1.0/me/messages'
        f'?$top={limit}'
        f'&$select=id,subject,from,toRecipients,receivedDateTime,isRead,hasAttachments,bodyPreview,body,parentFolderId'
        f'&$orderby=receivedDateTime desc'
    )

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f'Graph fetch all messages failed: {response.status_code} {response.text}')
            return None
        messages = response.json().get('value', [])
    except Exception as e:
        print(f'Graph fetch error: {e}')
        return None

    for m in messages:
        from_obj  = m.get('from', {}).get('emailAddress', {})
        to_list   = m.get('toRecipients', [])
        to_str    = ', '.join(r.get('emailAddress', {}).get('address', '') for r in to_list)
        body      = m.get('body', {})
        html_body = body.get('content', '') if body.get('contentType') == 'html' else ''
        text_body = body.get('content', '') if body.get('contentType') == 'text' else ''
        preview   = m.get('bodyPreview', '')

        result.append({
            'id':             m.get('id', ''),
            'folder':         '',
            'subject':        m.get('subject') or '(no subject)',
            'from':           f"{from_obj.get('name', '')} <{from_obj.get('address', '')}>".strip(),
            'to':             to_str,
            'receivedAt':     m.get('receivedDateTime', ''),
            'isRead':         m.get('isRead', False),
            'hasAttachments': m.get('hasAttachments', False),
            'preview':        preview,
            'htmlBody':       html_body,
            'textBody':       text_body,
            'attachments':    []
        })

    return result


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

def _parse_message(raw_email, flags_raw, folder_name, email_id_str=''):
    """解析一封原始邮件，返回结构化数据"""
    is_read = '\\Seen' in flags_raw
    msg = email.message_from_bytes(raw_email)

    # 优先用传入的 IMAP sequence ID，否则用 Message-ID 头
    if not email_id_str:
        # 从 flags_raw 里提取 IMAP sequence number，格式如 "3 (FLAGS ..."
        m = re.match(r'(\d+)\s+\(', flags_raw)
        email_id_str = m.group(1) if m else (msg.get('Message-ID', '') or '')

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


def fetch_emails(email_address, client_id, refresh_token, limit=20):
    """返回 (messages, new_refresh_token)，new_refresh_token 为 None 表示无更新"""
    # ── 优先尝试 Graph API ────────────────────────────────
    graph_token, new_rt = get_graph_access_token(client_id, refresh_token)
    if graph_token:
        try:
            result = _fetch_via_graph(email_address, graph_token, limit)
            if result is not None:
                print(f'[fetch] Graph API success for {email_address}')
                return result, new_rt
        except Exception as e:
            print(f'[fetch] Graph API failed, falling back to IMAP: {e}')

    # ── 降级到 IMAP ───────────────────────────────────────
    print(f'[fetch] Using IMAP for {email_address}')
    imap_token, new_rt = get_access_token(client_id, refresh_token)
    if not imap_token:
        raise RuntimeError('Failed to get access token via both Graph and IMAP paths')

    try:
        mail = _imap_connect(email_address, imap_token)
        result = []
        seen_folders = set()

        for folder_imap, folder_label in FETCH_FOLDERS:
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

            recent_ids = email_ids[-limit:]

            # 批量 fetch：一次请求拉取所有邮件
            ids_str = b','.join(recent_ids).decode()
            _, msg_data_list = mail.fetch(ids_str, '(RFC822 FLAGS)')

            # imaplib 批量返回格式：
            # [(b'1 (FLAGS (...) RFC822 {size}', b'<raw email>'), b')', ...]
            fetched = []
            for item in msg_data_list:
                if isinstance(item, tuple) and len(item) == 2:
                    flags_raw = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                    raw_email = item[1]
                    if isinstance(raw_email, bytes) and len(raw_email) > 0:
                        fetched.append((flags_raw, raw_email))

            # IMAP 返回顺序为 ID 升序，反转后变新→旧
            for flags_raw, raw_email in reversed(fetched):
                parsed = _parse_message(raw_email, flags_raw, folder_label, '')
                result.append(parsed)

        mail.logout()

        # 按时间倒序，最终取最新的 limit 封
        result.sort(key=lambda x: x['_ts'], reverse=True)
        for item in result:
            del item['_ts']

        return result[:limit], new_rt

    except Exception as e:
        print(f'IMAP fetch_emails error: {e}')
        raise


def _is_graph_id(email_id):
    """Graph API 邮件 ID 是 Base64 长字符串，IMAP 是纯数字"""
    return not str(email_id).isdigit()


def fetch_email_detail(email_address, access_token, email_id, client_id=None, refresh_token=None):
    """获取单封邮件完整内容，自动根据 email_id 类型选择 Graph 或 IMAP"""
    if _is_graph_id(email_id):
        # Graph API 路径
        graph_token = access_token
        if client_id and refresh_token:
            graph_token, _ = get_graph_access_token(client_id, refresh_token)
        if graph_token:
            try:
                url = (
                    f'https://graph.microsoft.com/v1.0/me/messages/{email_id}'
                    f'?$select=id,subject,from,toRecipients,receivedDateTime,isRead,hasAttachments,body'
                )
                headers = {'Authorization': f'Bearer {graph_token}'}
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 200:
                    m = response.json()
                    from_obj = m.get('from', {}).get('emailAddress', {})
                    to_list  = m.get('toRecipients', [])
                    to_str   = ', '.join(r.get('emailAddress', {}).get('address', '') for r in to_list)
                    body     = m.get('body', {})
                    html_body = body.get('content', '') if body.get('contentType') == 'html' else ''
                    text_body = body.get('content', '') if body.get('contentType') == 'text' else ''
                    return {
                        'id': email_id,
                        'subject': m.get('subject') or '(no subject)',
                        'from': f"{from_obj.get('name', '')} <{from_obj.get('address', '')}>".strip(),
                        'to': to_str,
                        'receivedAt': m.get('receivedDateTime', ''),
                        'isRead': m.get('isRead', False),
                        'hasAttachments': m.get('hasAttachments', False),
                        'htmlBody': html_body,
                        'textBody': text_body,
                        'attachments': []
                    }
            except Exception as e:
                print(f'Graph fetch_email_detail error: {e}')
        return None

    # IMAP 路径
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
