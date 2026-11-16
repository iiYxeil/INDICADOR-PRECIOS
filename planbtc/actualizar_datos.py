"""Descarga los datos para la web de gráficas estilo Plan BTC y genera data.js.

Uso:  python actualizar_datos.py
Fuentes gratuitas:
  - Coin Metrics Community: precio BTC diario desde 2010, MVRV, emisión (Puell), hashrate
  - alternative.me: Fear & Greed Index (desde 2018)
  - Yahoo Finance: Nasdaq (^IXIC) y S&P 500 (^GSPC)
  - bitcoin-data.com: STH-MVRV, precio realizado corto plazo, aSOPR, Reserve Risk
    (versión gratis: últimos ~4 años y máx. 15 consultas/día -> se guarda caché 20 h)
"""
import json, os, time, urllib.request, datetime as dt

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cache")
os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (planbtc-graficas)"}
EPOCH = dt.date(1970, 1, 1)


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def day(s):  # 'YYYY-MM-DD...' -> días desde 1970
    return (dt.date.fromisoformat(s[:10]) - EPOCH).days


def cached(name, url, max_age_h=20):
    # la fecha se guarda dentro del archivo (en GitHub la fecha del archivo no sirve)
    path = os.path.join(CACHE, name + ".json")
    old = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    if old and time.time() - old.get("_ts", 0) < max_age_h * 3600:
        return old["data"]
    try:
        data = get(url)
        if isinstance(data, dict) and data.get("status") in (404, 429):
            raise RuntimeError(data)
        json.dump({"_ts": time.time(), "data": data}, open(path, "w", encoding="utf-8"))
        return data
    except Exception as e:
        print(f"  ! {name}: {e}")
        if old:
            print("    usando caché antigua")
            return old["data"]
        return None


def coinmetrics():
    metrics = "PriceUSD,CapMVRVCur,IssTotUSD,HashRate"
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc"
           f"&metrics={metrics}&frequency=1d&page_size=10000&paging_from=start&start_time=2010-07-18")
    rows = []
    while url:
        d = get(url)
        rows += d["data"]
        url = d.get("next_page_url")
    out = {k: [] for k in ["d", "p", "mvrv", "iss", "hash"]}
    for r in rows:
        if not r.get("PriceUSD"):
            continue
        f = lambda k: round(float(r[k]), 6) if r.get(k) else None
        out["d"].append(day(r["time"]))
        out["p"].append(round(float(r["PriceUSD"]), 2))
        out["mvrv"].append(f("CapMVRVCur"))
        out["iss"].append(round(float(r["IssTotUSD"]), 0) if r.get("IssTotUSD") else None)
        out["hash"].append(round(float(r["HashRate"]), 1) if r.get("HashRate") else None)
    return out


def fng():
    d = get("https://api.alternative.me/fng/?limit=0")["data"]
    d.sort(key=lambda x: int(x["timestamp"]))
    return {"d": [int(x["timestamp"]) // 86400 for x in d], "v": [int(x["value"]) for x in d]}


def yahoo(sym):
    # range=max devuelve datos espaciados; con period1/period2 sí da velas diarias
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1262304000"
            f"&period2={int(time.time())}&interval=1d")
    r = d["chart"]["result"][0]
    ts, cl = r["timestamp"], r["indicators"]["quote"][0]["close"]
    out = {"d": [], "v": []}
    for t, c in zip(ts, cl):
        dd = t // 86400
        if c is None or dd < day("2010-01-01") or (out["d"] and dd <= out["d"][-1]):
            continue
        out["d"].append(dd)
        out["v"].append(round(c, 2))
    return out


def bitcoin_data(endpoint, key):
    d = cached("bd_" + endpoint, f"https://bitcoin-data.com/v1/{endpoint}")
    if not isinstance(d, list):
        return None
    out = {"d": [], "v": []}
    for x in d:
        v = x.get(key)
        if v in (None, ""):
            continue
        out["d"].append(day(x["d"]))
        out["v"].append(float(v))
    return out


def load_old():
    path = os.path.join(BASE, "data.js")
    try:
        txt = open(path, encoding="utf-8").read()
        return json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
    except Exception:
        return {}


def main():
    old = load_old()  # si una fuente falla, se conservan sus datos anteriores
    data = {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}

    def step(key, label, fn):
        print(label + "...")
        try:
            data[key] = fn()
        except Exception as e:
            print("  !", e, "-> se mantienen los datos anteriores")
            if old.get(key):
                data[key] = old[key]

    step("btc", "Coin Metrics (precio, MVRV, emisión, hashrate)", coinmetrics)
    step("fng", "Fear & Greed", fng)
    step("nasdaq", "Yahoo Nasdaq", lambda: yahoo("%5EIXIC"))
    step("sp500", "Yahoo S&P 500", lambda: yahoo("%5EGSPC"))
    if "btc" not in data:
        print("Sin datos de precio: no se escribe data.js")
        return
    print("bitcoin-data.com (on-chain corto plazo)...")
    for k, ep, key in [("sthMvrv", "sth-mvrv", "sthMvrv"), ("sthRp", "sth-realized-price", "sthRealizedPrice"),
                       ("asopr", "asopr", "asopr"), ("reserveRisk", "reserve-risk", "reserveRisk")]:
        data[k] = bitcoin_data(ep, key) or old.get(k)
        print(f"  {k}: {'OK ' + str(len(data[k]['d'])) if data[k] else 'sin datos'}")
    js = "window.DATA = " + json.dumps(data, separators=(",", ":")) + ";\n"
    open(os.path.join(BASE, "data.js"), "w", encoding="utf-8").write(js)
    print(f"data.js escrito ({len(js)//1024} KB)")


if __name__ == "__main__":
    import sys
    if sys.stdout is None:  # ejecutado con pythonw (tarea programada): escribir en un log
        sys.stdout = sys.stderr = open(os.path.join(BASE, "actualizacion.log"), "a", encoding="utf-8")
        print("\n=== " + dt.datetime.now().strftime("%Y-%m-%d %H:%M") + " ===")
    main()
