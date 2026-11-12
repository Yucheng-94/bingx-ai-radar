import os
import time
import json
import logging
import traceback
import requests

from datetime import datetime, timezone, timedelta


# ============================================================
# BingX AI 小幣雷達
# 穩定掃描版
# ============================================================

程式版本 = "3.0-STABLE"

print("=" * 60)
print("BingX AI 小幣雷達")
print("版本：", 程式版本)

if "__file__" in globals():
    print("執行檔位置：", os.path.abspath(__file__))
else:
    print("執行環境：目前工作目錄")
    print("工作目錄：", os.getcwd())

print("目前時間：", datetime.now())
print("=" * 60)


# ============================================================
# 1. 基本設定
# ============================================================

本金 = 100.0

單筆風險 = 1.0

預設槓桿 = 2
最高槓桿 = 5

最高保證金 = 20.0

最低幣價 = 0.1
最高幣價 = 0.9999

每次掃描數量 = 5

掃描間隔 = 900

API_TIMEOUT = 20

API_RETRY = 5

API_RETRY_BASE_SLEEP = 2.0

API_MIN_INTERVAL = 0.35

報告最大幣種數 = 5


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

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "BingX-AI-Market-Radar/"
        + 程式版本
    ),
    "Accept": "application/json",
})


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

    try:

        if value is None:
            return 預設

        if isinstance(value, str):

            value = value.strip()

            if not value:
                return 預設

        return float(value)

    except Exception:

        return 預設


# ============================================================
# 10. API 限速
# ============================================================

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

def 取得資料(
    path,
    params=None
):

    global 最後API請求時間

    url = 網址 + path

    最後錯誤 = None

    for attempt in range(
        1,
        API_RETRY + 1
    ):

        try:

            API等待()

            response = session.get(
                url,
                params=params or {},
                timeout=API_TIMEOUT
            )

            最後API請求時間 = time.monotonic()

            print(
                f"API請求：{path} "
                f"HTTP={response.status_code}"
            )

            if response.status_code == 429:

                raise RuntimeError(
                    "HTTP 429 API限頻"
                )

            if response.status_code >= 500:

                raise RuntimeError(
                    f"HTTP {response.status_code}"
                )

            response.raise_for_status()

            try:

                result = response.json()

            except Exception as e:

                raise ValueError(
                    "API回傳不是有效JSON"
                ) from e

            if not isinstance(
                result,
                dict
            ):

                raise ValueError(
                    "API回傳格式不是dict"
                )

            code = result.get(
                "code"
            )

            msg = result.get(
                "msg",
                ""
            )

            if code is not None:

                if str(code) != "0":

                    raise RuntimeError(
                        f"BingX API錯誤 "
                        f"code={code} "
                        f"msg={msg}"
                    )

            if "data" not in result:

                raise ValueError(
                    f"API缺少data：{result}"
                )

            return result["data"]

        except Exception as e:

            最後錯誤 = e

            print(
                f"API失敗 "
                f"{attempt}/{API_RETRY}："
                f"{type(e).__name__}: {e}"
            )

            if attempt < API_RETRY:

                sleep_time = (
                    API_RETRY_BASE_SLEEP
                    * attempt
                )

                time.sleep(
                    sleep_time
                )

    raise RuntimeError(
        f"API最終失敗：{path}："
        f"{最後錯誤}"
    )


# ============================================================
# 12. Telegram
# ============================================================

def 傳送通知(message):

    if not TG_TOKEN or not TG_CHAT:

        print("=" * 60)
        print("Telegram尚未設定")
        print(message)
        print("=" * 60)

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TG_TOKEN}/sendMessage"
    )

    最大長度 = 3500

    chunks = [
        message[i:i + 最大長度]
        for i in range(
            0,
            len(message),
            最大長度
        )
    ]

    成功 = True

    for chunk in chunks:

        try:

            response = session.post(
                url,
                json={
                    "chat_id": TG_CHAT,
                    "text": chunk
                },
                timeout=20
            )

            response.raise_for_status()

            result = response.json()

            if not result.get("ok"):

                raise RuntimeError(
                    str(result)
                )

        except Exception as e:

            成功 = False

            logging.error(
                "Telegram傳送失敗：%s",
                str(e)
            )

    return 成功


# ============================================================
# 13. State
# ============================================================

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

    temp_file = (
        紀錄檔 + ".tmp"
    )

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            紀錄檔
        )

    except Exception:

        try:

            if os.path.exists(
                temp_file
            ):

                os.remove(
                    temp_file
                )

        except Exception:

            pass

        raise


# ============================================================
# 15. EMA
# ============================================================

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

            if h < l:

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

    return 解析K線(data) # ============================================================
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

    if atr <= 0:

        raise ValueError(
            "ATR無效"
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

    else:

        分數 -= 1

    if close[-1] > ema7[-1]:

        分數 += 1

    else:

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

    if total <= 0:

        return 0.5

    return (
        買單 / total
    )


# ============================================================
# 22. 合約清單
# ============================================================

def 取得合約清單():

    data = 取得資料(
        "/openApi/swap/v2/quote/contracts"
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

    if not isinstance(
        data,
        list
    ):

        raise ValueError(
            "合約清單格式錯誤"
        )

    contracts = {}

    for item in data:

        if not isinstance(
            item,
            dict
        ):

            continue

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        if not symbol:

            continue

        # ----------------------------------------------------
        # 只保留USDT合約
        # ----------------------------------------------------

        if not symbol.endswith(
            "-USDT"
        ):

            continue

        base = (
            symbol.split("-")[0]
        )

        if base in 排除幣種:

            continue

        # ----------------------------------------------------
        # 優先判斷合約狀態
        # ----------------------------------------------------

        status = str(
            item.get(
                "status",
                ""
            )
        ).lower()

        if status:

            if status not in {
                "1",
                "online",
                "normal",
                "trading",
                "open",
            }:

                # 某些版本可能使用其他正常值
                if status not in {
                    "2"
                }:

                    continue

        # ----------------------------------------------------
        # 排除非永續 / 異常合約
        # ----------------------------------------------------

        contract_type = str(
            item.get(
                "contractType",
                item.get(
                    "contract_type",
                    ""
                )
            )
        ).lower()

        if contract_type:

            if (
                "perpetual"
                not in contract_type
                and "永續"
                not in contract_type
            ):

                continue

        contracts[symbol] = item

    return contracts


# ============================================================
# 23. Ticker
# ============================================================

def 取得Ticker():

    data = 取得資料(
        "/openApi/swap/v2/quote/ticker"
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

    if not isinstance(
        data,
        list
    ):

        raise ValueError(
            "Ticker資料格式錯誤"
        )

    return data


# ============================================================
# 24. 掃描低價幣
# ============================================================

def 掃描幣種():

    # --------------------------------------------------------
    # 先取得合約清單
    # --------------------------------------------------------

    try:

        contracts = (
            取得合約清單()
        )

    except Exception as e:

        logging.warning(
            "取得合約清單失敗：%s",
            str(e)
        )

        contracts = {}

    # --------------------------------------------------------
    # 再取得Ticker
    # --------------------------------------------------------

    ticker = 取得Ticker()

    candidates = []

    已加入 = set()

    for item in ticker:

        try:

            if not isinstance(
                item,
                dict
            ):

                continue

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            ).upper().strip()

            if not symbol:

                continue

            if not symbol.endswith(
                "-USDT"
            ):

                continue

            if symbol in 已加入:

                continue

            base = (
                symbol.split("-")[0]
            )

            if base in 排除幣種:

                continue

            # ------------------------------------------------
            # 如果成功取得合約清單
            # 則必須存在於合約清單
            # ------------------------------------------------

            if contracts:

                if symbol not in contracts:

                    continue

            price = 轉Float(
                item.get(
                    "lastPrice"
                )
            )

            if price is None:

                continue

            if not (
                最低幣價
                <= price
                <= 最高幣價
            ):

                continue

            quote_volume = 轉Float(
                item.get(
                    "quoteVolume",
                    item.get(
                        "volume24h",
                        0
                    )
                ),
                0
            )

            if (
                quote_volume is None
                or quote_volume <= 0
            ):

                continue

            已加入.add(
                symbol
            )

            candidates.append({
                "symbol": symbol,
                "lastPrice": price,
                "quoteVolume": quote_volume,
            })

        except Exception as e:

            logging.debug(
                "Ticker項目跳過：%s",
                str(e)
            )

            continue

    # --------------------------------------------------------
    # 依24h成交額排序
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: (
            x["quoteVolume"]
        ),
        reverse=True
    )

    # --------------------------------------------------------
    # 最終只取設定數量
    # --------------------------------------------------------

    candidates = candidates[
        :每次掃描數量
    ]

    # --------------------------------------------------------
    # 最後再做一次symbol去重
    # --------------------------------------------------------

    final = []

    seen = set()

    for item in candidates:

        symbol = item[
            "symbol"
        ]

        if symbol in seen:

            continue

        seen.add(
            symbol
        )

        final.append(
            item
        )

    return final


# ============================================================
# 25. 風險管理
# ============================================================

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

    except Exception as e:

        logging.warning(
            "%s OI取得失敗：%s",
            symbol,
            str(e)
        )

    # --------------------------------------------------------
    # Order Book
    # --------------------------------------------------------

    book = 0.5

    try:

        book = 取得買賣掛單(
            symbol
        )

    except Exception as e:

        logging.warning(
            "%s 深度取得失敗：%s",
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

    if oi is not None:

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
                止損 < 進場
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
                > 止盈2
            ):

                進場 = None
                止損 = None
                止盈1 = None
                止盈2 = None

    # --------------------------------------------------------
    # 下單風險
    # --------------------------------------------------------

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

    elif old is None:

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

    if book > 0.60:

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

    message = (
        f"\n🪙 幣種：{r['symbol']}\n"
        f"💵 現價：{r['price']:.8f}\n"
        f"📊 方向：{r['方向']}\n"
        f"🎯 建議：{r['動作']}\n"
        f"📈 分析分數：{r['分數']:.1f}\n"
        f"📉 RSI：{r['RSI']:.1f}\n"
        f"🟢 可能支撐：{r['支撐']:.8f}\n"
        f"🔴 可能壓力：{r['壓力']:.8f}\n"
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
            f"{r['進場']:.8f}\n"

            f"🛑 參考止損："
            f"{r['止損']:.8f}\n"

            f"🎯 第一止盈："
            f"{r['止盈1']:.8f}\n"

            f"🎯 第二止盈："
            f"{r['止盈2']:.8f}\n"

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

def 傳送報告(results):

    # --------------------------------------------------------
    # 最終去重
    # --------------------------------------------------------

    unique = []

    seen = set()

    for r in results:

        symbol = r.get(
            "symbol"
        )

        if not symbol:

            continue

        if symbol in seen:

            continue

        seen.add(
            symbol
        )

        unique.append(
            r
        )

    # --------------------------------------------------------
    # 最終限制數量
    # --------------------------------------------------------

    unique = unique[
        :報告最大幣種數
    ]

    if not unique:

        傳送通知(
            "🔍 BingX AI小幣雷達\n\n"
            f"🕒 {現在時間()}\n\n"
            "本次沒有取得有效分析資料。"
        )

        return

    # --------------------------------------------------------
    # 按絕對分數排序
    # --------------------------------------------------------

    unique.sort(
        key=lambda x: (
            abs(
                x["分數"]
            )
        ),
        reverse=True
    )

    # --------------------------------------------------------
    # 報告標題
    # --------------------------------------------------------

    message = (
        "🔍 BingX AI小幣雷達\n"
        f"🕒 {現在時間()}\n"
        f"💰 帳戶本金：{本金:.2f} USDT\n"
        f"⚠️ 單筆風險上限："
        f"{單筆風險:.2f} USDT\n"
        f"🔎 本次掃描："
        f"{len(unique)} / "
        f"{每次掃描數量}\n"
        "━━━━━━━━━━━━━━\n"
    )

    # --------------------------------------------------------
    # 每個結果
    # --------------------------------------------------------

    for r in unique:

        message += 格式化結果(
            r
        )

        message += (
            "\n━━━━━━━━━━━━━━\n"
        )

    # --------------------------------------------------------
    # 固定說明
    # --------------------------------------------------------

    message += (
        "\n📌 本程式只提供分析，不會自動下單。\n"
        "📌 OI為公開市場資料，不代表可確認主力身分。\n"
        "📌 OI變化以不同掃描週期的成功紀錄比較。\n"
        "📌 價格與技術指標不保證未來走勢。\n"
        "📌 未計入手續費、滑價及資金費率。\n"
        "📌 實際虧損可能高於理論計算值。"
    )

    傳送通知(
        message
    )


# ============================================================
# 29. 分析單一幣種
# ============================================================

def 分析單一幣種(
    item,
    state
):

    symbol = item[
        "symbol"
    ]

    price = float(
        item["lastPrice"]
    )

    print(
        "=" * 60
    )

    print(
        "分析中：",
        symbol
    )

    print(
        "現價：",
        price
    )

    # --------------------------------------------------------
    # 15分鐘
    # --------------------------------------------------------

    k15 = 取得K線(
        symbol,
        "15m"
    )

    if not k15:

        raise ValueError(
            "15m K線無效"
        )

    time.sleep(
        API_MIN_INTERVAL
    )

    # --------------------------------------------------------
    # 1小時
    # --------------------------------------------------------

    k1h = 取得K線(
        symbol,
        "1h"
    )

    if not k1h:

        raise ValueError(
            "1h K線無效"
        )

    time.sleep(
        API_MIN_INTERVAL
    )

    # --------------------------------------------------------
    # 4小時
    # --------------------------------------------------------

    k4h = 取得K線(
        symbol,
        "4h"
    )

    if not k4h:

        raise ValueError(
            "4h K線無效"
        )

    time.sleep(
        API_MIN_INTERVAL
    )

    # --------------------------------------------------------
    # 綜合分析
    # --------------------------------------------------------

    result = 分析幣種(
        symbol,
        price,
        k15,
        k1h,
        k4h,
        state
    )

    return result


# ============================================================
# 30. 執行一次掃描
# ============================================================

def main():

    print("=" * 60)

    print(
        "開始掃描：",
        現在時間()
    )

    state = 讀取紀錄()

    # --------------------------------------------------------
    # 取得候選幣
    # --------------------------------------------------------

    try:

        candidates = 掃描幣種()

    except Exception as e:

        logging.error(
            "掃描幣種失敗：%s",
            str(e)
        )

        傳送通知(
            "⚠️ BingX掃描失敗\n"
            f"時間：{現在時間()}\n"
            f"錯誤：{str(e)[:800]}"
        )

        return

    # --------------------------------------------------------
    # 強制確認數量
    # --------------------------------------------------------

    candidates = candidates[
        :每次掃描數量
    ]

    print(
        "實際取得幣種數量：",
        len(candidates)
    )

    print(
        "實際取得幣種：",
        [
            x["symbol"]
            for x in candidates
        ]
    )

    if not candidates:

        print(
            "本次沒有符合條件的幣種"
        )

        傳送通知(
            "🔍 BingX AI小幣雷達\n\n"
            f"🕒 {現在時間()}\n\n"
            "本次沒有符合低價與成交量條件的USDT永續合約。"
        )

        return

    # --------------------------------------------------------
    # 分析
    # --------------------------------------------------------

    results = []

    已分析 = set()

    for item in candidates:

        symbol = item[
            "symbol"
        ]

        if symbol in 已分析:

            continue

        已分析.add(
            symbol
        )

        try:

            result = 分析單一幣種(
                item,
                state
            )

            if result:

                results.append(
                    result
                )

        except Exception as e:

            print(
                "幣種分析失敗：",
                symbol
            )

            print(
                "錯誤類型：",
                type(e).__name__
            )

            print(
                "錯誤內容：",
                repr(e)
            )

            traceback.print_exc()

            print(
                "=" * 60
            )

        time.sleep(
            API_MIN_INTERVAL
        )

    # --------------------------------------------------------
    # 儲存OI狀態
    # --------------------------------------------------------

    try:

        儲存紀錄(
            state
        )

    except Exception as e:

        logging.error(
            "紀錄儲存失敗：%s",
            str(e)
        )

    # --------------------------------------------------------
    # 最終結果去重
    # --------------------------------------------------------

    final_results = []

    seen = set()

    for result in results:

        symbol = result.get(
            "symbol"
        )

        if not symbol:

            continue

        if symbol in seen:

            continue

        seen.add(
            symbol
        )

        final_results.append(
            result
        )

    # --------------------------------------------------------
    # 最終限制
    # --------------------------------------------------------

    final_results = final_results[
        :每次掃描數量
    ]

    print(
        "=" * 60
    )

    print(
        "分析成功數量：",
        len(final_results)
    )

    print(
        "分析結果：",
        [
            x["symbol"]
            for x in final_results
        ]
    )

    # --------------------------------------------------------
    # 傳送報告
    # --------------------------------------------------------

    傳送報告(
        final_results
    )

    print(
        "掃描完成：",
        現在時間()
    )

    print(
        "=" * 60
    ) # ============================================================
# 31. 啟動循環
# ============================================================

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

        開始時間 = time.time()

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
            time.time()
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

    啟動()

