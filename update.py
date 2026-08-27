#!/usr/bin/env python3
"""
Reescribe index.html con datos frescos.

Principio de diseno: NUNCA empeorar la pagina. Si un dato no se puede
leer, se conserva el que ya estaba. Un fallo de red deja la pagina
exactamente como estaba, nunca a medias ni con ceros.

Uso:
    python update.py              # normal, va a la red
    python update.py --selftest   # con datos de prueba, sin red
"""

import json
import math
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
import config as C

RAIZ = Path(__file__).resolve().parent
HTML = RAIZ / "index.html"
UA = {"User-Agent": "Mozilla/5.0 (compatible; barato-o-caro/1.0)"}

avisos = []


def aviso(msg):
    avisos.append(msg)
    print("  aviso:", msg)


# --------------------------------------------------------------------------
# puntuaciones — identicas a las que usa la pagina
# --------------------------------------------------------------------------
def clamp(v):
    return max(0.0, min(100.0, v))


def s_peg(v):        return clamp(100 * (1 - (v - 0.5) / 2.5))
def s_fwd(r):        return clamp(100 * (1 - (r - 0.5) / 1.0))
def s_fcf(pct):      return clamp(100 * (pct / 6))
def s_ev(r):         return clamp(100 * (1 - (r - 0.5) / 1.0))
def s_cons(pct):     return clamp(100 * (pct / 40))
def s_roic(pct):     return clamp(100 * (pct / 40))
def s_sma(d):        return clamp(100 * (1 - (d + 0.20) / 0.50))
def s_rsi(v):        return clamp(100 - v)
def s_mvrv(z):       return clamp(100 * (1 - z / 7))
def s_puell(p):      return clamp(100 * (1 - (p - 0.5) / 3.5))
def s_real(r):       return clamp(100 * (1 - (r - 1) / 2))
def s_rhodl(h):      return clamp(100 * (1 - math.log10(h / 1000)))
def s_mayer(m):      return clamp(100 * (1 - (m - 0.8) / 1.6))

BANDA_SCORES = [100, 87.5, 75, 62.5, 50, 37.5, 25, 12.5, 0]


def clasifica(s):
    if s >= 80: return "Muy barata", "▼▼", "good", "c-vgood"
    if s >= 60: return "Barata", "▼", "good", "c-good"
    if s >= 40: return "Justa", "●", "neutral", "c-mid"
    if s >= 20: return "Cara", "▲", "serious", "c-bad"
    return "Muy cara", "▲▲", "critical", "c-vbad"


def cubo(s):
    return "cheap" if s >= 60 else ("rich" if s < 40 else "mid")


# --------------------------------------------------------------------------
# recogida de datos
# --------------------------------------------------------------------------
def _num(txt):
    """Extrae el primer numero de un texto tipo '1.23%', '-0.41%', '$52,970'."""
    if txt is None:
        return None
    m = re.search(r"-?[\d,]+\.?\d*", str(txt).replace("−", "-"))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _tabla_stockanalysis(html):
    """Devuelve {etiqueta_en_minusculas: texto_valor} de todas las filas."""
    sopa = BeautifulSoup(html, "lxml")
    out = {}
    for tr in sopa.find_all("tr"):
        celdas = tr.find_all("td")
        if len(celdas) >= 2:
            k = celdas[0].get_text(" ", strip=True).lower()
            v = celdas[1].get_text(" ", strip=True)
            if k and k not in out:
                out[k] = v
    return out


def _busca(tabla, *claves):
    for c in claves:
        for k, v in tabla.items():
            if c in k:
                return v
    return None


def recoge_accion(ticker, get):
    """Devuelve dict con lo que se haya podido leer. Claves ausentes = no leido."""
    d = {}
    try:
        t = _tabla_stockanalysis(get(f"https://stockanalysis.com/stocks/{ticker}/statistics/"))
        d["peg"]   = _num(_busca(t, "peg ratio"))
        d["fwd"]   = _num(_busca(t, "forward pe", "forward p/e"))
        d["fcf"]   = _num(_busca(t, "fcf yield", "free cash flow yield"))
        d["roic"]  = _num(_busca(t, "return on invested capital", "roic"))
        d["sma"]   = _num(_busca(t, "200-day moving average", "200 day moving average"))
        d["ev"]    = _num(_busca(t, "ev/ebitda", "ev / ebitda"))
        d["rsi"]   = _num(_busca(t, "relative strength index", "rsi"))
        d["precio"] = _num(_busca(t, "current price", "share price", "price"))
    except Exception as e:
        aviso(f"{ticker}: estadisticas no leidas ({e})")
    try:
        t2 = _tabla_stockanalysis(get(f"https://stockanalysis.com/stocks/{ticker}/forecast/"))
        d["objetivo"] = _num(_busca(t2, "price target", "average price target"))
    except Exception as e:
        aviso(f"{ticker}: prevision no leida ({e})")
    return {k: v for k, v in d.items() if v is not None}


def recoge_btc(get):
    d = {}
    try:
        j = json.loads(get("https://api.alternative.me/fng/?limit=1"))
        d["fg"] = float(j["data"][0]["value"])
    except Exception as e:
        aviso(f"Fear & Greed no leido ({e})")
    for clave, url, patron in [
        ("mvrv",  "https://newhedge.io/bitcoin/mvrv-z-score",       r"MVRV Z[- ]Score[^0-9\-]{0,80}(-?\d+\.?\d*)"),
        ("puell", "https://newhedge.io/bitcoin/puell-multiple",     r"Puell Multiple[^0-9\-]{0,80}(\d+\.?\d*)"),
        ("rhodl", "https://newhedge.io/bitcoin/realized-hodl-ratio", r"RHODL[^0-9]{0,80}([\d,]+\.?\d*)"),
        ("real",  "https://newhedge.io/bitcoin/realized-price",     r"Realized Price[^0-9$]{0,60}\$?([\d,]+\.?\d*)"),
        ("sma",   "https://newhedge.io/bitcoin/mayer-multiple",     r"200[- ]Day[^0-9$]{0,60}\$?([\d,]+\.?\d*)"),
    ]:
        try:
            txt = BeautifulSoup(get(url), "lxml").get_text(" ", strip=True)
            m = re.search(patron, txt, re.I)
            if m:
                d[clave] = float(m.group(1).replace(",", ""))
            else:
                aviso(f"BTC {clave}: patron no encontrado")
        except Exception as e:
            aviso(f"BTC {clave} no leido ({e})")
    return d


# --------------------------------------------------------------------------
# reescritura del HTML
# --------------------------------------------------------------------------
def pinta_fila(sopa, clave, texto, score):
    fila = sopa.select_one(f'.ind-row[data-k="{clave}"]')
    if not fila:
        return
    et, _, cls, _ = clasifica(score)
    v = fila.select_one(".ind-val")
    t = fila.select_one(".ind-tag")
    b = fila.select_one(".ind-bar i")
    if v: v.string = texto
    if t:
        t.string = et
        t["class"] = ["ind-tag", cls]
    if b:
        b["class"] = [cls]
        b["style"] = f"width:{score:.0f}%"


def pinta_nota(sopa, prefijo, score):
    et, ico, cls, _ = clasifica(score)
    n = sopa.select_one(f"#{prefijo}-score")
    if n:
        n.string = str(round(score))
        n["style"] = f"color:var(--{cls})"
    b = sopa.select_one(f"#{prefijo}-bar")
    if b:
        b["class"] = [cls]
        b["style"] = f"width:{clamp(score):.1f}%"
    p = sopa.select_one(f"#{prefijo}-pill")
    if p:
        p.string = f"{ico} {et}"
        p["class"] = ["status-pill", cls]
    a = sopa.select_one(f"#{prefijo}-avg")
    if a:
        a.string = str(round(score))


def pinta_acciones(sopa, filas):
    """Actualiza tarjetas y matriz, y las reordena por valoracion."""
    if not filas:
        return

    calc = {}
    for tk, info in filas.items():
        sc = info["sc"]
        val_k = [sc[k] for k in ("peg", "fwd", "fcf", "ev", "cons", "roic") if k in sc]
        mom_k = [sc[k] for k in ("sma", "rsi") if k in sc]
        if not val_k or not mom_k:
            aviso(f"{tk}: faltan metricas, se conserva lo anterior")
            continue
        calc[tk] = {
            "val": sum(val_k) / len(val_k),
            "mom": sum(mom_k) / len(mom_k),
            "d": info["d"], "sc": sc,
        }
    if not calc:
        return

    orden = sorted(calc, key=lambda t: -calc[t]["val"])

    # ---- tarjetas ----
    rejilla = sopa.select_one(".grid")
    tarjetas = {}
    for card in sopa.select(".grid > .card"):
        tk_el = card.select_one(".tk")
        if not tk_el:
            continue
        tk = tk_el.get_text(" ", strip=True).split("·")[0].strip().upper()
        tarjetas[tk] = card

    for tk in orden:
        card = tarjetas.get(tk)
        if not card:
            continue
        c = calc[tk]
        precio = c["d"].get("precio")
        if precio:
            tk_el = card.select_one(".tk")
            if tk_el:
                tk_el.string = f"{tk} · ${precio:,.2f}"
        et, ico, cls, _ = clasifica(c["val"])
        pill = card.select_one(".status-pill")
        if pill:
            pill.string = f"{ico} {et}"
            pill["class"] = ["status-pill", cls]
        minis = card.select(".mini")
        for mini, score in zip(minis, (c["val"], c["mom"])):
            _, _, mcls, _ = clasifica(score)
            n = mini.select_one(".mini-num")
            b = mini.select_one(".mini-bar i")
            if n:
                n.string = str(round(score))
                n["style"] = f"color:var(--{mcls})"
            if b:
                b["class"] = [mcls]
                b["style"] = f"width:{score:.0f}%"
        # bandera de contradiccion
        bandera = card.select_one(".conflict-flag")
        choca = (cubo(c["val"]), cubo(c["mom"])) in (("cheap", "rich"), ("rich", "cheap"))
        if choca and not bandera:
            nueva = BeautifulSoup(
                '<div class="conflict-flag">⚠ Las dos lecturas se contradicen</div>',
                "html.parser")
            nota = card.select_one(".card-note")
            (nota.insert_before(nueva) if nota else card.append(nueva))
        elif bandera and not choca:
            bandera.decompose()

    if rejilla:
        for tk in orden:
            if tk in tarjetas:
                rejilla.append(tarjetas[tk])   # append mueve, no copia

    # ---- matriz ----
    tabla = sopa.select_one("table.matrix")
    if not tabla:
        return
    cab = tabla.select("thead th")
    for th, tk in zip(cab[1:], orden):
        th.string = tk

    def dev(a, b):
        return (a / b - 1) * 100

    def txt_val(tk, i):
        d, s = calc[tk]["d"], calc[tk]["sc"]
        if i == 0 and "peg" in d:  return f"{d['peg']:.2f}", s["peg"]
        if i == 1 and "fwd" in d:  return f"{dev(d['fwd'], C.PE_MEDIA_5A[tk]):+.0f}%".replace("-", "−"), s["fwd"]
        if i == 2 and "fcf" in d:  return f"{d['fcf']:.2f}%".replace("-", "−"), s["fcf"]
        if i == 3:
            ev = d.get("ev", C.EV_EBITDA_RESERVA[tk])
            return f"{dev(ev, C.EV_EBITDA_MEDIANA_10A[tk]):+.0f}%".replace("-", "−"), s["ev"]
        if i == 4 and "cons" in s and "objetivo" in d and d.get("precio"):
            return f"{dev(d['objetivo'], d['precio']):+.0f}%".replace("-", "−"), s["cons"]
        if i == 5 and "roic" in d: return f"{d['roic']:.0f}%", s["roic"]
        if i == 6 and "sma" in d and d.get("precio"):
            return f"{dev(d['precio'], d['sma']):+.0f}%".replace("-", "−"), s["sma"]
        if i == 7 and "rsi" in d:  return f"{d['rsi']:.0f}", s["rsi"]
        return None, None

    metricas = [tr for tr in tabla.select("tbody tr")
                if "grp" not in (tr.get("class") or []) and "total" not in (tr.get("class") or [])]
    for i, tr in enumerate(metricas[:8]):
        tds = tr.find_all("td")
        for td, tk in zip(tds, orden):
            texto, score = txt_val(tk, i)
            if texto is None:
                continue
            td.string = texto
            td["class"] = [clasifica(score)[3]]

    for tr, clave in zip(tabla.select("tbody tr.total"), ("val", "mom")):
        for td, tk in zip(tr.find_all("td"), orden):
            s = calc[tk][clave]
            _, _, cls, celda = clasifica(s)
            td.string = str(round(s))
            td["class"] = [celda]
            td["style"] = f"color:var(--{cls})"


def reescribe_anchor(html, **kv):
    """Cambia numeros sueltos dentro del literal ANCHOR = {...} del script."""
    for k, v in kv.items():
        if v is None:
            continue
        patron = rf"(\b{k}\s*:\s*)-?[\d.]+"
        nuevo = rf"\g<1>{v:.6g}"
        html, n = re.subn(patron, nuevo, html, count=1)
        if not n:
            aviso(f"ANCHOR.{k} no encontrado en el script")
    return html


def main(selftest=False):
    if selftest:
        from fixtures import get  # datos de prueba, sin red
    else:
        import requests
        sesion = requests.Session()
        sesion.headers.update(UA)

        def get(url):
            r = sesion.get(url, timeout=30)
            r.raise_for_status()
            return r.text

    html = HTML.read_text(encoding="utf-8")
    sopa = BeautifulSoup(html, "html.parser")  # conserva el marcado tal cual

    # ---------- Bitcoin ----------
    print("Bitcoin…")
    btc = recoge_btc(get)
    anchor = {}
    daily = {}
    if "mvrv" in btc:
        sc = s_mvrv(btc["mvrv"])
        pinta_fila(sopa, "mvrv", f"{btc['mvrv']:.2f}", sc)
        daily["mvrv"] = sc
    if "rhodl" in btc:
        sc = s_rhodl(btc["rhodl"])
        pinta_fila(sopa, "rhodl", f"{btc['rhodl']:,.0f}", sc)
        daily["rhodl"] = sc
    if "fg" in btc:
        sc = s_rsi(btc["fg"])  # 100 - valor
        pinta_fila(sopa, "fg", f"{btc['fg']:.0f}", sc)
        daily["fg"] = sc
    if "sma" in btc:
        anchor["sma200"] = btc["sma"]
        el = sopa.select_one('[data-anchor="sma200"]')
        if el: el.string = f"${btc['sma']:,.0f}"
    if "real" in btc:
        anchor["realizedPrice"] = btc["real"]
        el = sopa.select_one('[data-anchor="realized"]')
        if el: el.string = f"${btc['real']:,.0f}"
    if "puell" in btc:
        anchor["puell"] = btc["puell"]

    # ---------- acciones ----------
    filas = {}
    for tk in C.TICKERS:
        print(f"{tk}…")
        d = recoge_accion(tk, get)
        if not d:
            aviso(f"{tk}: sin datos, se conserva lo anterior")
            continue
        precio = d.get("precio")
        sc = {}
        if "peg" in d:  sc["peg"] = s_peg(d["peg"])
        if "fwd" in d:  sc["fwd"] = s_fwd(d["fwd"] / C.PE_MEDIA_5A[tk])
        if "fcf" in d:  sc["fcf"] = s_fcf(d["fcf"])
        ev = d.get("ev", C.EV_EBITDA_RESERVA[tk])
        sc["ev"] = s_ev(ev / C.EV_EBITDA_MEDIANA_10A[tk])
        if "objetivo" in d and precio:
            sc["cons"] = s_cons((d["objetivo"] / precio - 1) * 100)
        if "roic" in d: sc["roic"] = s_roic(d["roic"])
        if "sma" in d and precio:
            sc["sma"] = s_sma(precio / d["sma"] - 1)
        if "rsi" in d:  sc["rsi"] = s_rsi(d["rsi"])
        filas[tk] = {"d": d, "sc": sc}

    if filas:
        print(f"  {len(filas)}/{len(C.TICKERS)} acciones leidas")
    pinta_acciones(sopa, filas)

    html2 = str(sopa)
    if anchor:
        html2 = reescribe_anchor(html2, **anchor)
    if daily:
        for k, v in daily.items():
            html2, n = re.subn(rf"(\b{k}\s*:\s*)[\d.]+(\s*[,}}])", rf"\g<1>{v:.1f}\g<2>", html2, count=1)
            if not n:
                aviso(f"DAILY.{k} no encontrado")

    if not avisos:
        print("sin incidencias")
    else:
        print(f"{len(avisos)} aviso(s); los datos no leidos conservan su valor anterior")

    HTML.write_text(html2, encoding="utf-8")
    print("index.html actualizado")
    return 0


if __name__ == "__main__":
    sys.exit(main(selftest="--selftest" in sys.argv))
