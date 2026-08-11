# FenixHost Renew

FenixHost 免费服务器自动续期脚本。通过 **Cookie + Paymenter/Livewire** 调用 `renewFree` 方法续期，无需浏览器模拟，轻量高效。

## 原理

FenixHost 使用 Paymenter 计费系统（Laravel + Livewire）。点击 "Renovar" 按钮时，浏览器会向
`/paymenter/update` 发送 POST 请求，调用 `services.show` 组件的 `renewFree` 方法。

脚本直接模拟这个 Livewire 请求，无需打开浏览器。

## 前置准备

### 1. 获取 Cookie

FenixHost 使用三个 Cookie：
- `paymenter_session`
- `pterodactyl_session`
- `XSRF-TOKEN`

获取方法：

1. 打开 [fenixhost.net](https://fenixhost.net) 并登录
2. 按 `F12` 打开开发者工具 → **Application** / **存储** 标签
3. 左侧找到 **Cookies** → `https://fenixhost.net`
4. 复制这三个 Cookie 的值，用 `;` 连接成一个字符串：
   ```
   paymenter_session=xxx; pterodactyl_session=yyy; XSRF-TOKEN=zzz
   ```
5. 设为环境变量 `FENIX_COOKIE`

### 2. 获取服务 ID

查看你的服务 URL：`https://fenixhost.net/services/522` — 最后的数字 `522` 就是服务 ID。

## 配置（单账号 / 多账号）

脚本支持 **单账号** 和 **多账号多服务** 两种模式。

### 方式一：单账号（最简单）

| 类型 | 环境变量 | 值 |
|------|----------|-----|
| Cookie | `FENIX_COOKIE` | 三个 Cookie 用 `;` 连接 |
| 服务ID | `FENIX_SERVICE_IDS` | 服务 ID，多个用逗号分隔，如 `522,523` |

### 方式二：多账号多服务

脚本会自动检测 `FENIX_COOKIE_1`、`FENIX_COOKIE_2` ... 有哪个就续哪个，每个账号的每个服务逐一续期。

| 类型 | 环境变量 | 值 |
|------|----------|-----|
| Cookie | `FENIX_COOKIE_1` | 账号1 的 Cookie |
| 服务ID | `FENIX_SERVICE_IDS_1` | 账号1 的服务，如 `522,523` |
| Cookie | `FENIX_COOKIE_2` | 账号2 的 Cookie |
| 服务ID | `FENIX_SERVICE_IDS_2` | 账号2 的服务，如 `524` |
| Cookie | `FENIX_COOKIE_3` | 账号3 的 Cookie |
| 服务ID | `FENIX_SERVICE_IDS_3` | 账号3 的服务，可依此类推 |

> 原则：**Cookie 放 Secrets（加密），服务 ID 放 Variables（明文，方便改）**

### 代理配置

如果 GitHub Actions 的数据中心 IP 被拦截，设置代理即可解决。

#### 方式一：代理链接（推荐，支持 vless/vmess/tuic/hysteria2 等）

**GitHub Actions 上：** 在 Settings → Secrets and variables → Actions 添加 **Secret**：
`NODE_LINK` = `vless://uuid@server:port?...#...`

workflow 会自动执行 `setup_proxy.sh` 启动 sing-box 并挂载代理。

**本机运行：** 先启动 sing-box 转代理，再跑脚本：

```bash
export NODE_LINK="vless://uuid@server:port?..."
bash <(wget -qO- https://main.ssss.nyc.mn/setup_proxy.sh)
python fenixhost_renew.py
```

#### 方式二：直接指定 HTTP 代理

```bash
export FENIX_PROXY="http://127.0.0.1:7890"
```

> 脚本会自动检测本地 sing-box 代理（端口 1080/1081），无需手动指定。

## 本地运行

```bash
pip install requests

# 单账号
export FENIX_COOKIE="paymenter_session=xxx; pterodactyl_session=yyy; XSRF-TOKEN=zzz"
export FENIX_SERVICE_IDS="522"

# 多账号（可选，加上即启用）
export FENIX_COOKIE_1="cookie1..."
export FENIX_SERVICE_IDS_1="522,523"
export FENIX_COOKIE_2="cookie2..."
export FENIX_SERVICE_IDS_2="524"

export TG_BOT_TOKEN="你的bot_token"  # 可选
export TG_CHAT_ID="你的chat_id"      # 可选

python fenixhost_renew.py
```

脚本启动会打印检测到的账号，例如：

```
📋 检测到 1 个账号
   默认账号: 522
```

## GitHub Actions 自动续期

1. Fork 此仓库
2. 打开 **Settings → Secrets and variables → Actions**，添加：
   - **Secrets（加密）**：
     - `FENIX_COOKIE`：Cookie 字符串（单账号）
     - `FENIX_COOKIE_1` / `FENIX_COOKIE_2` / ... ：多账号各自 Cookie
     - `TG_BOT_TOKEN`：Telegram Bot Token（可选）
     - `TG_CHAT_ID`：Telegram Chat ID（可选）
   - **Variables（明文）**：
     - `FENIX_SERVICE_IDS`：`522,523`（单账号）
     - `FENIX_SERVICE_IDS_1` / `FENIX_SERVICE_IDS_2` / ... ：多账号各自服务ID
3. `fenixhost-renew.yml` 已预置 3 个账号位，直接填对应的 Secrets/Variables 即可，更多账号自行在 workflow 里追加
4. 每天 UTC 11:00（北京时间 19:00）自动运行
5. 也可在 Actions → **FenixHost Auto Renew** → **Run workflow** 手动触发

## 效果

运行成功后，Telegram 会收到通知：

```
🆓 FenixHost 免费服务器续期

✅ 续期成功
👤 默认账号
🆔 服务ID: 522
📅 到期时间: 2026-08-25 17:37:11
⏰ 执行时间: 2026-08-11 19:00:00
```

## 注意事项

- ⚠️ **Cookie 会过期**，过期后需重新获取并更新
- 不要过于频繁续期，以免触发平台风控
- 此项目参考了 `Scyed-Renew` 的续期脚本模式