# Outlook Mail Viewer

通过 Telegram Bot 管理批量 Outlook 邮箱，在浏览器中查看收件箱。

## 功能

- 通过 Telegram Bot 发送邮箱地址，获取短时效访问链接
- 浏览器打开链接，查看收件箱邮件列表和邮件详情
- 支持 HTML 邮件渲染、附件展示
- 批量导入邮箱（Bot 命令 或 网页导入页面）
- 访问链接随机生成、限时有效，防止爆破
- Docker 一键部署

## 邮箱格式

批量导入时每行一条，支持两种格式：

```
邮箱----密码----clientid----refresh_token
邮箱----密码----clientid----refresh_token----辅助邮箱----辅助邮箱密码
```

## 部署

### 1. 克隆项目

```bash
git clone https://github.com/your-username/outlook-mail.git
cd outlook-mail
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填写以下配置：

| 变量 | 说明 |
|------|------|
| `APP_BASE_URL` | 服务器公网地址，如 `https://your-domain.com` |
| `TELEGRAM_BOT_TOKEN` | BotFather 创建的 Bot Token |
| `TELEGRAM_ALLOWED_USER_IDS` | 允许使用的 Telegram 用户 ID，多个用逗号分隔 |
| `ENCRYPTION_KEY` | 加密 refresh token 用的密钥，随机字符串即可 |
| `ADMIN_TOKEN` | 访问导入页面的固定密码，自己设置 |
| `ACCESS_TOKEN_TTL` | 邮件链接有效期（秒），默认 3600（1小时）|

### 3. 启动

```bash
docker compose up -d
```

查看日志：

```bash
docker compose logs -f
```

更新代码后重新构建：

```bash
docker compose up -d --build
```

## Telegram Bot 命令

| 命令 / 消息 | 说明 |
|-------------|------|
| `邮箱地址` | 生成该邮箱的访问链接 |
| `#编号` | 按 ID 生成访问链接 |
| `/add` + 邮箱数据 | 直接在 Bot 中批量导入 |
| `/adds` | 获取网页批量导入页面链接 |

## 本地开发

```bash
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填写配置
python app/app.py
```

## 技术栈

- **后端**：Python + Flask
- **Telegram**：python-telegram-bot
- **邮件**：IMAP + OAuth2（Microsoft）
- **数据库**：SQLite
- **部署**：Docker
