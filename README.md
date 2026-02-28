# Leet-Picker

定時挑選 LeetCode 題目的 CLI 工具，支援 Telegram 推播通知。純 Python 標準函式庫，無需安裝外部套件。

---

## 安裝

### 方式一：直接執行（目前使用方式）

不需安裝，直接用 Python 執行：

```bash
python3 leet.py today
python3 leet.py pick
python3 leet.py bot setup <token>
```

若想省略 `python3 leet.py`，可加 shell alias：

```bash
# 加到 ~/.zshrc 或 ~/.bashrc
alias leet="python3 /path/to/leet.py"
```

### 方式二：pip 安裝（使用 `leet` 指令）

```bash
pip install -e .
```

安裝後可直接使用 `leet` 指令，不需加 `python3 leet.py` 前綴。

---

## 指令總覽

```
leet                           取得今日題目（預設行為）
leet today                     同上
leet pick                      立即強制換新題（會詢問當前題目是否完成）
leet solved                    標記今日題目為完成
leet solved 42                 標記題號 42 為完成
leet review                    標記當前題目為需要複習
leet review 42                 標記題號 42 為複習
leet review 42 -r              移除題號 42 的複習標記
leet config                    查看目前設定
leet config -d easy,medium     設定難度為 Easy + Medium
leet config -f 7               設定頻率為每 7 天
leet status                    查看目前狀態與當前題目
leet history                   查看最近 20 筆歷史紀錄
leet history -n 10             查看最近 10 筆
leet history -a                查看全部
leet history -r                只顯示複習題
leet history -s difficulty     依難度排序（Hard 優先）
leet history -s id             依題號排序
leet bot setup <token>         設定 Telegram 推播（互動式）
leet bot test                  發送測試通知
leet bot status                查看 Telegram 設定狀態
```

---

## 設定檔路徑

所有資料存放於 `~/.config/leetpicker/`：

| 檔案 | 用途 |
|------|------|
| `config.json` | 難度、頻率、當前題目、Telegram token / chat_id |
| `history.json` | 所有選題紀錄（含完成與複習標記） |
| `problems_cache.json` | LeetCode 題目快取（每日自動更新） |

---

## Telegram 推播設定

### 1. 建立 Bot

前往 Telegram 搜尋 **@BotFather**，傳送 `/newbot`，依提示建立 bot 並取得 token。

### 2. 執行 Setup

```bash
leet bot setup <token>
```

驗證 token 後，程式會等待你在 Telegram 傳任意訊息給 bot，自動偵測並儲存你的 chat_id。

### 3. 測試

```bash
leet bot test
```

Telegram 收到訊息即代表設定成功。

### 4. 通知觸發時機

`leet pick` 或 `leet today` **換題時**自動發送，未換題（頻率未到）則不發送。

---

## 自動排程（crontab）

讓系統每天固定時間自動執行 `leet today`，到期就換題並推播。

```bash
crontab -e
```

加入以下這行（每天晚上 8 點執行）：

```
0 20 * * * /path/to/python3 /path/to/leet.py today
```

> 實際路徑在執行 `leet bot setup` 完成後會自動印出，直接複製貼上即可。

**注意：** 系統睡眠期間排程不會執行，但不影響結果——`leet today` 內建頻率判斷，下次執行時若距上次換題已超過設定天數，一樣會換題並推播。

---

## 題目難度與頻率設定

```bash
leet config -d easy,medium    # 只選 Easy 和 Medium
leet config -d hard           # 只選 Hard
leet config -d all            # 全難度（預設）
leet config -f 1              # 每天換題（預設）
leet config -f 3              # 每 3 天換題
leet config -f 7              # 每週換題
```

---

## 複習機制

標記為複習的題目，在 `leet pick` 時有 **30% 機率**被抽到：

```bash
leet review          # 標記當前題目
leet review 42       # 標記指定題號
leet review 42 -r    # 移除複習標記
leet history -r      # 查看所有複習題
```
