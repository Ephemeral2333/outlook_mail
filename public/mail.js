(function () {
  var refreshButton = document.getElementById('refreshButton');
  var sessionStatus = document.getElementById('sessionStatus');
  var messageCount = document.getElementById('messageCount');
  var statusCard = document.getElementById('statusCard');
  var statusTitle = document.getElementById('statusTitle');
  var statusDetail = document.getElementById('statusDetail');
  var messageList = document.getElementById('messageList');
  var appGrant = document.body.dataset.grant || '';
  var sessionEndpoint = document.body.dataset.sessionEndpoint || '/mail/api/session/telegram';
  var messagesEndpoint = document.body.dataset.messagesEndpoint || '/mail/api/messages';

  function getTelegramApp() {
    var telegram = window.Telegram;

    if (!telegram || !telegram.WebApp) {
      return null;
    }

    return telegram.WebApp;
  }

  function setLoadingState(isLoading) {
    refreshButton.disabled = isLoading;
    refreshButton.textContent = isLoading ? 'Refreshing…' : 'Refresh';
  }

  function setStatus(title, detail, tone) {
    statusTitle.textContent = title;
    statusDetail.textContent = detail;
    statusCard.dataset.tone = tone || 'neutral';
    statusCard.classList.remove('u-hidden');
  }

  function hideStatus() {
    statusCard.classList.add('u-hidden');
  }

  function setMessageCount(count) {
    messageCount.textContent = count === 1 ? '1 message' : count + ' messages';
  }

  function clearMessages() {
    messageList.innerHTML = '';
  }

  function createMessageRow(message) {
    var item = document.createElement('li');
    var topline = document.createElement('div');
    var subject = document.createElement('p');
    var meta = document.createElement('p');
    var from = document.createElement('p');
    var preview = document.createElement('p');

    item.className = 'message-item';
    topline.className = 'message-topline';
    subject.className = 'message-subject';
    meta.className = 'message-meta';
    from.className = 'message-from';
    preview.className = 'message-preview';

    subject.textContent = getSubject(message);
    meta.textContent = formatMessageTime(message);
    from.textContent = getFromLabel(message);
    preview.textContent = getPreviewText(message);

    topline.appendChild(subject);
    topline.appendChild(meta);
    item.appendChild(topline);
    item.appendChild(from);
    item.appendChild(preview);

    return item;
  }

  function renderMessages(messages) {
    clearMessages();

    messages.forEach(function (message) {
      messageList.appendChild(createMessageRow(message));
    });
  }

  function renderEmptyState() {
    clearMessages();

    var item = document.createElement('li');
    var note = document.createElement('p');

    item.className = 'message-item';
    note.className = 'empty-note';
    note.textContent = 'No recent messages are available yet. Pull to refresh after the mailbox receives mail.';

    item.appendChild(note);
    messageList.appendChild(item);
  }

  function normalizeMessages(payload) {
    if (Array.isArray(payload)) {
      return payload;
    }

    if (payload && Array.isArray(payload.messages)) {
      return payload.messages;
    }

    if (payload && Array.isArray(payload.items)) {
      return payload.items;
    }

    if (payload && Array.isArray(payload.value)) {
      return payload.value;
    }

    return [];
  }

  function getSubject(message) {
    return message.subject || 'Untitled message';
  }

  function getFromLabel(message) {
    if (!message) {
      return 'Unknown sender';
    }

    if (typeof message.from === 'string') {
      return message.from;
    }

    if (message.from && typeof message.from.name === 'string') {
      return message.from.name;
    }

    if (message.from && typeof message.from.address === 'string') {
      return message.from.address;
    }

    if (message.from && message.from.emailAddress) {
      return message.from.emailAddress.name || message.from.emailAddress.address || 'Unknown sender';
    }

    if (typeof message.sender === 'string') {
      return message.sender;
    }

    if (typeof message.fromName === 'string') {
      return message.fromName;
    }

    return 'Unknown sender';
  }

  function getPreviewText(message) {
    return message.preview || message.bodyPreview || message.snippet || message.summary || 'No preview available.';
  }

  function getRawTimeValue(message) {
    return message.receivedAt || message.receivedDateTime || message.dateTime || message.sentDateTime || message.createdAt || message.time || null;
  }

  function formatMessageTime(message) {
    var rawValue = getRawTimeValue(message);

    if (!rawValue) {
      return 'Time unavailable';
    }

    var date = new Date(rawValue);

    if (Number.isNaN(date.getTime())) {
      return String(rawValue);
    }

    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(date);
  }

  async function createTelegramSession() {
    // 简单 token 模式：跳过 Telegram 验证
    if (appGrant === 'simple-auth-mode') {
      sessionStatus.textContent = 'Session active';
      return;
    }

    // 原有 Telegram 验证流程
    var telegramApp = getTelegramApp();
    var initData = telegramApp && telegramApp.initData ? telegramApp.initData : '';

    if (!appGrant) {
      throw new AuthRequiredError('The protected mailbox token is missing. Ask the Telegram bot for a new inbox entry point.');
    }

    if (!initData) {
      throw new AuthRequiredError('Open this inbox from the Telegram WebApp so the page can establish a trusted session.');
    }

    sessionStatus.textContent = 'Verifying Telegram session…';

    var response = await fetch(sessionEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      credentials: 'same-origin',
      body: JSON.stringify({ grant: appGrant, initData: initData })
    });

    if (response.status === 401 || response.status === 403) {
      throw new AuthRequiredError('Telegram authentication was rejected. Reopen this page from Telegram and try again.');
    }

    if (!response.ok) {
      throw new Error('Could not create the Telegram-backed session.');
    }

    sessionStatus.textContent = 'Telegram session active';
  }

  async function fetchMessages() {
    var response = await fetch(messagesEndpoint, {
      method: 'GET',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json'
      }
    });

    if (response.status === 401 || response.status === 403) {
      throw new AuthRequiredError('The current session is not authorized to read messages.');
    }

    if (!response.ok) {
      throw new Error('Could not load the latest messages.');
    }

    return response.json();
  }

  async function refreshInbox() {
    setLoadingState(true);
    setStatus('Connecting…', 'Starting a secure Telegram-backed session before loading the inbox.', 'neutral');

    try {
      await createTelegramSession();
      setStatus('Loading inbox…', 'The session is ready. Fetching the latest Outlook messages now.', 'neutral');

      var payload = await fetchMessages();
      var messages = normalizeMessages(payload);

      setMessageCount(messages.length);

      if (!messages.length) {
        renderEmptyState();
        setStatus('Inbox is empty', 'Authentication succeeded, but the mailbox did not return any recent messages.', 'warning');
        return;
      }

      renderMessages(messages);
      hideStatus();
      sessionStatus.textContent = 'Inbox synced';
    } catch (error) {
      clearMessages();
      setMessageCount(0);

      if (error instanceof AuthRequiredError) {
        sessionStatus.textContent = 'Authentication required';
        setStatus('Authentication required', error.message, 'warning');
        return;
      }

      sessionStatus.textContent = 'Sync failed';
      setStatus('Unable to load inbox', error && error.message ? error.message : 'An unexpected error interrupted inbox loading.', 'danger');
    } finally {
      setLoadingState(false);
    }
  }

  function AuthRequiredError(message) {
    this.name = 'AuthRequiredError';
    this.message = message;
  }

  AuthRequiredError.prototype = Object.create(Error.prototype);
  AuthRequiredError.prototype.constructor = AuthRequiredError;

  var telegramApp = getTelegramApp();

  if (telegramApp) {
    telegramApp.ready();

    if (typeof telegramApp.expand === 'function') {
      telegramApp.expand();
    }
  }

  refreshButton.addEventListener('click', refreshInbox);
  refreshInbox();
}());
