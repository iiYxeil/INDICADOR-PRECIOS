"""Respuestas de mentira para `update.py --selftest`.

Sirven para comprobar que la reescritura del HTML funciona sin tocar la red.
Los numeros son deliberadamente distintos de los que hay en la pagina, para
que el test falle si algo no se escribe.
"""

_STATS = """<table>
<tr><td>52-Week Price Change</td><td>{cambio52}%</td></tr>
<tr><td>PEG Ratio</td><td>{peg}</td></tr>
<tr><td>Forward PE</td><td>{fwd}</td></tr>
<tr><td>FCF Yield</td><td>{fcf}%</td></tr>
<tr><td>Return on Invested Capital (ROIC)</td><td>{roic}%</td></tr>
<tr><td>200-Day Moving Average</td><td>{sma}</td></tr>
<tr><td>EV/EBITDA</td><td>{ev}</td></tr>
<tr><td>Relative Strength Index (RSI)</td><td>{rsi}</td></tr>
</table>"""

# Con los tres "... Change" presentes: si la busqueda no es exacta,
# "Target Low Change" puede ganarle a "Target Change".
_FORECAST = """<table>
<tr><th>Target</th><th>Change</th></tr>
<tr><td>Price</td><td>${obj}</td><td>{chg}%</td></tr>
<tr><td>Low</td><td>${low}</td><td>-21.67%</td></tr>
<tr><td>High</td><td>${high}</td><td>+124.11%</td></tr>
<tr><td>Median</td><td>${obj}</td><td>{chg}%</td></tr>
</table>"""

# ticker -> (precio, peg, fwd, fcf, roic, sma200, ev, rsi, objetivo)
DATOS = {
    "NVDA":  (215.00, 0.50, 20.00, 2.60, 100.0, 196.00, 26.0, 50.0, 300.00),
    "META":  (580.00, 0.95, 18.00, 2.80,  25.0, 620.00, 13.0, 49.0, 750.00),
    "AMZN":  (262.00, 1.30, 28.00, -0.40, 12.0, 240.00, 11.5, 51.0, 330.00),
    "MSFT":  (500.00, 1.55, 25.00, 1.80,  26.0, 432.00, 17.0, 66.0, 570.00),
    "GOOGL": (345.00, 2.00, 26.00, 1.30,  25.0, 334.00, 12.5, 45.0, 430.00),
    "AAPL":  (315.00, 3.20, 34.00, 3.00, 102.0, 283.00, 27.0, 51.0, 327.00),
    "TSLA":  (348.00, 6.70, 182.0, 0.40,   5.0, 402.00, 111.0, 51.0, 392.00),
}

# Imitan la estructura real de newhedge: un menu que MENCIONA la metrica
# (con numeros que no son el valor) y despues el titulo con el dato bueno.
# La primera version del script mordia el anzuelo del menu.
_MENU = ("Charts MVRV Z Score 38 Rhold Ratio 38 Puell Multiple 12 "
         "Realized Price 7 Compare metrics across 38 indicators. ")

_NEWHEDGE = {
    "mvrv-z-score":        _MENU + "BTC Daily Price $78,494.55 MVRV Z Score 1.42 Learn more",
    "puell-multiple":      _MENU + "BTC Daily Price $79,120.00 Puell Multiple 1.11 Learn more",
    "realized-hodl-ratio": _MENU + "BTC Daily Price $78,943.24 Rhold Ratio 2,450.5 Learn more",
    "realized-price":      _MENU + "BTC Daily Price $78,943.24 Realized Price $54,120 Learn more",
    # El "200 Day Moving Average 1D 1W 1M" imita los botones del grafico:
    # la etiqueta va seguida de un "1" que parece un numero valido. Fue
    # exactamente esto lo que escribio sma200 = 1 en la pagina real.
    "mayer-multiple":      _MENU + "BTC Daily Price $79,120.00 200 Day Moving Average 1D 1W 1M "
                                   "Mayer Multiple 1.12 Learn more",
}


def get(url):
    if "alternative.me" in url:
        return '{"data":[{"value":"41","value_classification":"Fear"}]}'
    if "newhedge.io" in url:
        for k, v in _NEWHEDGE.items():
            if k in url:
                return f"<html><body>{v}</body></html>"
        raise RuntimeError("url newhedge no prevista: " + url)
    if "stockanalysis.com" in url:
        tk = url.rstrip("/").split("/")[-2].upper()
        if tk not in DATOS:
            raise RuntimeError("ticker no previsto: " + tk)
        p, peg, fwd, fcf, roic, sma, ev, rsi, obj = DATOS[tk]
        chg = (obj / p - 1) * 100
        if url.endswith("forecast/"):
            return _FORECAST.format(obj=round(obj, 2), chg=round(chg, 2),
                                    low=round(obj * 0.8, 2), high=round(obj * 1.4, 2))
        return _STATS.format(cambio52=-23.52, peg=peg, fwd=fwd, fcf=fcf,
                             roic=roic, sma=sma, ev=ev, rsi=rsi)
    raise RuntimeError("url no prevista: " + url)
