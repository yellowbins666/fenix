#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# 模板名称：FenixHost 免费服务器续期脚本
# 描述：通过 Cookie + Paymenter/Livewire 调用 renewFree 续期
# 支持多账号多服务
# 归类：Paymenter / Livewire 类型
# 仓库: https://github.com/jacksun-king/fenixhost-renew
# ============================================================
import os
import sys
import json
import re
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

# ============================================================
# 📌 配置区域
# ============================================================
BASE_URL = "https://fenixhost.net"
# Livewire 更新端点：旧版面板是 /paymenter/update，新版多为 /livewire/update；
# 脚本会从页面 HTML 自动识别，识别不到时才用这个默认值
UPDATE_URL = f"{BASE_URL}/paymenter/update"

# ============================================================
# 代理配置
# ============================================================
FENIX_PROXY = os.environ.get("FENIX_PROXY") or ""
NODE_LINK = os.environ.get("NODE_LINK") or ""
PROXIES = {}


def _detect_local_proxy() -> dict:
    """自动检测本地 sing-box 代理"""
    candidates = {
        "http://127.0.0.1:1081": "HTTP",
        "socks5://127.0.0.1:1080": "SOCKS5",
        "http://127.0.0.1:7890": "HTTP",
    }
    for url, label in candidates.items():
        try:
            requests.get("http://127.0.0.1:1081", timeout=2)
            proxies = {"http": url, "https": url}
            try:
                test = requests.get("https://api.ipify.org", proxies=proxies, timeout=8)
                if test.status_code == 200:
                    print(f"  🔗 自动检测到本地代理 ({label}): {url}")
                    return proxies
            except Exception:
                continue
        except Exception:
            continue
    return {}


if FENIX_PROXY:
    # 先测试代理是否可达，不可达则回退直连
    try:
        test = requests.get("http://127.0.0.1:1081", timeout=2)
        proxies = {"http": FENIX_PROXY, "https": FENIX_PROXY}
        test2 = requests.get("https://api.ipify.org", proxies=proxies, timeout=8)
        if test2.status_code == 200:
            PROXIES = proxies
            print(f"  🔗 使用 FENIX_PROXY: {FENIX_PROXY}")
        else:
            raise Exception("proxy unreachable")
    except Exception:
        print(f"  ⚠️  FENIX_PROXY={FENIX_PROXY} 不可达，回退直连")
        PROXIES = {}
elif NODE_LINK:
    print("  🔗 检测到 NODE_LINK，尝试自动检测本地代理...")
    PROXIES = _detect_local_proxy()
    if not PROXIES:
        print("  ⚠️  NODE_LINK 已设置但未检测到本地代理")
else:
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or ""
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if http_proxy or https_proxy:
        PROXIES = {"http": http_proxy, "https": https_proxy or http_proxy}
        print(f"  🔗 使用 HTTP_PROXY: {http_proxy}")
    else:
        detected = _detect_local_proxy()
        if detected:
            PROXIES = detected

# ============================================================
# Telegram 配置
# ============================================================
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""

# ============================================================
# 多账号检测
# 变量与 Cookie 的对应关系（每个变量只存一个 Cookie 的值）:
#   必填三件套:
#     XSRF_TOKEN          → Cookie: XSRF-TOKEN
#     PTERODACTYL_SESSION → Cookie: pterodactyl_session
#     REMEMBER_WEB        → Cookie: remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d
#   可选（填了才带，不填不带）:
#     HOST_SESSION        → Cookie: __Host-fenixhost_session（新版面板的会话 Cookie）
#     FH_DEVICE           → Cookie: fh_device（设备指纹 Cookie，面板可能校验）
# 脚本把已填的变量拼成一个 Cookie 字符串，没填的可选项一律不带。
#
# 账号规则:
#   三件套 + FENIX_SERVICE_IDS                  → 默认账号（无后缀，始终生效）
#   三件套加后缀 _1 / _2 / _3 ... + FENIX_SERVICE_IDS_N → 更多账号（依此类推，
#   可选变量同样加后缀，如 HOST_SESSION_1）
#
# 去重逻辑: 拼出的 Cookie 字符串相同的账号，只保留先出现的一个。
# ============================================================
REMEMBER_WEB_NAME = "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"
SESSION_COOKIE_NAME = "__Host-fenixhost_session"  # 按面板截图 __Host-fenixhos… 的全名

COOKIE_VARS = [
    # (环境变量名, Cookie 名, 是否必填)
    ("XSRF_TOKEN", "XSRF-TOKEN", True),
    ("PTERODACTYL_SESSION", "pterodactyl_session", True),
    ("REMEMBER_WEB", REMEMBER_WEB_NAME, True),
    ("HOST_SESSION", SESSION_COOKIE_NAME, False),
    ("FH_DEVICE", "fh_device", False),
]

ACCOUNTS = []
_seen_cookies = set()  # 用于去重


def _add_account(suffix: str, label: str):
    """按后缀读取 Cookie 变量并添加账号，自动去重（相同 cookie 不重复添加）"""
    tag = f"_{suffix}" if suffix else ""
    values = {env: os.environ.get(f"{env}{tag}") or "" for env, _, _ in COOKIE_VARS}
    if not any(values.values()):
        return False  # 这一组完全没配置，跳过
    missing = [f"{env}{tag}" for env, _, req in COOKIE_VARS if req and not values[env]]
    if missing:
        print(f"  ⚠️ {label} 缺少变量: {', '.join(missing)}，跳过")
        return False
    cookie = "; ".join(
        f"{cname}={values[env]}" for env, cname, _ in COOKIE_VARS if values[env]
    )
    if cookie in _seen_cookies:
        print(f"  ⚠️ 发现重复账号（{label} 与已有账号 cookie 相同），跳过")
        return False
    sid_label = f"FENIX_SERVICE_IDS{tag}"
    service_ids = [s.strip() for s in (os.environ.get(sid_label) or "").split(",") if s.strip()]
    if not service_ids:
        print(f"  ⚠️ {sid_label} 未配置服务 ID，跳过")
        return False
    _seen_cookies.add(cookie)
    ACCOUNTS.append({
        "cookie": cookie,
        "service_ids": service_ids,
        "label": label,
    })
    return True


# 默认账号: 无后缀（始终生效）
_add_account("", "账号1")

# 更多账号: 后缀 _1.._99（扫描所有编号，不因中间缺失而中断）
for _n in range(1, 100):
    _add_account(str(_n), f"账号{_n}")

if not ACCOUNTS:
    print("❌ 未配置任何 Cookie，脚本终止。")
    print("   单账号: 设置 XSRF_TOKEN + PTERODACTYL_SESSION + REMEMBER_WEB + FENIX_SERVICE_IDS")
    print("   多账号: 三件套加后缀，如 XSRF_TOKEN_1 + PTERODACTYL_SESSION_1")
    print("            + REMEMBER_WEB_1 + FENIX_SERVICE_IDS_1（_2、_3 依此类推）")
    sys.exit(1)

print(f"📋 检测到 {len(ACCOUNTS)} 个账号")
for acc in ACCOUNTS:
    print(f"   {acc['label']}: {', '.join(acc['service_ids'])}")


# ------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------
def send_telegram(message: str):
    """发送 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过通知")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, timeout=10, proxies=PROXIES or None)
        print("  ✅ Telegram 通知已发送")
    except Exception as e:
        print(f"  ❌ Telegram 发送失败: {e}")


def send_telegram_photo(photo_path: str, caption: str = ""):
    """发送 Telegram 图片"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过图片通知")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            requests.post(
                url,
                data={"chat_id": TG_CHAT_ID, "caption": caption},
                files={"photo": f},
                timeout=20,
                proxies=PROXIES or None,
            )
        print(f"  ✅ 截图已发送到 Telegram: {photo_path}")
    except Exception as e:
        print(f"  ❌ 截图发送失败: {e}")


def take_page_screenshot(cookie: str, service_id: str, save_path: str) -> bool:
    """使用 Playwright 截图（兜底用）"""
    page_url = f"{BASE_URL}/services/{service_id}"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠️  未安装 playwright，无法截图")
        return False

    cookie_str = cookie
    cookies = []
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookies.append({"name": k.strip(), "value": v.strip(), "domain": "fenixhost.net", "path": "/"})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
                proxy={k: v for k, v in PROXIES.items()} if PROXIES else None,
            )
            context.add_cookies(cookies)
            page = context.new_page()
            page.goto(page_url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(3000)
            page.screenshot(path=save_path, full_page=True)
            print(f"  📸 页面截图已保存: {save_path}")
            browser.close()
            return True
    except Exception as e:
        print(f"  ⚠️  截图失败: {e}")
        try:
            browser.close()
        except Exception:
            pass
        return False


def format_notification(status: str, label: str, service_id: str, new_expiry: str) -> str:
    """格式化续期通知消息"""
    now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "🆓 FenixHost 免费服务器续期",
        "",
        f"{status}",
        f"👤 {label}",
        f"🆔 服务ID: {service_id}",
        f"📅 到期时间: {new_expiry}",
        f"⏰ 执行时间: {now}",
    ]
    return "\n".join(lines)


def parse_cookies(cookie_str: str) -> dict:
    """将 Cookie 字符串解析为字典"""
    cookies = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def _unescape_html(s: str) -> str:
    """反转义 HTML 实体"""
    return s.replace("&quot;", '"').replace("&#039;", "'").replace("&amp;", "&")\
            .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")


def get_browser_headers() -> dict:
    """构造浏览器风格的 GET 请求头（FenixHost 需要这些头才能通过）"""
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "zh-CN,zh;q=0.9",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    }


def get_livewire_headers(referer: str) -> dict:
    """构造 Livewire 更新请求头"""
    return {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "content-type": "application/json",
        "origin": BASE_URL,
        "referer": referer,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "x-livewire": "",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def extract_csrf_token(html: str) -> str:
    """从页面 HTML 中提取 CSRF token"""
    m = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'csrfToken\s*:\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def extract_all_snapshots(html: str) -> list:
    """提取页面全部 Livewire snapshot，返回 [(memo_name, snapshot_dict), ...]"""
    found = []
    for m in re.finditer(r'wire:snapshot=["\']([^"\']+)["\']', html, re.IGNORECASE):
        snap_str = _unescape_html(m.group(1))
        try:
            data = json.loads(snap_str)
        except json.JSONDecodeError:
            continue
        found.append((data.get("memo", {}).get("name", ""), data))
    return found


def pick_renew_snapshot(html: str):
    """
    从页面 HTML 中挑出续期组件的 Livewire snapshot。

    在 Livewire 3 + Paymenter 中，组件 root 元素带 wire:snapshot 属性。
    优先 memo.name == services.show（旧版面板），其次名字带 renew 的，
    再次名字带 service / server 的（新版面板改名时的兜底）。

    返回 (snapshot, 组件名)；找不到返回 (None, 页面上发现的组件名列表)。
    """
    all_snaps = extract_all_snapshots(html)
    for name, data in all_snaps:
        if name == "services.show":
            return data, name
    for key in ("renew", "service", "server"):
        for name, data in all_snaps:
            if key in name.lower():
                return data, name
    return None, [n for n, _ in all_snaps]


def detect_update_url(html: str) -> str:
    """从页面 HTML 里识别 Livewire 更新端点，识别不到就用默认 UPDATE_URL"""
    for cand in ("/livewire/update", "/paymenter/update"):
        if cand in html:
            return f"{BASE_URL}{cand}"
    return UPDATE_URL


def extract_expiry(html: str) -> str:
    """
    从页面 HTML 中提取到期时间。
    FenixHost 使用 <p class="...countdown-timer" data-expires="UnixTs"> 存到期时间。
    """
    # 优先用 data-expires 时间戳
    m = re.search(r'data-expires="(\d+)"', html)
    if m:
        ts = int(m.group(1))
        try:
            dt = datetime.fromtimestamp(ts, timezone.utc) + timedelta(hours=8)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            return m.group(1)

    # 新版面板: RENEWAL 倒计时 "6d 1h 33m 21s"
    m = re.search(r'(\d+d\s+\d+h\s+\d+m\s+\d+s)', html)
    if m:
        return m.group(1)

    # 兜底：查找 "Expires at: Month DD, YYYY"
    m = re.search(r'Expires at:\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4})', html)
    if m:
        return m.group(1)

    # 兜底：查找 data-expires 附近的脚本
    m = re.search(r'data-expires[^0-9]*(\d+)', html)
    if m:
        return m.group(1)

    return ""


# ------------------------------------------------------------
# 续期函数
# ------------------------------------------------------------
def renew_service(cookie: str, service_id: str) -> dict:
    """
    通过 Paymenter/Livewire 续期服务器

    Args:
        cookie: Cookie 字符串（XSRF-TOKEN; pterodactyl_session; remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d）
        service_id: 服务 ID（如 522）

    Returns:
        包含续期结果的字典
    """
    cookies_dict = parse_cookies(cookie)

    session = requests.Session()
    session.cookies.update(cookies_dict)

    # 第一步：GET 服务页面（新版面板是 /dashboard/servers/<id>，旧版是 /services/<id>，两个都试）
    service_urls = [
        f"{BASE_URL}/dashboard/servers/{service_id}",
        f"{BASE_URL}/services/{service_id}",
    ]
    resp = None
    service_url = service_urls[0]
    snapshot = None
    snap_name = ""
    update_url = UPDATE_URL
    found_names = []
    for url in service_urls:
        print(f"  🔄 获取服务页面 {service_id}（{url}）...")
        try:
            r = session.get(url, headers=get_browser_headers(),
                            timeout=30, proxies=PROXIES or None, allow_redirects=True)
        except Exception as e:
            print(f"  ❌ 获取服务页面失败: {e}")
            return {"status": "error", "message": f"页面请求失败: {e}"}

        # 检查是否被重定向到登录页（Cookie 过期）
        if "login" in r.url.lower() and ("Sign in" in r.text or "sign in" in r.text.lower()):
            print(f"  ❌ 被重定向到登录页，Cookie 已过期")
            return {"status": "error", "message": "Cookie 已过期"}

        if r.status_code == 403:
            print(f"  ❌ 403 Forbidden - Cookie 可能已过期，或服务ID不存在")
            return {"status": "error", "message": "403 Forbidden"}
        if r.status_code != 200:
            print(f"  ❌ HTTP {r.status_code}: 获取服务页面失败")
            continue

        resp = r
        service_url = url
        snapshot, picked = pick_renew_snapshot(r.text)
        if not snapshot and picked and all(n.startswith("auth.") for n in picked):
            print(f"  ❌ 拿到的是登录页（组件 {picked}），Cookie 没登录上——多半缺会话 Cookie（HOST_SESSION）")
            return {"status": "error", "message": "Cookie 未登录（拿到登录页）"}
        if snapshot:
            snap_name = picked
            update_url = detect_update_url(r.text)
            break
        found_names = picked
        print(f"  ⚠️ 这个页面没有续期组件（发现组件: {found_names or '无'}），换下一个地址...")

    if resp is None:
        return {"status": "error", "message": "页面请求失败"}

    # 提取 CSRF token
    csrf_token = extract_csrf_token(resp.text)
    if not csrf_token:
        print(f"  ❌ 未找到 CSRF token")
        return {"status": "error", "message": "未找到 CSRF token"}

    if not snapshot:
        print(f"  ❌ 未找到续期组件，页面组件列表: {found_names}")
        return {"status": "error", "message": f"未找到续期组件（组件: {found_names}）"}

    print(f"  ✅ 已获取 CSRF token 和续期组件（{snap_name}，端点 {update_url}）")

    # 记录续期前的到期时间
    old_expiry = extract_expiry(resp.text)

    # 第二步：调用 renewFree 方法
    payload = {
        "_token": csrf_token,
        "components": [
            {
                "snapshot": json.dumps(snapshot),
                "updates": {},
                "calls": [
                    {"path": "", "method": "renewFree", "params": []}
                ]
            }
        ]
    }

    print(f"  🔄 调用 renewFree...")
    try:
        lw_resp = session.post(update_url, headers=get_livewire_headers(service_url),
                               json=payload, timeout=30, proxies=PROXIES or None)
    except Exception as e:
        print(f"  ❌ Livewire 请求失败: {e}")
        return {"status": "error", "message": f"请求失败: {e}"}

    if lw_resp.status_code != 200:
        print(f"  ❌ Livewire HTTP {lw_resp.status_code}")
        return {"status": "error", "message": f"Livewire HTTP {lw_resp.status_code}"}

    # 第三步：重新 GET 页面，获取续期后的到期时间
    print(f"  🔄 重新获取页面确认到期时间...")
    try:
        resp2 = session.get(service_url, headers=get_browser_headers(),
                            timeout=30, proxies=PROXIES or None)
    except Exception as e:
        print(f"  ⚠️  重新获取页面失败: {e}")
        return {"status": "success", "new_expiry": old_expiry or "续期成功"}

    new_expiry = extract_expiry(resp2.text)

    if new_expiry:
        # 对比新旧到期时间
        if old_expiry and new_expiry != old_expiry:
            print(f"  ✅ 续期成功! 到期时间从 {old_expiry} 更新为 {new_expiry}")
        else:
            print(f"  ✅ 续期请求成功，当前到期时间: {new_expiry}")
            print(f"     （注：若到期时间未变化，说明服务已满额续期或存在冷却时间）")
        return {"status": "success", "new_expiry": new_expiry}
    else:
        print(f"  ✅ Livewire 请求成功，但无法解析到期时间")
        screenshot_path = f"/tmp/fenixhost_{service_id}.png"
        if take_page_screenshot(cookie, service_id, screenshot_path):
            send_telegram_photo(
                screenshot_path,
                caption=f"🆓 FenixHost 续期成功\n🆔 服务ID: {service_id}\n到期时间见截图",
            )
        return {"status": "success", "new_expiry": "请查看截图"}


# ------------------------------------------------------------
# 主入口
# ------------------------------------------------------------
def main():
    print("=" * 40)
    print(" FenixHost 免费服务器自动续期")
    print("=" * 40)

    all_results = []

    for acc in ACCOUNTS:
        label = acc["label"]
        cookie = acc["cookie"]
        service_ids = acc["service_ids"]

        print(f"\n{'=' * 40}")
        print(f" {label}")
        print(f" 服务ID: {', '.join(service_ids)}")
        print(f"{'=' * 40}")

        for service_id in service_ids:
            try:
                result = renew_service(cookie, service_id)
                info = {
                    "label": label,
                    "service_id": service_id,
                    "status": "✅ 续期成功" if result["status"] == "success" else "❌ 续期失败",
                    "new_expiry": result.get("new_expiry", "未知"),
                }
            except Exception as e:
                print(f"  ❌ 服务 {service_id} 续期失败: {e}")
                info = {
                    "label": label,
                    "service_id": service_id,
                    "status": "❌ 续期失败",
                    "new_expiry": str(e)[:50],
                }

            all_results.append(info)

            # 每个服务发一次 Telegram 通知
            msg = format_notification(
                info["status"],
                info["label"],
                info["service_id"],
                info["new_expiry"]
            )
            send_telegram(msg)

    # 汇总
    success = sum(1 for r in all_results if "成功" in r["status"])
    fail = sum(1 for r in all_results if "失败" in r["status"])
    accounts = len(set(r["label"] for r in all_results))
    print(f"\n{'=' * 40}")
    print(f"📊 汇总: {accounts} 个账号, {success} 成功, {fail} 失败, 共 {len(all_results)} 个服务")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    main()
