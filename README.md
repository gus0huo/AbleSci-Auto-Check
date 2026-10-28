# AbleSci Auto Check-in

科研通（AbleSci.com）自动签到 GitHub Actions 项目，支持多账号、Cookie 自动续期、多渠道通知推送、积分统计。

> **免责声明**：本项目仅供个人学习与技术研究使用，请遵守目标网站的用户协议和服务条款。使用本项目产生的一切后果由使用者自行承担。

## 功能

- 🕐 每日自动签到（北京时间 6:00~7:00 随机执行，降低风控风险）
- 👥 多账号支持
- 🔄 Cookie 有效期 30 天，过期后自动用账号密码登录并刷新
- 📊 积分统计（读取网站积分页，总积分 + 今日变动）
- 📨 多渠道通知推送（Telegram / 微信 Server酱 / 飞书 / 钉钉）
- 🔒 凭据全部存储在 GitHub Secrets，统计数据邮箱自动脱敏

## 快速开始

### 1. Fork 本仓库（建议改名为私有仓库使用）

### 2. 配置 Secrets

**Settings → Secrets and variables → Actions**：

| Secret 名称 | 必填 | 说明 |
|------------|:---:|------|
| `ABLESCI_ACCOUNTS` | ✅ | JSON 数组，格式见下 |
| `PAT_TOKEN` | 可选 | 有 Secrets 写权限的 PAT（自动续期 Cookie 用） |
| `PUSH_TELEGRAM_BOT_TOKEN` | 可选 | Telegram Bot Token |
| `PUSH_TELEGRAM_CHAT_ID` | 可选 | Telegram Chat ID |
| `PUSH_SERVERCHAN_KEY` | 可选 | Server酱 SendKey |
| `PUSH_FEISHU_WEBHOOK` | 可选 | 飞书机器人 Webhook |
| `PUSH_DINGTALK_WEBHOOK` | 可选 | 钉钉机器人 Webhook |

**`ABLESCI_ACCOUNTS` 格式：**

```json
[
  {"email": "your_email@example.com", "password": "your_password", "cookie": ""},
  {"email": "your_email2@example.com", "password": "your_password2", "cookie": ""}
]
##cookie 留空即可，脚本会自动登录并填入
