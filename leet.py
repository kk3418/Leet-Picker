#!/usr/bin/env python3
"""LeetPicker - 定時挑選 LeetCode 題目的 CLI 工具（純標準函式庫）"""

import argparse
import json
import random
import re
import sys
import unicodedata
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

# ─── 常數設定 ────────────────────────────────────────────────────────────────

APP_DIR = Path.home() / ".config" / "leetpicker"
CONFIG_FILE = APP_DIR / "config.json"
HISTORY_FILE = APP_DIR / "history.json"
PROBLEMS_CACHE = APP_DIR / "problems_cache.json"

LEETCODE_API = "https://leetcode.com/api/problems/all/"
PROBLEM_URL = "https://leetcode.com/problems/{slug}/"

DIFFICULTY_MAP = {1: "Easy", 2: "Medium", 3: "Hard"}

DEFAULT_CONFIG: Dict[str, Any] = {
    "difficulty": ["Easy", "Medium", "Hard"],
    "frequency_days": 1,
    "last_pick_date": None,
    "current_problem": None,
}

# ─── ANSI 顏色 ───────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
WHITE  = "\033[37m"

DIFF_COLORS = {"Easy": GREEN, "Medium": YELLOW, "Hard": RED}


def colored(text: str, *codes: str) -> str:
    if not sys.stdout.isatty():
        return text
    return "".join(codes) + text + RESET


def display_width(s: str) -> int:
    """計算字串在終端的顯示寬度（考慮中文全形與 ANSI 色碼）"""
    s = re.sub(r"\033\[[0-9;]*m", "", s)  # 移除 ANSI 色碼
    w = 0
    for ch in s:
        eaw = unicodedata.east_asian_width(ch)
        w += 2 if eaw in ("W", "F") else 1
    return w


def pad(text: str, width: int) -> str:
    """將 text 補空白到指定的顯示寬度"""
    return text + " " * (width - display_width(text))


# ─── 資料管理 ────────────────────────────────────────────────────────────────

def ensure_app_dir():
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    ensure_app_dir()
    if CONFIG_FILE.exists():
        config = json.loads(CONFIG_FILE.read_text())
        for k, v in DEFAULT_CONFIG.items():
            config.setdefault(k, v)
        return config
    return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any]):
    ensure_app_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))


def load_history() -> List[Dict[str, Any]]:
    ensure_app_dir()
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []


def save_history(history: List[Dict[str, Any]]):
    ensure_app_dir()
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))


# ─── LeetCode API ────────────────────────────────────────────────────────────

def fetch_problems() -> List[Dict[str, Any]]:
    """從 LeetCode API 取得題目列表，每日快取一次"""
    if PROBLEMS_CACHE.exists():
        cache = json.loads(PROBLEMS_CACHE.read_text())
        if cache.get("date") == str(date.today()):
            return cache["problems"]

    print(colored("正在從 LeetCode 取得題目列表...", DIM))

    req = urllib.request.Request(
        LEETCODE_API,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
            "Referer": "https://leetcode.com/",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, Exception) as e:
        print(colored(f"無法連線到 LeetCode API: {e}", RED))
        if PROBLEMS_CACHE.exists():
            print(colored("使用本地快取資料...", YELLOW))
            return json.loads(PROBLEMS_CACHE.read_text())["problems"]
        sys.exit(1)

    problems = []
    for p in data.get("stat_status_pairs", []):
        if p.get("paid_only", False):
            continue
        stat = p["stat"]
        diff = DIFFICULTY_MAP.get(p["difficulty"]["level"], "Unknown")
        problems.append({
            "id": stat["question_id"],
            "frontend_id": str(stat.get("frontend_question_id", stat["question_id"])),
            "title": stat["question__title"],
            "slug": stat["question__title_slug"],
            "difficulty": diff,
        })

    problems.sort(key=lambda x: int(x["frontend_id"]))
    ensure_app_dir()
    PROBLEMS_CACHE.write_text(
        json.dumps({"date": str(date.today()), "problems": problems}, ensure_ascii=False)
    )
    print(colored(f"已載入 {len(problems)} 道免費題目", DIM))
    return problems


def get_review_ids() -> set:
    """取得所有標記為複習的題目 ID"""
    history = load_history()
    return {h["id"] for h in history if h.get("review")}


def do_pick_problem(difficulty: List[str], history_ids: set) -> Optional[Dict[str, Any]]:
    """根據難度和歷史紀錄挑選一題（優先選未做過的，複習題有機率出現）"""
    problems = fetch_problems()
    filtered = [p for p in problems if p["difficulty"] in difficulty]
    if not filtered:
        print(colored("沒有符合條件的題目", RED))
        return None

    review_ids = get_review_ids()
    review_candidates = [p for p in filtered if p["id"] in review_ids]

    # 30% 機率抽複習題（如果有的話）
    if review_candidates and random.random() < 0.3:
        problem = random.choice(review_candidates)
        print(colored("★ 複習時間！這是你標記要複習的題目", CYAN, BOLD))
        return problem

    not_done = [p for p in filtered if p["id"] not in history_ids]
    if not_done:
        return random.choice(not_done)
    print(colored("恭喜！你已完成所有符合條件的題目！從全部重新選取...", YELLOW))
    return random.choice(filtered)


# ─── Telegram 推播 ───────────────────────────────────────────────────────────

def _resolve_telegram_ip() -> Optional[str]:
    """用 DNS 查詢 api.telegram.org 真實 IP，避免本機 DNS 劫持"""
    import socket
    try:
        results = socket.getaddrinfo("api.telegram.org", 443)
        for family, _, _, _, addr in results:
            if family == socket.AF_INET and addr[0] != "127.0.0.1":
                return addr[0]
    except Exception:
        pass
    # getaddrinfo 被劫持時，用 subprocess 呼叫 nslookup 取真實 IP
    try:
        out = subprocess.run(
            ["nslookup", "api.telegram.org"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Address:") or line.startswith("Address"):
                ip = line.split(":")[-1].strip().split("#")[0].strip()
                if ip and ip != "127.0.0.1" and not ip.startswith("168."):
                    return ip
    except Exception:
        pass
    return None


_TG_REAL_IP: Optional[str] = None


def tg_api(token: str, method: str, params: Dict[str, Any] = None, http_timeout: int = 10) -> Optional[Dict]:
    """呼叫 Telegram Bot API，失敗回傳 None"""
    import ssl
    import socket

    global _TG_REAL_IP

    host = "api.telegram.org"
    path = f"/bot{token}/{method}"
    data = json.dumps(params or {}).encode()

    # 先嘗試正常連線
    url = f"https://{host}{path}"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(colored(f"Telegram API 錯誤 ({method}): HTTP {e.code}", RED))
        return None
    except Exception:
        pass  # DNS 劫持等問題，改用 IP 直連

    # 正常連線失敗，用 IP 直連繞過 DNS 劫持
    if _TG_REAL_IP is None:
        _TG_REAL_IP = _resolve_telegram_ip() or ""
    if not _TG_REAL_IP:
        print(colored(f"Telegram API 錯誤 ({method}): 無法解析 api.telegram.org", RED))
        return None

    url_ip = f"https://{_TG_REAL_IP}{path}"
    req_ip = urllib.request.Request(url_ip, data=data, headers={
        "Content-Type": "application/json",
        "Host": host,
    })
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req_ip, timeout=http_timeout, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(colored(f"Telegram API 錯誤 ({method}): HTTP {e.code}", RED))
        return None
    except Exception as e:
        print(colored(f"Telegram API 錯誤 ({method}): {e}", RED))
        return None


def tg_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def notify_self(token: str, chat_id: int, problem: Dict[str, Any]):
    diff_emoji = {"Easy": "🟢", "Medium": "🟡", "Hard": "🔴"}.get(problem["difficulty"], "⚪")
    url = PROBLEM_URL.format(slug=problem["slug"])
    text = (
        f"🎯 <b>今日 LeetCode 題目更新！</b>\n\n"
        f"📝 <b>{tg_escape(str(problem['frontend_id']))}. {tg_escape(problem['title'])}</b>\n"
        f"{diff_emoji} 難度：{problem['difficulty']}\n"
        f'🔗 <a href="{url}">開始作答</a>'
    )
    result = tg_api(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    if result and result.get("ok"):
        print(colored("✓ 已發送 Telegram 通知", CYAN))
    else:
        print(colored("⚠ Telegram 通知發送失敗", DIM))


def try_notify_self(problem: Dict[str, Any]):
    """若已設定 Telegram，發送換題通知；未設定則靜默略過"""
    config = load_config()
    token = config.get("telegram_token")
    chat_id = config.get("telegram_chat_id")
    if not token or not chat_id:
        return
    notify_self(token, chat_id, problem)


# ─── 顯示函數 ────────────────────────────────────────────────────────────────

def print_box(lines: List[str], title: str = ""):
    width = max(len(title) + 4, max(len(l) for l in lines) + 4, 50)
    bar = "─" * width
    top = f"┌{bar}┐"
    bot = f"└{bar}┘"

    title_line = f"┤ {colored(title, BOLD, CYAN)} ├"
    print(colored(f"┌{bar[:len(bar)//2 - len(title)//2 - 2]}", CYAN) +
          colored(f" {title} ", BOLD, CYAN) +
          colored("─" * (width - len(bar)//2 + len(title)//2 + 2 - 1) + "┐", CYAN))
    for line in lines:
        padding = width - len(line)
        print(colored("│ ", CYAN) + line + " " * (padding - 1) + colored("│", CYAN))
    print(colored(f"└{bar}┘", CYAN))


def display_problem(problem: Dict[str, Any], label: str = "今日 LeetCode 題目"):
    diff = problem["difficulty"]
    diff_color = DIFF_COLORS.get(diff, WHITE)
    url = PROBLEM_URL.format(slug=problem["slug"])

    width = 60
    bar = "─" * width

    print()
    print(colored(f"┌── {label} ", CYAN) + colored("─" * (width - len(label) - 4) + "┐", CYAN))
    print(colored("│", CYAN))

    title_text = f"  {problem['frontend_id']}. {problem['title']}"
    print(colored("│", CYAN) + colored(title_text, BOLD, WHITE))
    print(colored("│", CYAN))
    print(colored("│", CYAN) + f"  難度: " + colored(diff, BOLD, diff_color))
    print(colored("│", CYAN) + f"  連結: " + colored(url, CYAN))
    print(colored("│", CYAN))
    print(colored(f"└{bar}┘", CYAN))
    print()


def freq_label(days: int) -> str:
    return {1: "每天", 7: "每週", 14: "每兩週", 30: "每月"}.get(days, f"每 {days} 天")


# ─── 子命令處理函數 ──────────────────────────────────────────────────────────

def cmd_today(_args):
    """顯示今日題目（根據頻率自動決定是否更換新題）"""
    config = load_config()
    history = load_history()
    history_ids = {h["id"] for h in history}

    last_pick = config.get("last_pick_date")
    freq = config.get("frequency_days", 1)
    current = config.get("current_problem")

    should_pick = last_pick is None or (
        (date.today() - date.fromisoformat(last_pick)).days >= freq
    )

    if should_pick:
        problem = do_pick_problem(config["difficulty"], history_ids)
        if problem:
            config["last_pick_date"] = str(date.today())
            config["current_problem"] = problem
            save_config(config)
            history.append({**problem, "picked_date": str(date.today())})
            save_history(history)
            display_problem(problem)
            try_notify_self(problem)
    else:
        if current:
            next_date = date.fromisoformat(last_pick) + timedelta(days=freq)
            days_left = (next_date - date.today()).days
            print(colored(f"\n下次更換: {next_date}（還有 {days_left} 天）", DIM))
            display_problem(current)
        else:
            print(colored("尚無題目，執行 `leet pick` 來取得第一題", YELLOW))


def mark_current_solved(config: Dict[str, Any], history: List[Dict[str, Any]]) -> bool:
    """將 history 中當前題目最新一筆標記為完成，回傳是否有更新"""
    current = config.get("current_problem")
    if not current:
        return False
    for h in reversed(history):
        if h["id"] == current["id"] and not h.get("solved_date"):
            h["solved_date"] = str(date.today())
            return True
    return False


def cmd_review(args):
    """將題目標記或取消複習 tag"""
    config = load_config()
    history = load_history()

    if args.problem_id:
        # 用 frontend_id 找題目
        target = None
        for h in reversed(history):
            if h.get("frontend_id") == str(args.problem_id):
                target = h
                break
        if not target:
            print(colored(f"在歷史紀錄中找不到題號 {args.problem_id}", RED))
            return
    else:
        # 標記當前題目
        current = config.get("current_problem")
        if not current:
            print(colored("目前沒有進行中的題目，請指定題號：leet review <題號>", YELLOW))
            return
        target = None
        for h in reversed(history):
            if h["id"] == current["id"]:
                target = h
                break
        if not target:
            print(colored("當前題目不在歷史紀錄中", RED))
            return

    title = f"{target['frontend_id']}. {target.get('title', '?')}"
    if args.remove:
        if target.get("review"):
            target["review"] = False
            save_history(history)
            print(colored(f"✗ 已移除複習標記：{title}", YELLOW))
        else:
            print(colored(f"該題目沒有複習標記：{title}", DIM))
    else:
        if target.get("review"):
            print(colored(f"該題目已經標記為複習：{title}", DIM))
        else:
            target["review"] = True
            save_history(history)
            print(colored(f"★ 已標記為複習：{title}", CYAN, BOLD))


def cmd_solved(args):
    """將題目標記為已完成（不給題號則標記今日題目）"""
    config = load_config()
    history = load_history()

    if args.problem_id:
        target = None
        for h in reversed(history):
            if h.get("frontend_id") == str(args.problem_id):
                target = h
                break
        if not target:
            print(colored(f"在歷史紀錄中找不到題號 {args.problem_id}", RED))
            return
        title = f"{target['frontend_id']}. {target.get('title', '?')}"
        if target.get("solved_date"):
            print(colored(f"該題目已經標記為完成了：{title}", DIM))
        else:
            target["solved_date"] = str(date.today())
            save_history(history)
            print(colored(f"✓ 已完成：{title}", GREEN, BOLD))
    else:
        current = config.get("current_problem")
        if not current:
            print(colored("目前沒有進行中的題目", YELLOW))
            return
        if mark_current_solved(config, history):
            save_history(history)
            title = f"{current['frontend_id']}. {current['title']}"
            print(colored(f"✓ 已完成：{title}", GREEN, BOLD))
        else:
            print(colored("當前題目已經標記為完成了", DIM))


def cmd_pick(_args):
    """立即強制挑選一道新題目（忽略頻率限制）"""
    config = load_config()
    history = load_history()

    current = config.get("current_problem")
    if current and not any(
        h["id"] == current["id"] and h.get("solved_date")
        for h in reversed(history)
        if h["id"] == current["id"]
    ):
        title = f"{current['frontend_id']}. {current['title']}"
        try:
            ans = input(colored(f"是否已完成「{title}」？[y/N] ", YELLOW)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans in ("y", "yes"):
            if mark_current_solved(config, history):
                save_history(history)
                print(colored("✓ 已標記為完成", GREEN))
            history = load_history()  # 重新載入確保資料一致

    history_ids = {h["id"] for h in history}
    problem = do_pick_problem(config["difficulty"], history_ids)
    if problem:
        config["last_pick_date"] = str(date.today())
        config["current_problem"] = problem
        save_config(config)
        history.append({**problem, "picked_date": str(date.today())})
        save_history(history)
        display_problem(problem, label="新題目")
        try_notify_self(problem)


def cmd_bot(args):
    """Telegram 推播通知設定"""
    config = load_config()

    if args.bot_cmd == "setup":
        if not args.token:
            print(colored("請提供 bot token：leet bot setup <token>", RED))
            sys.exit(1)

        result = tg_api(args.token, "getMe")
        if not result:
            print(colored("無法連線到 Telegram，請確認網路連線或 proxy 設定", RED))
            sys.exit(1)
        if not result.get("ok"):
            print(colored("Token 無效，請確認後重試", RED))
            sys.exit(1)
        bot_name = result["result"].get("username", "unknown")

        print(colored(f"✓ Bot @{bot_name} 驗證成功", GREEN))

        # 清除 webhook，確保 getUpdates 能正常運作
        tg_api(args.token, "deleteWebhook")

        # 先記下目前最新的 update_id，避免抓到舊訊息
        snapshot = tg_api(args.token, "getUpdates", {"limit": 1, "timeout": 0})
        offset = 0
        if snapshot and snapshot.get("ok") and snapshot.get("result"):
            offset = snapshot["result"][-1]["update_id"] + 1

        print(colored(f"  請在 Telegram 傳送任意訊息給 @{bot_name}", YELLOW))
        print(colored("  （等待中，最多 60 秒，Ctrl+C 取消）", DIM))

        chat_id = None
        first_name = ""
        try:
            for _ in range(12):  # 每次最多等 5 秒，共 12 次 = 60 秒
                updates = tg_api(args.token, "getUpdates", {
                    "offset": offset, "limit": 1, "timeout": 5,
                }, http_timeout=10)
                if updates and updates.get("ok"):
                    for update in updates.get("result", []):
                        offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        cid = msg.get("chat", {}).get("id")
                        if cid:
                            chat_id = cid
                            first_name = msg.get("from", {}).get("first_name", "")
                if chat_id:
                    break
        except KeyboardInterrupt:
            print(colored("\n已取消", DIM))
            return

        if not chat_id:
            print(colored("等待超時，請再執行一次 leet bot setup", RED))
            sys.exit(1)

        config["telegram_token"] = args.token
        config["telegram_chat_id"] = chat_id
        save_config(config)
        print(colored(f"✓ 設定完成！將推播通知給：{first_name}（chat_id: {chat_id}）", GREEN, BOLD))
        print(colored("  執行 leet bot test 測試是否正常", DIM))
        python = sys.executable
        script = str(Path(__file__).resolve())
        print()
        print(colored("  ── 自動排程設定 ──", DIM))
        print(colored("  執行 crontab -e，加入以下這行（每天早上 9 點檢查）：", DIM))
        print(colored(f"  0 20 * * * {python} {script} today", CYAN))

    elif args.bot_cmd == "test":
        token = config.get("telegram_token")
        chat_id = config.get("telegram_chat_id")
        if not token or not chat_id:
            print(colored("尚未設定，請先執行：leet bot setup <token>", RED))
            sys.exit(1)
        result = tg_api(token, "sendMessage", {
            "chat_id": chat_id,
            "text": "🧪 <b>LeetPicker 測試通知</b>\n\n設定成功！每次換題時你會收到這樣的推播 🎉",
            "parse_mode": "HTML",
        })
        if result and result.get("ok"):
            print(colored("✓ 測試訊息已發送，請查看 Telegram", GREEN))
        else:
            print(colored("✗ 發送失敗，請確認 token 與 chat_id 是否正確", RED))

    elif args.bot_cmd == "status":
        token = config.get("telegram_token")
        chat_id = config.get("telegram_chat_id")
        print()
        print(colored("  Telegram 推播狀態", BOLD, CYAN))
        print(colored("─" * 40, DIM))
        if token:
            me = tg_api(token, "getMe")
            if me and me.get("ok"):
                print(f"  Bot     : @{me['result'].get('username', 'unknown')}")
                print(f"  Chat ID : {chat_id if chat_id else colored('未設定', YELLOW)}")
                print(colored("  狀態    : 正常", GREEN))
            else:
                print(colored("  Token 已設定但無法連線", YELLOW))
        else:
            print(colored("  尚未設定（執行 leet bot setup <token>）", YELLOW))
        print()

    else:
        print(colored("用法：leet bot <setup|test|status> [token]", RED))


def cmd_config(args):
    """查看或修改難度與頻率設定"""
    config = load_config()
    changed = False

    if args.difficulty:
        DIFF_MAP = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}
        if args.difficulty.lower() == "all":
            config["difficulty"] = ["Easy", "Medium", "Hard"]
        else:
            parts = [d.strip().lower() for d in args.difficulty.split(",")]
            mapped = [DIFF_MAP[p] for p in parts if p in DIFF_MAP]
            if not mapped:
                print(colored("無效的難度。請使用 easy / medium / hard / all", RED))
                sys.exit(1)
            config["difficulty"] = mapped
        changed = True
        print(colored(f"✓ 難度已設定為: {', '.join(config['difficulty'])}", GREEN))

    if args.frequency:
        config["frequency_days"] = args.frequency
        changed = True
        print(colored(f"✓ 頻率已設定為: {freq_label(args.frequency)}", GREEN))

    if changed:
        save_config(config)
        return

    # 顯示目前設定
    print()
    row_fmt = f"  {{:<10}} {{}}"
    sep = colored("─" * 40, DIM)
    print(colored("  目前設定", BOLD, CYAN))
    print(sep)

    diff_parts = []
    for d in config["difficulty"]:
        diff_parts.append(colored(d, DIFF_COLORS.get(d, WHITE)))
    print(row_fmt.format("難度", " / ".join(diff_parts)))
    print(row_fmt.format("頻率", freq_label(config["frequency_days"])))

    last_pick = config.get("last_pick_date")
    if last_pick:
        next_date = date.fromisoformat(last_pick) + timedelta(days=config["frequency_days"])
        print(row_fmt.format("上次選題", last_pick))
        print(row_fmt.format("下次選題", str(next_date)))

    print(sep)
    print(colored("  修改範例: leet config -d easy,medium -f 2", DIM))
    print()


def cmd_status(_args):
    """顯示目前狀態、設定與當前題目"""
    config = load_config()
    history = load_history()

    print()
    row_fmt = f"  {{:<12}} {{}}"
    sep = colored("─" * 44, DIM)
    print(colored("  LeetPicker 狀態", BOLD, CYAN))
    print(sep)

    diff_parts = [colored(d, DIFF_COLORS.get(d, WHITE)) for d in config["difficulty"]]
    print(row_fmt.format("難度", " / ".join(diff_parts)))
    print(row_fmt.format("頻率", freq_label(config["frequency_days"])))
    print(row_fmt.format("已選題數", str(len(history))))

    last_pick = config.get("last_pick_date")
    if last_pick:
        last_date = date.fromisoformat(last_pick)
        next_date = last_date + timedelta(days=config["frequency_days"])
        days_left = (next_date - date.today()).days
        print(row_fmt.format("上次選題", last_pick))
        if days_left > 0:
            print(row_fmt.format("下次選題", f"{next_date} （還有 {days_left} 天）"))
        else:
            print(row_fmt.format("下次選題", colored("現在可以選新題！", GREEN)))
    else:
        print(row_fmt.format("狀態", colored("尚未選過題目", YELLOW)))

    print(sep)
    print()

    current = config.get("current_problem")
    if current:
        display_problem(current, label="當前題目")


SORT_CONFIG = {
    #           key_fn                                                    reverse  label
    "date":     (lambda h: h.get("picked_date", ""),                     True,   "日期（新→舊）"),
    "date-asc": (lambda h: h.get("picked_date", ""),                     False,  "日期（舊→新）"),
    "difficulty":(lambda h: {"Easy": 0, "Medium": 1, "Hard": 2}.get(h.get("difficulty", ""), -1),
                                                                          True,   "難度（Hard→Easy）"),
    "id":       (lambda h: int(h.get("frontend_id") or 0),               False,  "題號"),
}


def cmd_history(args):
    """顯示題目歷史紀錄"""
    history = load_history()
    if not history:
        print(colored("尚無歷史紀錄", YELLOW))
        return

    if args.review:
        history = [h for h in history if h.get("review")]
        if not history:
            print(colored("沒有標記為複習的題目", YELLOW))
            return

    sort_key, reverse, sort_label = SORT_CONFIG[args.sort]
    sorted_all = sorted(history, key=sort_key, reverse=reverse)
    records = sorted_all if args.all else sorted_all[:args.limit]

    total = len(history)
    solved_count = sum(1 for h in history if h.get("solved_date"))

    print()
    header = (
        f"  歷史紀錄（共 {total} 題｜已完成 {solved_count} 題，"
        f"顯示 {len(records)} 筆｜排序：{sort_label}）"
    )
    print(colored(header, BOLD, CYAN))
    # 欄位寬度定義
    W_IDX, W_DATE, W_FID, W_TITLE, W_DIFF, W_STATUS = 4, 12, 6, 35, 8, 6
    table_w = 2 + W_IDX + 1 + W_DATE + 1 + W_FID + 1 + W_TITLE + 1 + W_DIFF + 1 + W_STATUS + 2

    sep = colored("─" * table_w, DIM)
    print(sep)
    print(
        "  " + pad("#", W_IDX) + " "
        + pad("日期", W_DATE) + " "
        + pad("題號", W_FID) + " "
        + pad("題目", W_TITLE) + " "
        + pad("難度", W_DIFF) + " "
        + "狀態"
    )
    print(sep)

    for i, h in enumerate(records, 1):
        diff = h.get("difficulty", "?")
        diff_c = DIFF_COLORS.get(diff, WHITE)
        title = h.get("title", "?")
        # 截斷過長的標題（考慮全形字元）
        if display_width(title) > W_TITLE - 2:
            while display_width(title + "...") > W_TITLE:
                title = title[:-1]
            title = title + "..."
        solved = h.get("solved_date")
        status = colored("✓ 完成", GREEN) if solved else colored("✗ 未完成", DIM)
        review_mark = colored(" ★", CYAN) if h.get("review") else ""
        print(
            "  " + pad(str(i), W_IDX) + " "
            + pad(h.get("picked_date", "?"), W_DATE) + " "
            + pad(h.get("frontend_id", "?"), W_FID) + " "
            + pad(title, W_TITLE) + " "
            + colored(pad(diff, W_DIFF), diff_c) + " "
            + status
            + review_mark
        )

    print(sep)
    print()


# ─── 主程式入口 ──────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="leet",
        description="LeetPicker - 定時挑選 LeetCode 題目的 CLI 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令：
  today     顯示今日題目（根據頻率自動判斷是否換題）
  pick      立即強制挑選新題目（會詢問當前題目是否完成）
  solved    將當前題目標記為已完成
  review    標記題目為需要複習（pick 時有 30% 機率抽到複習題）
  config    查看或修改設定
  status    查看目前狀態與當前題目
  history   查看歷史紀錄（含完成狀態）
  bot       Telegram 推播通知設定

範例：
  leet                           # 取得今日題目
  leet pick                      # 立即選新題
  leet solved                    # 標記今日題目為完成
  leet solved 42                 # 標記題號 42 為完成
  leet review                    # 標記當前題目為複習
  leet review 42                 # 標記題號 42 為複習
  leet review 42 -r              # 移除題號 42 的複習標記
  leet config -d easy,medium     # 設定難度為 Easy + Medium
  leet config -f 7               # 設定頻率為每週
  leet history -n 10             # 查看最近 10 筆（日期由新到舊）
  leet history -r                # 只顯示複習題
  leet history -s difficulty     # 依難度排序（Hard 優先）
  leet history -s id -a          # 依題號排序，顯示全部
  leet bot setup <token>         # 設定 Telegram 推播（互動式）
  leet bot test                  # 發送測試通知
  leet bot status                # 查看 Telegram 設定狀態
        """,
    )
    sub = parser.add_subparsers(dest="cmd")

    # today
    sub.add_parser("today", help="顯示今日題目")

    # pick
    sub.add_parser("pick", help="立即強制挑選新題目")

    # config
    p_config = sub.add_parser("config", help="查看或修改設定")
    p_config.add_argument(
        "-d", "--difficulty",
        metavar="LEVEL",
        help="難度：easy / medium / hard / all（逗號分隔可多選）",
    )
    p_config.add_argument(
        "-f", "--frequency",
        metavar="DAYS",
        type=int,
        help="頻率（天數）：1=每天、2=每兩天、7=每週",
    )

    # solved
    p_solved = sub.add_parser("solved", help="將題目標記為已完成")
    p_solved.add_argument("problem_id", nargs="?", type=int, help="題號（不填則標記今日題目）")

    # review
    p_review = sub.add_parser("review", help="標記題目為需要複習")
    p_review.add_argument("problem_id", nargs="?", type=int, help="題號（不填則標記當前題目）")
    p_review.add_argument("-r", "--remove", action="store_true", help="移除複習標記")

    # bot
    p_bot = sub.add_parser("bot", help="Telegram 推播通知設定")
    p_bot.add_argument(
        "bot_cmd",
        choices=["setup", "test", "status"],
        help="操作：setup 設定 token、test 測試通知、status 查看狀態",
    )
    p_bot.add_argument("token", nargs="?", help="Bot token（setup 時使用）")

    # status
    sub.add_parser("status", help="查看目前狀態與當前題目")

    # history
    p_hist = sub.add_parser("history", help="查看歷史紀錄")
    p_hist.add_argument("-n", "--limit", type=int, default=20, help="顯示幾筆（預設 20）")
    p_hist.add_argument("-a", "--all", action="store_true", help="顯示全部紀錄")
    p_hist.add_argument("-r", "--review", action="store_true", help="只顯示標記為複習的題目")
    p_hist.add_argument(
        "-s", "--sort",
        choices=["date", "date-asc", "difficulty", "id"],
        default="date",
        metavar="ORDER",
        help="排序方式：date（新→舊，預設）/ date-asc（舊→新）/ difficulty（Hard→Easy）/ id（題號）",
    )

    return parser


COMMANDS = {
    "today":   cmd_today,
    "pick":    cmd_pick,
    "solved":  cmd_solved,
    "review":  cmd_review,
    "config":  cmd_config,
    "status":  cmd_status,
    "history": cmd_history,
    "bot":     cmd_bot,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    handler = COMMANDS.get(args.cmd, cmd_today)
    handler(args)


if __name__ == "__main__":
    main()
