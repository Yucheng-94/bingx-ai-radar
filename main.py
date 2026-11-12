
import os
import time
import json
import requests
from datetime import datetime, timezone, timedelta

# ==================================
# 1. 你的專屬設定
# ==================================

本金 = 100.0
單筆風險 = 1.0
預設槓桿 = 2
最高槓桿 = 5
最高保證金 = 20.0

最低幣價 = 0.1
最高幣價 = 0.9999

每次掃描數量 = 10
掃描間隔 = 900

排除幣種 = {
    "BTC", "ETH", "BNB", "SOL", "XRP",
    "DOGE", "ADA", "TRX", "LTC", "BCH",
    "DOT", "LINK", "AVAX", "TON"
}

網址 = "https://open-api.bingx.com"
時區 = timezone(timedelta(hours=8))

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

紀錄檔 = "state.json"


# ==================================
# 2. 基本工具
# ==================================

def 現在時間():
    return datetime.now(時區).strftime("%Y-%m-%d %H:%M:%S")


def 取得資料(path, params=None):
    r = requests.get(
        網址 + path,
        params=params or {},
        timeout=20
    )
    r.raise_for_status()

    data = r.json()

    if data.get("code", 0) != 0:
        raise Exception(data.get("msg", "BingX資料錯誤"))

    return data.get("data")


def 傳送通知(message):
    if not TG_TOKEN or not TG_CHAT:
        print("尚未設定Telegram")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    r = requests.post(
        url,
        json={
            "chat_id": TG_CHAT,
            "text": message
        },
        timeout=20
    )
    r.raise_for_status()


def 讀取紀錄():
    try:
        with open(紀錄檔, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def 儲存紀錄(data):
    with open(紀錄檔, "w") as f:
        json.dump(data, f)


# ==================================
# 3. EMA及RSI
# ==================================

def 計算EMA(values, period):
    alpha = 2 / (period + 1)
    result = [values[0]]

    for value in values[1:]:
        result.append(
            alpha * value +
            (1 - alpha) * result[-1]
        )

    return result


def 計算RSI(values, period=14):
    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ==================================
# 4. 取得K線
# ==================================

def 取得K線(symbol, interval):
    data = 取得資料(
        "/openApi/swap/v3/quote/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": 80
        }
    )

    if not data or len(data) < 30:
        return None

    return {
        "open": [float(x[1]) for x in data],
        "high": [float(x[2]) for x in data],
        "low": [float(x[3]) for x in data],
        "close": [float(x[4]) for x in data],
        "volume": [float(x[5]) for x in data],
        "buy": [
            float(x[9]) if len(x) > 9 else float(x[5]) / 2
            for x in data
        ]
    }


def 分析K線(k):
    close = k["close"]
    high = k["high"]
    low = k["low"]
    volume = k["volume"]

    ema7 = 計算EMA(close, 7)
    ema25 = 計算EMA(close, 25)

    rsi = 計算RSI(close)

    成交平均 = sum(volume[-21:-1]) / 20

    成交倍數 = (
        volume[-1] / 成交平均
        if 成交平均 > 0 else 1
    )

    atr = sum(
        high[i] - low[i]
        for i in range(len(high) - 14, len(high))
    ) / 14

    支撐 = min(low[-20:])
    壓力 = max(high[-20:])

    買盤比例 = (
        k["buy"][-1] / volume[-1]
        if volume[-1] > 0 else 0.5
    )

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

    if rsi > 70:
        分數 -= 1

    if 成交倍數 > 1.5 and 買盤比例 > 0.55:
        分數 += 1

    if 成交倍數 > 1.5 and 買盤比例 < 0.45:
        分數 -= 1

    return {
        "分數": 分數,
        "RSI": rsi,
        "EMA7": ema7[-1],
        "EMA25": ema25[-1],
        "支撐": 支撐,
        "壓力": 壓力,
        "ATR": atr,
        "成交倍數": 成交倍數,
        "買盤比例": 買盤比例
    }


# ==================================
# 5. 主力動向觀察
# ==================================

def 取得持倉量(symbol):
    data = 取得資料(
        "/openApi/swap/v2/quote/openInterest",
        {"symbol": symbol}
    )

    return float(data["openInterest"])


def 取得買賣掛單(symbol):
    data = 取得資料(
        "/openApi/swap/v2/quote/depth",
        {
            "symbol": symbol,
            "limit": 20
        }
    )

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    買單 = sum(
        float(x[0]) * float(x[1])
        for x in bids
    )

    賣單 = sum(
        float(x[0]) * float(x[1])
        for x in asks
    )

    total = 買單 + 賣單

    比例 = 買單 / total if total > 0 else 0.5

    return 比例


# ==================================
# 6. 計算建議下單金額
# ==================================

def 計算下單(方向, 進場, 止損):

    距離 = abs(進場 - 止損)

    if 進場 <= 0 or 距離 <= 0:
        return None

    距離比例 = 距離 / 進場

    # 以最多虧損1 USDT反推合約金額
    合約金額 = 單筆風險 / 距離比例

    # 先限制保證金
    槓桿 = min(預設槓桿, 最高槓桿)

    保證金 = 合約金額 / 槓桿

    if 保證金 > 最高保證金:
        保證金 = 最高保證金
        合約金額 = 保證金 * 槓桿

    # 計算實際價格變動造成的預估虧損
    預估虧損 = 合約金額 * 距離比例

    return {
        "槓桿": 槓桿,
        "保證金": 保證金,
        "合約金額": 合約金額,
        "預估虧損": 預估虧損,
        "風險比例": 距離比例 * 100
    }


# ==================================
# 7. 綜合判斷
# ==================================

def 分析幣種(symbol, price, k15, k1h, k4h, state):

    a15 = 分析K線(k15)
    a1h = 分析K線(k1h)
    a4h = 分析K線(k4h)

    oi = 取得持倉量(symbol)
    book = 取得買賣掛單(symbol)

    old = state.get(symbol, {}).get("oi")

    oi_change = 0

    if old and float(old) > 0:
        oi_change = (oi / float(old) - 1) * 100

    state[symbol] = {"oi": oi}

    分數 = (
        a15["分數"] * 1.5 +
        a1h["分數"] * 1.5 +
        a4h["分數"]
    )

    if oi_change > 1 and book > 0.55:
        分數 += 1

    elif oi_change > 1 and book < 0.45:
        分數 -= 1

    if 分數 >= 3:
        方向 = "偏向上漲"
        動作 = "觀察做多"
        進場 = max(
            a15["支撐"],
            price - a15["ATR"] * 0.3
        )
        止損 = 進場 - a15["ATR"] * 1.5
        止盈1 = 進場 + (進場 - 止損) * 2
        止盈2 = 進場 + (進場 - 止損) * 3

    elif 分數 <= -3:
        方向 = "偏向下跌"
        動作 = "觀察做空"
        進場 = min(
            a15["壓力"],
            price + a15["ATR"] * 0.3
        )
        止損 = 進場 + a15["ATR"] * 1.5
        止盈1 = 進場 - (止損 - 進場) * 2
        止盈2 = 進場 - (止損 - 進場) * 3

    else:
        方向 = "目前方向不明"
        動作 = "繼續觀望"
        進場 = None
        止損 = None
        止盈1 = None
        止盈2 = None

    下單 = None

    if 進場 is not None:
        下單 = 計算下單(
            方向,
            進場,
            止損
        )

    if oi_change > 1:
        oi_text = "持倉增加，可能有資金進入"
    elif oi_change < -1:
        oi_text = "持倉減少，可能有資金撤出"
    else:
        oi_text = "持倉變化不明顯"

    if book > 0.60:
        book_text = "買單較強"
    elif book < 0.40:
        book_text = "賣單較強"
    else:
        book_text = "買賣力量接近"

    return {
        "symbol": symbol,
        "price": price,
        "方向": 方向,
        "動作": 動作,
        "分數": 分數,
        "RSI": a15["RSI"],
        "支撐": a15["支撐"],
        "壓力": a15["壓力"],
        "成交倍數": a15["成交倍數"],
        "持倉變化": oi_change,
        "持倉說明": oi_text,
        "掛單說明": book_text,
        "進場": 進場,
        "止損": 止損,
        "止盈1": 止盈1,
        "止盈2": 止盈2,
        "下單": 下單
    }


# ==================================
# 8. 找出符合條件的低價幣
# ==================================

def 掃描幣種():

    data = 取得資料(
        "/openApi/swap/v2/quote/ticker"
    )

    candidates = []

    for item in data:

        symbol = item.get("symbol", "")

        if not symbol.endswith("-USDT"):
            continue

        base = symbol.split("-")[0]

        if base in 排除幣種:
            continue

        price = float(item.get("lastPrice", 0))

        if 最低幣價 <= price <= 最高幣價:

            candidates.append(item)

    candidates.sort(
        key=lambda x: float(
            x.get("quoteVolume", 0)
        ),
        reverse=True
    )

    return candidates[:每次掃描數量]


# ==================================
# 9. 傳送中文報告
# ==================================

def 傳送報告(results):

    if not results:
        傳送通知(
            "🔍 BingX AI小幣雷達\n\n"
            "本次沒有取得有效分析資料。"
        )
        return

    results.sort(
        key=lambda x: abs(x["分數"]),
        reverse=True
    )

    message = (
        "🔍 BingX AI小幣雷達\n"
        "🕒 " + 現在時間() + "\n"
        "💰 帳戶本金：100 USDT\n"
        "⚠️ 單筆風險上限：1 USDT\n"
        "━━━━━━━━━━━━━━\n"
    )

    for r in results[:8]:

        message += (
            "\n🪙 幣種：" + r["symbol"] + "\n"
            "💵 現價：" + str(round(r["price"], 6)) + "\n"
            "📊 方向：" + r["方向"] + "\n"
            "🎯 建議：" + r["動作"] + "\n"
            "📈 分析分數：" + str(round(r["分數"], 1)) + "\n"
            "📉 RSI：" + str(round(r["RSI"], 1)) + "\n"
            "🟢 可能支撐：" + str(round(r["支撐"], 6)) + "\n"
            "🔴 可能壓力：" + str(round(r["壓力"], 6)) + "\n"
            "📦 成交量：" + str(round(r["成交倍數"], 2)) + "倍\n"
            "🐋 持倉：" + r["持倉說明"] + "\n"
            "📚 買賣掛單：" + r["掛單說明"] + "\n"
        )

        if r["進場"] is not None and r["下單"]:

            o = r["下單"]

            message += (
                "\n📍 參考進場：" + str(round(r["進場"], 6)) + "\n"
                "🛑 參考止損：" + str(round(r["止損"], 6)) + "\n"
                "🎯 第一止盈：" + str(round(r["止盈1"], 6)) + "\n"
                "🎯 第二止盈：" + str(round(r["止盈2"], 6)) + "\n"
                "⚖️ 建議槓桿：" + str(o["槓桿"]) + "倍\n"
                "💰 建議保證金：" + str(round(o["保證金"], 2)) + " USDT\n"
                "📦 合約總金額：" + str(round(o["合約金額"], 2)) + " USDT\n"
                "⚠️ 預估止損虧損：" + str(round(o["預估虧損"], 2)) + " USDT\n"
            )

        message += "\n━━━━━━━━━━━━━━\n"

    message += (
        "\n📌 本程式只提供分析，不會自動下單。"
        "\n📌 主力動向只是公開市場跡象，不代表能確認主力身分。"
        "\n📌 以上價格是模型估算，不保證未來走勢。"
        "\n📌 實際虧損可能因手續費、滑價及強平風險而超過估算。"
    )

    傳送通知(message)


# ==================================
# 10. 執行一次掃描
# ==================================

def main():

    print("開始掃描：", 現在時間())

    state = 讀取紀錄()

    candidates = 掃描幣種()

    results = []

    for item in candidates:

        symbol = item["symbol"]
        price = float(item["lastPrice"])

        try:

            print("分析中：", symbol)

            k15 = 取得K線(symbol, "15m")
            time.sleep(1.1)

            k1h = 取得K線(symbol, "1h")
            time.sleep(1.1)

            k4h = 取得K線(symbol, "4h")
            time.sleep(1.1)

            if not k15 or not k1h or not k4h:
                continue

            result = 分析幣種(
                symbol,
                price,
                k15,
                k1h,
                k4h,
                state
            )

            results.append(result)

        except Exception as e:

            print("幣種分析失敗：", symbol, str(e))

        time.sleep(1.1)

    儲存紀錄(state)

    傳送報告(results)

    print("掃描完成：", 現在時間())


if __name__ == "__main__":
    main()
