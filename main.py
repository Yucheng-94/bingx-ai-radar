import os
import time
import json
import logging
import requests

from datetime import datetime, timezone, timedelta


# ==========================================
# 1. 專屬設定
# ==========================================

本金 = 100.0
單筆風險 = 1.0

預設槓桿 = 2
最高槓桿 = 5
最高保證金 = 20.0

最低幣價 = 0.1
最高幣價 = 0.9999

每次掃描數量 = 5
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
print("目前執行檔：", os.path.abspath(__file__))
print("目前掃描數量：", 每次掃描數量)
print("目前請求間隔：", 請求間隔)

請求重試次數 = 3
請求間隔 = 2.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


# ==========================================
# 2. HTTP Session
# ==========================================

session = requests.Session()

session.headers.update({
    "User-Agent": "BingX-Market-Radar/2.0"
})


def 現在時間():
    return datetime.now(時區).strftime(
        "%Y-%m-%d %H:%M:%S"
    )



def 取得資料(path, params=None):

    url = 網址 + path

    最後錯誤 = None

    for attempt in range(5):

        try:

            response = session.get(
                url,
                params=params or {},
                timeout=30
            )

            print(
                "API請求：",
                path,
                "HTTP：",
                response.status_code
            )

            response.raise_for_status()

            result = response.json()

            if not isinstance(result, dict):
                raise ValueError(
                    f"API格式錯誤：{str(result)[:300]}"
                )

            code = result.get("code", 0)
            msg = result.get("msg", "")

            if str(code) != "0":

                raise Exception(
                    f"BingX錯誤碼={code}，訊息={msg}"
                )

            if "data" not in result:
                raise ValueError(
                    f"API缺少data：{result}"
                )

            return result["data"]

        except Exception as e:

            最後錯誤 = e

            print(
                f"API失敗 {attempt + 1}/5：",
                repr(e)
            )

            if attempt < 4:
                time.sleep(3 * (attempt + 1))

    raise Exception(
        f"API最終失敗：{path}：{最後錯誤}"
    )


# ==========================================
# 3. Telegram通知
# ==========================================

def 傳送通知(message):

    if not TG_TOKEN or not TG_CHAT:

        print("尚未設定Telegram")
        print(message)
        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TG_TOKEN}/sendMessage"
    )

    分段長度 = 3500

    chunks = [
        message[i:i + 分段長度]
        for i in range(0, len(message), 分段長度)
    ]

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
                raise Exception(str(result))

        except Exception as e:

            logging.error(
                "Telegram傳送失敗：%s",
                str(e)
            )


# ==========================================
# 4. 狀態紀錄
# ==========================================

def 讀取紀錄():

    try:

        with open(
            紀錄檔,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            return data if isinstance(data, dict) else {}

    except Exception:

        return {}


def 儲存紀錄(data):

    temp_file = 紀錄檔 + ".tmp"

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

    os.replace(temp_file, 紀錄檔)


# ==========================================
# 5. 技術指標
# ==========================================

def 計算EMA(values, period):

    if not values:
        return []

    alpha = 2 / (period + 1)

    result = [float(values[0])]

    for value in values[1:]:

        result.append(
            alpha * float(value)
            + (1 - alpha) * result[-1]
        )

    return result


def 計算RSI(values, period=14):

    if len(values) < period + 1:
        raise ValueError("RSI資料不足")

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [
        max(x, 0)
        for x in changes
    ]

    losses = [
        max(-x, 0)
        for x in changes
    ]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):

        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:

        if avg_gain == 0:
            return 50.0

        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs)) # ==========================================
# 6. K線資料解析
# ==========================================

def 解析K線(data):

    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    buys = []

    for x in data:

        if isinstance(x, dict):

            o = float(x["open"])
            h = float(x["high"])
            l = float(x["low"])
            c = float(x["close"])
            v = float(x["volume"])

            b = float(
                x.get("takerBuyBaseVolume", v / 2)
            )

        elif isinstance(x, (list, tuple)):

            if len(x) < 6:
                continue

            o = float(x[1])
            h = float(x[2])
            l = float(x[3])
            c = float(x[4])
            v = float(x[5])

            b = (
                float(x[9])
                if len(x) > 9
                else v / 2
            )

        else:
            continue

        if not all(
            map(
                lambda n: n >= 0,
                [o, h, l, c, v, b]
            )
        ):
            continue

        if h < l or c <= 0:
            continue

        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(v)
        buys.append(b)

    if len(closes) < 30:
        return None

    return {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "buy": buys
    }


def 取得K線(symbol, interval):

    data = 取得資料(
        "/openApi/swap/v3/quote/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": 100
        }
    )

    if not data:
        return None

    if isinstance(data, dict):
        data = data.get(
            "data",
            data.get("list", [])
        )

    if not isinstance(data, list):
        raise ValueError("K線回傳不是列表")

    return 解析K線(data)


# ==========================================
# 7. K線技術分析
# ==========================================

def 分析K線(k):

    close = k["close"]
    high = k["high"]
    low = k["low"]
    volume = k["volume"]

    if len(close) < 30:
        raise ValueError("技術分析資料不足")

    ema7 = 計算EMA(close, 7)
    ema25 = 計算EMA(close, 25)

    rsi = 計算RSI(close)

    成交平均 = sum(volume[-21:-1]) / 20

    成交倍數 = (
        volume[-1] / 成交平均
        if 成交平均 > 0
        else 1
    )

    # ATR真實波幅
    true_ranges = []

    for i in range(1, len(close)):

        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )

        true_ranges.append(tr)

    atr = sum(true_ranges[-14:]) / 14

    支撐 = min(low[-20:])
    壓力 = max(high[-20:])

    買盤比例 = (
        k["buy"][-1] / volume[-1]
        if volume[-1] > 0
        else 0.5
    )

    買盤比例 = max(
        0,
        min(1, 買盤比例)
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

    elif rsi > 70:
        分數 -= 1

    if 成交倍數 > 1.5:

        if 買盤比例 > 0.55:
            分數 += 1

        elif 買盤比例 < 0.45:
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


# ==========================================
# 8. 持倉量 OI
# ==========================================

def 取得持倉量(symbol):

    data = 取得資料(
        "/openApi/swap/v2/quote/openInterest",
        {
            "symbol": symbol
        }
    )

    if isinstance(data, list):

        if not data:
            raise ValueError("OI資料為空")

        data = data[0]

    if not isinstance(data, dict):
        raise ValueError("OI格式錯誤")

    value = data.get(
        "openInterest",
        data.get("openInterestAmount")
    )

    if value is None:
        raise ValueError("找不到OI欄位")

    return float(value)


# ==========================================
# 9. 買賣盤深度
# ==========================================

def 取得買賣掛單(symbol):

    data = 取得資料(
        "/openApi/swap/v2/quote/depth",
        {
            "symbol": symbol,
            "limit": 20
        }
    )

    if not isinstance(data, dict):
        raise ValueError("深度資料格式錯誤")

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    def 計算掛單總額(items):

        total = 0

        for x in items:

            if isinstance(x, dict):

                price = float(x["price"])

                amount = float(
                    x.get(
                        "quantity",
                        x.get("qty", 0)
                    )
                )

            else:

                price = float(x[0])
                amount = float(x[1])

            total += price * amount

        return total

    買單 = 計算掛單總額(bids)
    賣單 = 計算掛單總額(asks)

    total = 買單 + 賣單

    if total <= 0:
        return 0.5

    return 買單 / total


# ==========================================
# 10. 風險管理
# ==========================================

def 計算下單(方向, 進場, 止損):

    距離 = abs(進場 - 止損)

    if 進場 <= 0 or 距離 <= 0:
        return None

    距離比例 = 距離 / 進場

    if 距離比例 <= 0:
        return None

    # 風險反推倉位
    理論合約金額 = 單筆風險 / 距離比例

    槓桿 = min(
        預設槓桿,
        最高槓桿
    )

    可用保證金 = min(
        最高保證金,
        本金
    )

    合約金額上限 = 可用保證金 * 槓桿

    合約金額 = min(
        理論合約金額,
        合約金額上限
    )

    保證金 = 合約金額 / 槓桿

    預估虧損 = 合約金額 * 距離比例

    return {
        "槓桿": 槓桿,
        "保證金": 保證金,
        "合約金額": 合約金額,
        "預估虧損": 預估虧損,
        "風險比例": 距離比例 * 100
    }


# ==========================================
# 11. 綜合分析
# ==========================================

def 分析幣種(
    symbol,
    price,
    k15,
    k1h,
    k4h,
    state
):

    a15 = 分析K線(k15)
    a1h = 分析K線(k1h)
    a4h = 分析K線(k4h)

    oi = None
    book = 0.5

    try:

        oi = 取得持倉量(symbol)

    except Exception as e:

        logging.warning(
            "%s OI取得失敗：%s",
            symbol,
            str(e)
        )

    try:

        book = 取得買賣掛單(symbol)

    except Exception as e:

        logging.warning(
            "%s 深度取得失敗：%s",
            symbol,
            str(e)
        )

    old = state.get(
        symbol,
        {}
    ).get("oi")

    oi_change = 0

    if (
        oi is not None
        and old is not None
        and float(old) > 0
    ):

        oi_change = (
            oi / float(old) - 1
        ) * 100

    if oi is not None:

        state[symbol] = {
            "oi": oi,
            "time": 現在時間()
        }

    分數 = (
        a15["分數"] * 1.5
        + a1h["分數"] * 1.5
        + a4h["分數"]
    )

    if oi is not None:

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

        止損 = (
            進場 - a15["ATR"] * 1.5
        )

        止盈1 = (
            進場 + (進場 - 止損) * 2
        )

        止盈2 = (
            進場 + (進場 - 止損) * 3
        )

    elif 分數 <= -3:

        方向 = "偏向下跌"
        動作 = "觀察做空"

        進場 = min(
            a15["壓力"],
            price + a15["ATR"] * 0.3
        )

        止損 = (
            進場 + a15["ATR"] * 1.5
        )

        止盈1 = (
            進場 - (止損 - 進場) * 2
        )

        止盈2 = (
            進場 - (止損 - 進場) * 3
        )

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

    if oi is None:

        oi_text = "OI資料暫時無法取得"

    elif old is None:

        oi_text = "首次紀錄，等待下次比較"

    elif oi_change > 1:

        oi_text = "持倉增加，可能有新倉進入"

    elif oi_change < -1:

        oi_text = "持倉減少，可能有倉位退出"

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
    } # ==========================================
# 12. 掃描低價幣
# ==========================================

def 掃描幣種():

    data = 取得資料(
        "/openApi/swap/v2/quote/ticker"
    )

    if not isinstance(data, list):
        raise ValueError("Ticker資料格式錯誤")

    candidates = []

    for item in data:

        try:

            symbol = item.get("symbol", "")

            if not symbol.endswith("-USDT"):
                continue

            base = symbol.split("-")[0]

            if base in 排除幣種:
                continue

            price = float(
                item.get("lastPrice", 0)
            )

            if not (
                最低幣價 <= price <= 最高幣價
            ):
                continue

            quote_volume = float(
                item.get("quoteVolume", 0)
            )

            if quote_volume <= 0:
                continue

            candidates.append(item)

        except Exception:
            continue

    candidates.sort(
        key=lambda x: float(
            x.get("quoteVolume", 0)
        ),
        reverse=True
    )

    return candidates[:每次掃描數量]


# ==========================================
# 13. Telegram報告
# ==========================================

def 傳送報告(results):

    if not results:

        傳送通知(
            "🔍 BingX AI小幣雷達\n\n"
            f"🕒 {現在時間()}\n\n"
            "本次沒有取得有效分析資料。"
        )

        return

    results.sort(
        key=lambda x: abs(x["分數"]),
        reverse=True
    )

    message = (
        "🔍 BingX AI小幣雷達\n"
        f"🕒 {現在時間()}\n"
        f"💰 帳戶本金：{本金} USDT\n"
        f"⚠️ 單筆風險上限：{單筆風險} USDT\n"
        "━━━━━━━━━━━━━━\n"
    )

    for r in results[:8]:

        message += (
            f"\n🪙 幣種：{r['symbol']}\n"
            f"💵 現價：{r['price']:.6f}\n"
            f"📊 方向：{r['方向']}\n"
            f"🎯 建議：{r['動作']}\n"
            f"📈 分析分數：{r['分數']:.1f}\n"
            f"📉 RSI：{r['RSI']:.1f}\n"
            f"🟢 可能支撐：{r['支撐']:.6f}\n"
            f"🔴 可能壓力：{r['壓力']:.6f}\n"
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
                f"\n📍 參考進場：{r['進場']:.6f}\n"
                f"🛑 參考止損：{r['止損']:.6f}\n"
                f"🎯 第一止盈：{r['止盈1']:.6f}\n"
                f"🎯 第二止盈：{r['止盈2']:.6f}\n"
                f"⚖️ 建議槓桿：{o['槓桿']}倍\n"
                f"💰 建議保證金：{o['保證金']:.2f} USDT\n"
                f"📦 合約總金額：{o['合約金額']:.2f} USDT\n"
                f"⚠️ 預估止損虧損：{o['預估虧損']:.2f} USDT\n"
            )

        message += "\n━━━━━━━━━━━━━━\n"

    message += (
        "\n📌 本程式只提供分析，不會自動下單。"
        "\n📌 主力動向只是公開市場跡象，不能確認主力身分。"
        "\n📌 OI變化以兩次成功紀錄作比較。"
        "\n📌 價格與指標不保證未來走勢。"
        "\n📌 未計入手續費、滑價及資金費率。"
        "\n📌 實際虧損可能超過預估值。"
    )

    傳送通知(message)


# ==========================================
# 14. 執行一次掃描
# ==========================================

def main():

    print("開始掃描：", 現在時間())

    state = 讀取紀錄()

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
            f"錯誤：{str(e)[:500]}"
        )

        return

    results = []

    for item in candidates:

        symbol = item["symbol"]

        try:

            price = float(
                item["lastPrice"]
            )

            print("分析中：", symbol)

            k15 = 取得K線(
                symbol,
                "15m"
            )

            time.sleep(請求間隔)

            k1h = 取得K線(
                symbol,
                "1h"
            )

            time.sleep(請求間隔)

            k4h = 取得K線(
                symbol,
                "4h"
            )

            time.sleep(請求間隔)

            if not k15 or not k1h or not k4h:

                logging.warning(
                    "%s K線資料不足，跳過",
                    symbol
                )

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
    import traceback

    print("幣種分析失敗：", symbol)
    print("錯誤類型：", type(e).__name__)
    print("錯誤內容：", repr(e))
    traceback.print_exc()

    print(
        "錯誤類型：",
        type(e).__name__
    )

    print(
        "錯誤內容：",
        repr(e)
    )

    traceback.print_exc()

    print("=" * 60)
    print("\n")

        time.sleep(請求間隔)

    try:

        儲存紀錄(state)

    except Exception as e:

        logging.error(
            "紀錄儲存失敗：%s",
            str(e)
        )

    傳送報告(results)

    print("掃描完成：", 現在時間())


# ==========================================
# 15. 每15分鐘自動循環
# ==========================================

def 啟動():

    print("================================")
    print("BingX AI小幣雷達啟動")
    print("本金：", 本金, "USDT")
    print("單筆風險：", 單筆風險, "USDT")
    print("掃描數量：", 每次掃描數量)
    print("掃描間隔：", 掃描間隔, "秒")
    print("================================")

    while True:

        開始時間 = time.time()

        try:

            main()

        except KeyboardInterrupt:

            print("使用者停止程式")
            break

        except Exception as e:

            logging.exception(
                "主程式發生錯誤：%s",
                str(e)
            )

        執行時間 = time.time() - 開始時間

        等待時間 = max(
            5,
            掃描間隔 - 執行時間
        )

        print(
            f"下次掃描約在 {等待時間:.0f} 秒後"
        )

        try:

            time.sleep(等待時間)

        except KeyboardInterrupt:

            print("程式已停止")
            break


# ==========================================
# 16. 程式入口
# ==========================================

if __name__ == "__main__":

    啟動()

