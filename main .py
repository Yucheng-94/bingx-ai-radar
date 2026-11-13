import os
import time
import json
import logging
import math
import tempfile
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from datetime import datetime, timezone, timedelta


# ============================================================
# BingX AI 小幣雷達
# 穩定掃描版
# ============================================================

程式版本 = "3.1"



本金 = 100.0

單筆風險 = 1.0

預設槓桿 = 2
最高槓桿 = 5

最高保證金 = 20.0

最低幣價 = 0.1
最高幣價 = 0.9999

每次掃描數量 = 5
異動門檻百分比 = 1.0
行情紀錄鍵 = "_ticker_snapshot"
行情比較最長秒數 = 3600

掃描間隔 = 900

API_TIMEOUT = 10

API_RETRY = 3

API_RETRY_BASE_SLEEP = 2.0

API_MIN_INTERVAL = 1.05



# ============================================================
# 2. 排除幣種
# ============================================================

排除幣種 = {
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "DOGE",
    "ADA",
    "TRX",
    "LTC",
    "BCH",
    "DOT",
    "LINK",
    "AVAX",
    "TON",
}


# ============================================================
# 3. BingX API
# ============================================================

網址 = "https://open-api.bingx.com"

時區 = timezone(
    timedelta(hours=8)
)


# ============================================================
# 4. Telegram
# ============================================================

TG_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TG_CHAT = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# 5. 狀態紀錄
# ============================================================

紀錄檔 = "state.json"


# ============================================================
# 6. Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


# ============================================================
# 7. HTTP Session
# ============================================================



最後API請求時間 = 0.0


# ============================================================
# 8. 時間
# ============================================================

def 現在時間():

    return datetime.now(
        時區
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# 9. 安全轉數字
# ============================================================

def 轉Float(value, 預設=None):
    if isinstance(value, bool):
        return 預設
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 預設
    return number if math.isfinite(number) else 預設


class 行情暫缺(RuntimeError):
    pass

def API等待():

    global 最後API請求時間

    現在 = time.monotonic()

    經過 = 現在 - 最後API請求時間

    if 經過 < API_MIN_INTERVAL:

        time.sleep(
            API_MIN_INTERVAL - 經過
        )


# ============================================================
# 11. API 請求
# ============================================================

def 取得資料(path, params=None):
    global 最後API請求時間
    query = "?" + urlencode(params) if params else ""
    request = Request(
        網址 + path + query,
        headers={"Accept": "application/json", "User-Agent": "BingX-Market-Radar/3.1"},
    )
    for attempt in range(1, API_RETRY + 1):
        delay = API_RETRY_BASE_SLEEP * 2 ** (attempt - 1)
        API等待()
        最後API請求時間 = time.monotonic()
        try:
            with urlopen(request, timeout=API_TIMEOUT) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise ValueError("回應格式異常")
            code = str(result.get("code"))
            if code != "0":
                raise ValueError(f"BingX {code} {str(result.get('msg', ''))[:160]}")
            if result.get("data") is None:
                raise ValueError("回應缺少行情資料")
            return result["data"]
        except HTTPError as exc:
            detail = f"HTTP {exc.code}"
            retry_after = 轉Float(exc.headers.get("Retry-After"), 0)
            exc.close()
            if exc.code not in {408, 429} and exc.code < 500:
                raise 行情暫缺(f"{path} {detail}") from exc
            if retry_after > 60:
                raise 行情暫缺(f"{path} {detail}，服務要求稍後再試") from exc
            delay = max(delay, retry_after)
        except (URLError, OSError, ValueError, HTTPException) as exc:
            detail = str(exc)[:200]
        if attempt < API_RETRY:
            time.sleep(delay)
    raise 行情暫缺(f"{path} {detail}")

def 傳送通知(message):
    print(message)
    if not TG_TOKEN or not TG_CHAT:
        return False

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    request = Request(
        url,
        data=json.dumps({"chat_id": TG_CHAT, "text": message}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=API_TIMEOUT) as response:
            result = json.load(response)
        if isinstance(result, dict) and result.get("ok") is True:
            return True
        logging.warning("Telegram 未確認送達，報告已輸出至執行記錄")
    except HTTPError as exc:
        logging.warning("Telegram HTTP %s，報告已輸出至執行記錄", exc.code)
        exc.close()
    except (URLError, OSError, ValueError, HTTPException) as exc:
        logging.warning("Telegram 未確認送達（%s），報告已輸出至執行記錄", type(exc).__name__)
    return False

def 讀取紀錄():

    if not os.path.exists(
        紀錄檔
    ):

        return {}

    try:

        with open(
            紀錄檔,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            dict
        ):

            return data

        logging.warning(
            "state.json不是dict，重新建立"
        )

        return {}

    except Exception as e:

        logging.warning(
            "讀取state.json失敗：%s",
            str(e)
        )

        return {}


# ============================================================
# 14. 安全儲存 State
# ============================================================

def 儲存紀錄(data):
    destination = os.path.abspath(紀錄檔)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=os.path.dirname(destination),
            prefix=".radar-state-", delete=False,
        ) as file:
            temporary = file.name
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def 計算EMA(
    values,
    period
):

    if not values:

        return []

    if period <= 0:

        raise ValueError(
            "EMA period必須大於0"
        )

    alpha = (
        2 / (period + 1)
    )

    result = [
        float(values[0])
    ]

    for value in values[1:]:

        value = float(value)

        result.append(
            alpha * value
            + (1 - alpha)
            * result[-1]
        )

    return result


# ============================================================
# 16. RSI
# ============================================================

def 計算RSI(
    values,
    period=14
):

    if len(values) < period + 1:

        raise ValueError(
            "RSI資料不足"
        )

    changes = []

    for i in range(
        1,
        len(values)
    ):

        changes.append(
            float(values[i])
            - float(values[i - 1])
        )

    gains = [
        max(x, 0)
        for x in changes
    ]

    losses = [
        max(-x, 0)
        for x in changes
    ]

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(changes)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:

        if avg_gain == 0:

            return 50.0

        return 100.0

    rs = (
        avg_gain / avg_loss
    )

    return (
        100
        - (
            100 / (1 + rs)
        )
    )


# ============================================================
# 17. K線解析
# ============================================================

def 解析K線(data):

    if not isinstance(
        data,
        list
    ):

        return None

    rows = []

    for x in data:

        try:

            if isinstance(
                x,
                dict
            ):

                timestamp = (
                    x.get("time")
                    or x.get("timestamp")
                    or x.get("openTime")
                    or x.get("open_time")
                    or 0
                )

                o = 轉Float(
                    x.get("open")
                )

                h = 轉Float(
                    x.get("high")
                )

                l = 轉Float(
                    x.get("low")
                )

                c = 轉Float(
                    x.get("close")
                )

                v = 轉Float(
                    x.get("volume")
                )

                buy = 轉Float(
                    x.get(
                        "takerBuyBaseVolume"
                    ),
                    None
                )

                if buy is None:

                    buy = (
                        v / 2
                        if v is not None
                        else 0
                    )

            elif isinstance(
                x,
                (list, tuple)
            ):

                if len(x) < 6:

                    continue

                timestamp = x[0]

                o = 轉Float(
                    x[1]
                )

                h = 轉Float(
                    x[2]
                )

                l = 轉Float(
                    x[3]
                )

                c = 轉Float(
                    x[4]
                )

                v = 轉Float(
                    x[5]
                )

                if len(x) > 9:

                    buy = 轉Float(
                        x[9],
                        None
                    )

                else:

                    buy = None

                if buy is None:

                    buy = (
                        v / 2
                        if v is not None
                        else 0
                    )

            else:

                continue

            if (
                o is None
                or h is None
                or l is None
                or c is None
                or v is None
                or buy is None
            ):

                continue

            if (
                o <= 0
                or h <= 0
                or l <= 0
                or c <= 0
                or v < 0
                or buy < 0
            ):

                continue

            if h < l or buy > v:

                continue

            if not (
                l <= o <= h
                and l <= c <= h
            ):

                continue

            timestamp_value = (
                轉Float(
                    timestamp,
                    0
                )
            )

            if timestamp_value <= 0:
                continue

            rows.append({
                "time": timestamp_value,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "buy": buy,
            })

        except Exception:

            continue

    if len(rows) < 30:

        return None

    # 依時間排序
    rows.sort(
        key=lambda x: x["time"]
    )

    # 移除重複時間
    unique = {}

    for row in rows:

        unique[
            row["time"]
        ] = row

    rows = list(
        unique.values()
    )

    rows.sort(
        key=lambda x: x["time"]
    )

    if len(rows) < 30:

        return None

    return {
        "time": [
            x["time"]
            for x in rows
        ],
        "open": [
            x["open"]
            for x in rows
        ],
        "high": [
            x["high"]
            for x in rows
        ],
        "low": [
            x["low"]
            for x in rows
        ],
        "close": [
            x["close"]
            for x in rows
        ],
        "volume": [
            x["volume"]
            for x in rows
        ],
        "buy": [
            x["buy"]
            for x in rows
        ],
    }


# ============================================================
# 18. 取得K線
# ============================================================

def 取得K線(
    symbol,
    interval
):

    data = 取得資料(
        "/openApi/swap/v3/quote/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": 100
        }
    )

    if isinstance(
        data,
        dict
    ):

        data = (
            data.get("data")
            or data.get("list")
            or []
        )

    return 解析K線(data)


# ============================================================
# 19. K線技術分析
# ============================================================

def 分析K線(k):

    if not k:

        raise ValueError(
            "K線資料為空"
        )

    close = k["close"]
    high = k["high"]
    low = k["low"]
    volume = k["volume"]
    buy = k["buy"]

    if len(close) < 30:

        raise ValueError(
            "技術分析資料不足"
        )

    ema7 = 計算EMA(
        close,
        7
    )

    ema25 = 計算EMA(
        close,
        25
    )

    rsi = 計算RSI(
        close,
        14
    )

    if len(volume) < 21:

        raise ValueError(
            "成交量資料不足"
        )

    成交平均 = (
        sum(volume[-21:-1])
        / 20
    )

    if 成交平均 > 0:

        成交倍數 = (
            volume[-1]
            / 成交平均
        )

    else:

        成交倍數 = 1.0

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------

    true_ranges = []

    for i in range(
        1,
        len(close)
    ):

        tr = max(
            high[i] - low[i],
            abs(
                high[i]
                - close[i - 1]
            ),
            abs(
                low[i]
                - close[i - 1]
            )
        )

        true_ranges.append(tr)

    if len(true_ranges) < 14:

        raise ValueError(
            "ATR資料不足"
        )

    atr = (
        sum(
            true_ranges[-14:]
        )
        / 14
    )

    # --------------------------------------------------------
    # 支撐壓力
    # --------------------------------------------------------

    支撐 = min(
        low[-20:]
    )

    壓力 = max(
        high[-20:]
    )

    # --------------------------------------------------------
    # 買盤比例
    # --------------------------------------------------------

    if volume[-1] > 0:

        買盤比例 = (
            buy[-1]
            / volume[-1]
        )

    else:

        買盤比例 = 0.5

    買盤比例 = max(
        0.0,
        min(
            1.0,
            買盤比例
        )
    )

    # --------------------------------------------------------
    # 分數
    # --------------------------------------------------------

    分數 = 0

    if ema7[-1] > ema25[-1]:

        分數 += 1

    elif ema7[-1] < ema25[-1]:

        分數 -= 1

    if close[-1] > ema7[-1]:

        分數 += 1

    elif close[-1] < ema7[-1]:

        分數 -= 1

    if rsi < 35:

        分數 += 1

    elif rsi > 70:

        分數 -= 1

    if 成交倍數 > 1.5:

        if 買盤比例 > 0.55:

            分數 += 1

        elif 買盤比例 < 0.45:

            分數 -= 1

    return {
        "分數": float(分數),
        "RSI": float(rsi),
        "EMA7": float(ema7[-1]),
        "EMA25": float(ema25[-1]),
        "支撐": float(支撐),
        "壓力": float(壓力),
        "ATR": float(atr),
        "成交倍數": float(成交倍數),
        "買盤比例": float(買盤比例),
    }


# ============================================================
# 20. 持倉量 OI
# ============================================================

def 取得持倉量(symbol):

    data = 取得資料(
        "/openApi/swap/v2/quote/openInterest",
        {
            "symbol": symbol
        }
    )

    # BingX不同回傳形式容錯
    if isinstance(
        data,
        list
    ):

        if not data:

            raise ValueError(
                "OI資料為空"
            )

        data = data[0]

    elif isinstance(
        data,
        dict
    ):

        # 某些回傳可能再包一層data
        if isinstance(
            data.get("data"),
            list
        ):

            if not data["data"]:

                raise ValueError(
                    "OI內層資料為空"
                )

            data = data["data"][0]

        elif isinstance(
            data.get("data"),
            dict
        ):

            data = data["data"]

    if not isinstance(
        data,
        dict
    ):

        raise ValueError(
            "OI格式錯誤"
        )

    value = (
        data.get("openInterest")
        if data.get("openInterest")
        is not None
        else data.get(
            "openInterestAmount"
        )
    )

    value = 轉Float(
        value
    )

    if value is None:

        raise ValueError(
            "找不到OI欄位"
        )

    if value < 0:

        raise ValueError(
            "OI數值無效"
        )

    return value


# ============================================================
# 21. 買賣盤深度
# ============================================================

def 取得買賣掛單(symbol):

    data = 取得資料(
        "/openApi/swap/v2/quote/depth",
        {
            "symbol": symbol,
            "limit": 20
        }
    )

    if isinstance(
        data,
        dict
    ):

        if isinstance(
            data.get("data"),
            dict
        ):

            data = data["data"]

    if not isinstance(
        data,
        dict
    ):

        raise ValueError(
            "深度資料格式錯誤"
        )

    bids = data.get(
        "bids",
        []
    )

    asks = data.get(
        "asks",
        []
    )

    def 計算掛單總額(
        items
    ):

        total = 0.0

        if not isinstance(
            items,
            list
        ):

            return 0.0

        for x in items:

            try:

                if isinstance(
                    x,
                    dict
                ):

                    price = 轉Float(
                        x.get("price")
                    )

                    amount = 轉Float(
                        x.get(
                            "quantity",
                            x.get(
                                "qty",
                                x.get(
                                    "amount",
                                    0
                                )
                            )
                        )
                    )

                elif isinstance(
                    x,
                    (list, tuple)
                ):

                    if len(x) < 2:

                        continue

                    price = 轉Float(
                        x[0]
                    )

                    amount = 轉Float(
                        x[1]
                    )

                else:

                    continue

                if (
                    price is None
                    or amount is None
                ):

                    continue

                if (
                    price <= 0
                    or amount < 0
                ):

                    continue

                total += (
                    price * amount
                )

            except Exception:

                continue

        return total

    買單 = 計算掛單總額(
        bids
    )

    賣單 = 計算掛單總額(
        asks
    )

    total = (
        買單 + 賣單
    )

    if not math.isfinite(total) or total <= 0 or not bids or not asks:
        raise ValueError("掛單深度不足")

    return (
        買單 / total
    )


# ============================================================
# 22. 合約清單
# ============================================================

def 行情清單(data, label):
    if isinstance(data, dict):
        data = data.get("data", data.get("list"))
    if not isinstance(data, list) or not any(isinstance(item, dict) for item in data):
        raise 行情暫缺(f"{label}暫無可用資料")
    return data


def 取得合約清單():
    data = 行情清單(取得資料("/openApi/swap/v2/quote/contracts"), "合約清單")
    contracts = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol.endswith("-USDT") or symbol[:-5] in 排除幣種:
            continue
        if str(item.get("status", "")).lower() not in {"1", "online", "normal", "trading", "open"}:
            continue
        if str(item.get("apiStateOpen", "")).lower() in {"false", "0"}:
            continue
        contracts[symbol] = item
    return contracts


def 取得Ticker():
    return 行情清單(取得資料("/openApi/swap/v2/quote/ticker"), "24 小時行情")


def 掃描幣種(state):
    contracts = 取得合約清單()
    candidates = {}
    for item in 取得Ticker():
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if symbol not in contracts:
            continue
        price = 轉Float(item.get("lastPrice"))
        volume = 轉Float(item.get("quoteVolume"))
        if price is None or not 最低幣價 <= price <= 最高幣價:
            continue
        if volume is None or volume <= 0:
            continue
        close_time = 轉Float(item.get("closeTime"), 0)
        raw_precision = str(contracts[symbol].get("pricePrecision", ""))
        if raw_precision.isdigit() and len(raw_precision) <= 2 and int(raw_precision) <= 18:
            precision = int(raw_precision)
        else:
            precision = len(str(item.get("lastPrice")).partition(".")[2].rstrip("0"))
        candidate = dict(symbol=symbol, lastPrice=price, quoteVolume=volume,
                         precision=precision + 1)
        previous = candidates.get(symbol)
        if previous is None or (close_time, volume) > (previous[0], previous[1]["quoteVolume"]):
            candidates[symbol] = (close_time, candidate)
    now = time.time()
    previous = state.get(行情紀錄鍵, {})
    if not isinstance(previous, dict):
        previous = {}
    age = now - 轉Float(previous.get("time"), 0)
    baseline = previous.get("prices")
    state[行情紀錄鍵] = {
        "time": now,
        "prices": {symbol: item["lastPrice"] for symbol, (_, item) in candidates.items()},
    }
    if not isinstance(baseline, dict) or not 0 < age <= 行情比較最長秒數:
        return None

    movers = []
    for symbol, (_, item) in candidates.items():
        old_price = 轉Float(baseline.get(symbol), 0)
        if old_price <= 0:
            continue
        change = (item["lastPrice"] - old_price) / old_price * 100
        if abs(change) >= 異動門檻百分比 - 1e-9:
            item["change"] = change
            movers.append(item)
    movers.sort(key=lambda item: (-abs(item["change"]), -item["quoteVolume"], item["symbol"]))
    return movers[:每次掃描數量]


def 計算下單(
    方向,
    進場,
    止損
):

    if (
        進場 is None
        or 止損 is None
    ):

        return None

    進場 = float(
        進場
    )

    止損 = float(
        止損
    )

    if (
        進場 <= 0
        or 止損 <= 0
    ):

        return None

    距離 = abs(
        進場 - 止損
    )

    if 距離 <= 0:

        return None

    距離比例 = (
        距離 / 進場
    )

    if 距離比例 <= 0:

        return None

    理論合約金額 = (
        單筆風險
        / 距離比例
    )

    槓桿 = min(
        預設槓桿,
        最高槓桿
    )

    可用保證金 = min(
        最高保證金,
        本金
    )

    合約金額上限 = (
        可用保證金
        * 槓桿
    )

    合約金額 = min(
        理論合約金額,
        合約金額上限
    )

    保證金 = (
        合約金額
        / 槓桿
    )

    預估虧損 = (
        合約金額
        * 距離比例
    )

    return {
        "槓桿": 槓桿,
        "保證金": 保證金,
        "合約金額": 合約金額,
        "預估虧損": 預估虧損,
        "風險比例": (
            距離比例 * 100
        ),
    } # ============================================================
# 26. 綜合分析
# ============================================================

def 分析幣種(
    symbol,
    price,
    k15,
    k1h,
    k4h,
    state
):

    # --------------------------------------------------------
    # 技術分析
    # --------------------------------------------------------

    a15 = 分析K線(
        k15
    )

    a1h = 分析K線(
        k1h
    )

    a4h = 分析K線(
        k4h
    )

    # --------------------------------------------------------
    # OI
    # --------------------------------------------------------

    oi = None

    try:

        oi = 取得持倉量(
            symbol
        )

    except (行情暫缺, ValueError) as e:

        logging.info(
            "%s 持倉資料暫缺：%s",
            symbol,
            str(e)
        )

    # --------------------------------------------------------
    # Order Book
    # --------------------------------------------------------

    book = None

    try:

        book = 取得買賣掛單(
            symbol
        )

    except (行情暫缺, ValueError) as e:

        logging.info(
            "%s 掛單資料暫缺：%s",
            symbol,
            str(e)
        )

    # --------------------------------------------------------
    # OI歷史比較
    # --------------------------------------------------------

    old = None

    old_data = state.get(
        symbol,
        {}
    )

    if isinstance(
        old_data,
        dict
    ):

        old = 轉Float(
            old_data.get(
                "oi"
            ),
            None
        )

    oi_change = 0.0

    if (
        oi is not None
        and old is not None
        and old > 0
    ):

        oi_change = (
            (
                oi / old
            ) - 1
        ) * 100

    # --------------------------------------------------------
    # 更新狀態
    # --------------------------------------------------------

    if oi is not None:

        state[symbol] = {
            "oi": oi,
            "time": 現在時間()
        }

    # --------------------------------------------------------
    # 多週期分數
    # --------------------------------------------------------

    分數 = (
        a15["分數"] * 1.5
        + a1h["分數"] * 1.5
        + a4h["分數"]
    )

    # --------------------------------------------------------
    # OI + 深度
    # --------------------------------------------------------

    if oi is not None and book is not None:

        if (
            oi_change > 1
            and book > 0.55
        ):

            分數 += 1

        elif (
            oi_change > 1
            and book < 0.45
        ):

            分數 -= 1

    # --------------------------------------------------------
    # 趨勢判斷
    # --------------------------------------------------------

    if 分數 >= 3:

        方向 = "偏向上漲"

        動作 = "觀察做多"

        進場 = max(
            a15["支撐"],
            price
            - a15["ATR"] * 0.3
        )

        止損 = (
            進場
            - a15["ATR"] * 1.5
        )

        止盈1 = (
            進場
            + (
                進場 - 止損
            ) * 2
        )

        止盈2 = (
            進場
            + (
                進場 - 止損
            ) * 3
        )

    elif 分數 <= -3:

        方向 = "偏向下跌"

        動作 = "觀察做空"

        進場 = min(
            a15["壓力"],
            price
            + a15["ATR"] * 0.3
        )

        止損 = (
            進場
            + a15["ATR"] * 1.5
        )

        止盈1 = (
            進場
            - (
                止損 - 進場
            ) * 2
        )

        止盈2 = (
            進場
            - (
                止損 - 進場
            ) * 3
        )

    else:

        方向 = "目前方向不明"

        動作 = "繼續觀望"

        進場 = None
        止損 = None
        止盈1 = None
        止盈2 = None

    # --------------------------------------------------------
    # 驗證價格邏輯
    # --------------------------------------------------------

    if 進場 is not None:

        if (
            not all(
                x is not None
                for x in [
                    進場,
                    止損,
                    止盈1,
                    止盈2
                ]
            )
        ):

            進場 = None
            止損 = None
            止盈1 = None
            止盈2 = None

        elif 方向 == "偏向上漲":

            if not (
                0 < 止損 < 進場
                < 止盈1
                < 止盈2
            ):

                進場 = None
                止損 = None
                止盈1 = None
                止盈2 = None

        elif 方向 == "偏向下跌":

            if not (
                止損 > 進場
                > 止盈1
                > 止盈2 > 0
            ):

                進場 = None
                止損 = None
                止盈1 = None
                止盈2 = None

    # --------------------------------------------------------
    # 下單風險
    # --------------------------------------------------------

    if 進場 is None:
        動作 = "繼續觀望"

    下單 = None

    if (
        進場 is not None
        and 止損 is not None
    ):

        下單 = 計算下單(
            方向,
            進場,
            止損
        )

    # --------------------------------------------------------
    # OI說明
    # --------------------------------------------------------

    if oi is None:

        oi_text = (
            "OI資料暫時無法取得"
        )

    elif old is None or old <= 0:

        oi_text = (
            "首次紀錄，等待下次比較"
        )

    elif oi_change > 1:

        oi_text = (
            "持倉增加，可能有新倉進入"
        )

    elif oi_change < -1:

        oi_text = (
            "持倉減少，可能有倉位退出"
        )

    else:

        oi_text = (
            "持倉變化不明顯"
        )

    # --------------------------------------------------------
    # 深度說明
    # --------------------------------------------------------

    if book is None:
        book_text = "掛單深度暫缺"
    elif book > 0.60:

        book_text = (
            "買單較強"
        )

    elif book < 0.40:

        book_text = (
            "賣單較強"
        )

    else:

        book_text = (
            "買賣力量接近"
        )

    return {
        "symbol": symbol,
        "price": float(price),
        "方向": 方向,
        "動作": 動作,
        "分數": float(分數),
        "RSI": float(
            a15["RSI"]
        ),
        "支撐": float(
            a15["支撐"]
        ),
        "壓力": float(
            a15["壓力"]
        ),
        "成交倍數": float(
            a15["成交倍數"]
        ),
        "持倉變化": float(
            oi_change
        ),
        "持倉說明": oi_text,
        "掛單說明": book_text,
        "進場": 進場,
        "止損": 止損,
        "止盈1": 止盈1,
        "止盈2": 止盈2,
        "下單": 下單,
    }


# ============================================================
# 27. 結果格式化
# ============================================================

def 格式化結果(r):
    precision = r["precision"]

    message = (
        f"\n🪙 幣種：{r['symbol']}\n"
        f"💵 現價：{r['price']:.{precision}f}\n"
        f"⚡ 較上次掃描：{r['change']:+.2f}%\n"
        f"📊 方向：{r['方向']}\n"
        f"🎯 建議：{r['動作']}\n"
        f"📈 分析分數：{r['分數']:.1f}\n"
        f"📉 RSI：{r['RSI']:.1f}\n"
        f"🟢 可能支撐：{r['支撐']:.{precision}f}\n"
        f"🔴 可能壓力：{r['壓力']:.{precision}f}\n"
        f"📦 成交量：{r['成交倍數']:.2f}倍\n"
        f"🐋 持倉：{r['持倉說明']}\n"
        f"📚 買賣掛單：{r['掛單說明']}\n"
    )

    if (
        r["進場"] is not None
        and r["下單"] is not None
    ):

        o = r["下單"]

        message += (
            "\n📍 參考進場："
            f"{r['進場']:.{precision}f}\n"

            f"🛑 參考止損："
            f"{r['止損']:.{precision}f}\n"

            f"🎯 第一止盈："
            f"{r['止盈1']:.{precision}f}\n"

            f"🎯 第二止盈："
            f"{r['止盈2']:.{precision}f}\n"

            f"⚖️ 建議槓桿："
            f"{o['槓桿']}倍\n"

            f"💰 建議保證金："
            f"{o['保證金']:.2f} USDT\n"

            f"📦 合約總金額："
            f"{o['合約金額']:.2f} USDT\n"

            f"⚠️ 預估止損虧損："
            f"{o['預估虧損']:.2f} USDT\n"
        )

    return message


# ============================================================
# 28. Telegram報告
# ============================================================

def 傳送報告(results, scanned, unavailable):
    ranked = results
    message = (
        "🔍 BingX AI小幣雷達\n"
        f"🕒 {現在時間()}（台灣時間）\n"
        f"💰 本金 {本金:.2f} USDT｜單筆風險 {單筆風險:.2f} USDT\n"
        f"🔎 掃描 {scanned}/{每次掃描數量} 檔｜有效分析 {len(ranked)} 檔\n"
    )
    for result in ranked:
        message += "━━━━━━━━━━━━━━\n" + 格式化結果(result)
    if unavailable:
        message += "\n行情暫缺：" + "、".join(unavailable) + "\n"
    if not scanned:
        message += "\n本輪沒有達到異動門檻的合約。\n"
    if ranked:
        message += "\n📌 只提供分析。估算未計入手續費、滑價與資金費率。"
    傳送通知(message)


def 分析單一幣種(item, state):
    symbol = item["symbol"]
    candles = []
    for interval in ("15m", "1h", "4h"):
        try:
            data = 取得K線(symbol, interval)
        except 行情暫缺 as exc:
            raise 行情暫缺(f"{interval} K 線暫缺：{exc}") from exc
        if data is None:
            raise 行情暫缺(f"{interval} 有效 K 線不足 30 根")
        candles.append(data)
    result = 分析幣種(symbol, item["lastPrice"], *candles, state)
    result.update(precision=item["precision"], change=item["change"])
    return result


def main():
    logging.info("開始掃描 %s", 現在時間())
    state = 讀取紀錄()
    try:
        candidates = 掃描幣種(state)
    except 行情暫缺 as exc:
        logging.warning("本輪行情暫缺：%s", exc)
        傳送通知(f"🔍 BingX AI小幣雷達\n{現在時間()}\n行情暫缺，本輪未產生分析。")
        return

    results = []
    unavailable = []
    for item in candidates or []:
        symbol = item["symbol"]
        try:
            results.append(分析單一幣種(item, state))
        except 行情暫缺 as exc:
            logging.info("%s %s", symbol, exc)
            unavailable.append(symbol)
    try:
        儲存紀錄(state)
    except OSError as exc:
        logging.warning("本輪行情紀錄未能寫入：%s", exc)
        raise
    if candidates is None:
        傳送通知(f"🔍 BingX AI小幣雷達\n{現在時間()}\n已建立行情基準，下輪開始比對異動。")
        return
    傳送報告(results, len(candidates), unavailable)

def 啟動():

    print("=" * 60)

    print(
        "BingX AI小幣雷達啟動"
    )

    print(
        "版本：",
        程式版本
    )

    print(
        "本金：",
        本金,
        "USDT"
    )

    print(
        "單筆風險：",
        單筆風險,
        "USDT"
    )

    print(
        "預設槓桿：",
        預設槓桿
    )

    print(
        "最高槓桿：",
        最高槓桿
    )

    print(
        "最高保證金：",
        最高保證金,
        "USDT"
    )

    print(
        "最低幣價：",
        最低幣價
    )

    print(
        "最高幣價：",
        最高幣價
    )

    print(
        "每次掃描數量：",
        每次掃描數量
    )

    print(
        "掃描間隔：",
        掃描間隔,
        "秒"
    )

    print(
        "API最小間隔：",
        API_MIN_INTERVAL,
        "秒"
    )

    print(
        "Telegram：",
        "已設定"
        if TG_TOKEN and TG_CHAT
        else "未設定"
    )

    print("=" * 60)

    while True:

        開始時間 = time.monotonic()

        try:

            main()

        except KeyboardInterrupt:

            print(
                "使用者停止程式"
            )

            break

        except Exception as e:

            logging.exception(
                "主程式發生未預期錯誤：%s",
                str(e)
            )

            # 主程式即使發生未預期錯誤，
            # 也不要讓整個循環直接消失。

            try:

                傳送通知(
                    "⚠️ BingX主程式發生未預期錯誤\n"
                    f"時間：{現在時間()}\n"
                    f"錯誤：{str(e)[:800]}"
                )

            except Exception:

                pass

        執行時間 = (
            time.monotonic()
            - 開始時間
        )

        等待時間 = max(
            5,
            掃描間隔
            - 執行時間
        )

        print(
            f"本輪執行時間："
            f"{執行時間:.1f} 秒"
        )

        print(
            f"下次掃描約在 "
            f"{等待時間:.0f} 秒後"
        )

        try:

            time.sleep(
                等待時間
            )

        except KeyboardInterrupt:

            print(
                "程式已停止"
            )

            break


# ============================================================
# 32. 程式入口
# ============================================================

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description="BingX AI 小幣雷達")
    parser.add_argument("--once", action="store_true", help="只執行一輪掃描")
    if parser.parse_args().once:
        main()
    else:
        啟動()
