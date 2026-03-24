(function () {
  const params     = new URLSearchParams(location.search);
  const token      = params.get('token');
  const mailboxId  = params.get('mailboxId');

  const refreshBtn    = document.getElementById('refreshBtn');
  const mailList      = document.getElementById('mailList');
  const stateCard     = document.getElementById('stateCard');
  const stateTitle    = document.getElementById('stateTitle');
  const stateDesc     = document.getElementById('stateDesc');
  const statsBar      = document.getElementById('statsBar');
  const totalCount    = document.getElementById('totalCount');
  const unreadCount   = document.getElementById('unreadCount');
  const mailboxEmail  = document.getElementById('mailboxEmail');
  const detailPanel   = document.getElementById('detailPanel');
  const detailContent = document.getElementById('detailContent');
  const closeDetail   = document.getElementById('closeDetail');
  const overlay       = document.getElementById('overlay');

  let activeItem = null;

  // ── 工具函数 ──────────────────────────────

  function escHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function formatTime(raw) {
    if (!raw) return '';
    const d = new Date(raw);
    if (isNaN(d)) return raw;
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    return isToday
      ? d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  }

  // ── 列表区 ────────────────────────────────

  function showState(title, desc, isError) {
    stateCard.style.display = '';
    stateCard.className = 'state-card' + (isError ? ' state-card--error' : '');
    stateTitle.textContent = title;
    stateDesc.textContent  = desc || '';
    mailList.innerHTML = '';
    statsBar.style.display = 'none';
  }

  function hideState() { stateCard.style.display = 'none'; }

  function renderMessages(messages, email) {
    mailboxEmail.textContent = email || '';
    mailList.innerHTML = '';
    const unread = messages.filter(m => !m.isRead).length;
    totalCount.textContent  = messages.length;
    unreadCount.textContent = unread;
    statsBar.style.display = '';

    messages.forEach(msg => {
      const li = document.createElement('li');
      li.className = 'mail-item' + (msg.isRead ? ' mail-item--read' : ' mail-item--unread');
      li.dataset.id = msg.id;

      const attachHtml = msg.hasAttachments
        ? `<span class="mail-item__attach">
             <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
               <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.41 17.41a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
             </svg>附件
           </span>` : '';

      const folderHtml = (msg.folder && msg.folder !== '收件箱')
        ? `<span class="mail-item__folder">${escHtml(msg.folder)}</span>` : '';

      li.innerHTML = `
        <span class="mail-item__dot"></span>
        <span class="mail-item__from">${escHtml(msg.from)}</span>
        <span class="mail-item__time">${escHtml(formatTime(msg.receivedAt))}</span>
        <div class="mail-item__body">
          ${folderHtml}
          <span class="mail-item__subject">${escHtml(msg.subject)}</span>
          <span class="mail-item__preview">${escHtml(msg.preview || '')}</span>
          ${attachHtml}
        </div>
      `;

      li.addEventListener('click', () => openDetail(msg, li));
      mailList.appendChild(li);
    });

    hideState();
  }

  async function loadMessages() {
    refreshBtn.disabled = true;
    showState('正在加载邮件…', '请稍候', false);
    closeDetailPanel();

    try {
      const res  = await fetch(`/api/messages?token=${encodeURIComponent(token)}&mailboxId=${encodeURIComponent(mailboxId)}`);
      const data = await res.json();
      if (!data.ok) { showState('加载失败', data.error || '未知错误', true); return; }
      if (!data.messages || data.messages.length === 0) {
        showState('收件箱为空', '暂无邮件', false);
        statsBar.style.display = '';
        totalCount.textContent = unreadCount.textContent = 0;
        return;
      }
      renderMessages(data.messages, data.mailboxEmail);
    } catch {
      showState('网络错误', '请检查网络后重试', true);
    } finally {
      refreshBtn.disabled = false;
    }
  }

  // ── 详情面板 ──────────────────────────────

  function openDetailPanel() {
    detailPanel.classList.add('is-open');
    overlay.classList.add('is-visible');
  }

  function closeDetailPanel() {
    detailPanel.classList.remove('is-open');
    overlay.classList.remove('is-visible');
    if (activeItem) { activeItem.classList.remove('mail-item--active'); activeItem = null; }
  }

  function openDetail(msg, liEl) {
    if (activeItem) activeItem.classList.remove('mail-item--active');
    activeItem = liEl;
    liEl.classList.add('mail-item--active');
    liEl.classList.remove('mail-item--unread');
    liEl.classList.add('mail-item--read');
    const dot = liEl.querySelector('.mail-item__dot');
    if (dot) dot.style.visibility = 'hidden';

    openDetailPanel();
    renderDetail(msg);
  }

  function renderDetail(msg) {
    const attachmentsHtml = (msg.attachments || []).length > 0
      ? `<div class="detail-attachments">
           <p class="detail-attachments__title">附件（${msg.attachments.length}个）</p>
           ${msg.attachments.map(a => `
             <div class="attachment-item">
               <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                 <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
                 <path d="M13 2v7h7"/>
               </svg>
               <span>${escHtml(a.filename || '未知文件')}</span>
               <span class="attachment-size">${formatSize(a.size || 0)}</span>
             </div>`).join('')}
         </div>` : '';

    let bodyHtml = '';
    if (msg.htmlBody) {
      // 注入 <base target="_blank"> 让所有链接在新标签页打开
      const injected = msg.htmlBody.replace(
        /<head([^>]*)>/i,
        '<head$1><base target="_blank" rel="noopener noreferrer">'
      );
      const blob = new Blob([injected], { type: 'text/html' });
      const url  = URL.createObjectURL(blob);
      bodyHtml = `<div class="detail-body detail-body--html">
        <iframe src="${url}" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-top-navigation"
          onload="this.style.height=this.contentDocument.body.scrollHeight+40+'px'"></iframe>
      </div>`;
    } else if (msg.textBody) {
      bodyHtml = `<div class="detail-body detail-body--text">${escHtml(msg.textBody)}</div>`;
    } else {
      bodyHtml = `<p style="color:var(--text-muted);font-size:13px">（无正文内容）</p>`;
    }

    detailContent.innerHTML = `
      <div class="detail-header">
        <h2 class="detail-subject">${escHtml(msg.subject)}</h2>
        <div class="detail-meta">
          <div class="detail-meta-row"><strong>发件人</strong><span>${escHtml(msg.from)}</span></div>
          <div class="detail-meta-row"><strong>收件人</strong><span>${escHtml(msg.to || '')}</span></div>
          <div class="detail-meta-row"><strong>时间</strong><span>${escHtml(msg.receivedAt || '')}</span></div>
        </div>
      </div>
      <hr class="detail-divider">
      ${bodyHtml}
      ${attachmentsHtml}
    `;
  }

  // ── 事件绑定 ──────────────────────────────

  refreshBtn.addEventListener('click', loadMessages);
  closeDetail.addEventListener('click', closeDetailPanel);
  overlay.addEventListener('click', closeDetailPanel);

  loadMessages();
})();
