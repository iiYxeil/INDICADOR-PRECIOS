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
def _num(txt, lo=None, hi=None):
    """Primer numero de un texto ('1.23%', '-0.41%', '$52,970').

    Si se dan lo/hi y el numero cae fuera, devuelve None: haber encontrado
    UN numero no significa haber encontrado EL numero. Sin este filtro un
    patron que engancha el sitio equivocado escribe basura en la pagina.
    """
    if txt is None:
        return None
    m = re.search(r"-?[\d,]+\.?\d*", str(txt).replace("−", "-"))
    if not m:
        return None
    try:
        v = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    if lo is not None and v < lo:
        return None
    if hi is not None and v > hi:
        return None
    return v


def _tras_etiqueta(texto, etiquetas, lo, hi, hueco=14):
    """Numero que va JUSTO detras de una de las etiquetas.

    Dos trampas reales de newhedge, aprendidas a base de escribir basura
    en la pagina:
      1) el menu de navegacion menciona las mismas metricas seguidas de
         numeros que NO son el valor;
      2) esos numeros senuelo pueden caer dentro del rango plausible, asi
         que validar el rango no basta.
    El bloque util siempre arranca en "BTC Daily Price", asi que se busca
    solo a partir de ahi. Si esa ancla no aparece, se usa la ultima
    coincidencia del texto, que suele ser el dato y no el menu.
    """
    corte = texto.rfind("BTC Daily Price")
    ambitos = []
    if corte != -1:
        ambitos.append(("ancla", texto[corte:]))
    ambitos.append(("todo", texto))

    for tipo, ambito in ambitos:
        hallados = []
        for et in etiquetas:
            for m in re.finditer(re.escape(et), ambito, re.I):
                trozo = ambito[m.end():m.end() + hueco + 24]
                mm = re.match(r"[^0-9\-]{0,%d}(-?[\d,]+\.?\d*)" % hueco, trozo)
                if mm:
                    v = _num(mm.group(1), lo, hi)
                    if v is not None:
                        hallados.append(v)
        if hallados:
            return hallados[0] if tipo == "ancla" else hallados[-1]
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


_VETADAS = ("target", "/", "sales", "book", "earnings ratio", "52-week", "52 week")


def _exacto(tabla, etiqueta):
    """Coincidencia exacta de etiqueta. Imprescindible cuando conviven
    'Target Change', 'Target Low Change' y 'Target High Change': con
    busqueda por 'contiene' cualquiera de las tres puede ganar."""
    return tabla.get(etiqueta.strip().lower())


def _busca(tabla, *claves):
    """Primera fila cuya etiqueta contenga la clave, ignorando parecidos
    peligrosos: 'Price Target' o 'Price/Sales' no son 'Current Price'."""
    for c in claves:
        for k, v in tabla.items():
            if c in k and not any(x in k for x in _VETADAS if x not in c):
                return v
    return None


def recoge_accion(ticker, get):
    """Devuelve dict con lo que se haya podido leer. Claves ausentes = no leido."""
    d = {}
    try:
        t = _tabla_stockanalysis(get(f"https://stockanalysis.com/stocks/{ticker}/statistics/"))
        d["peg"]   = _num(_busca(t, "peg ratio"), -50, 50)
        d["fwd"]   = _num(_busca(t, "forward pe", "forward p/e"), 0, 2000)
        d["fcf"]   = _num(_busca(t, "fcf yield", "free cash flow yield"), -60, 60)
        d["roic"]  = _num(_busca(t, "return on invested capital", "roic"), -300, 600)
        d["sma"]   = _num(_busca(t, "200-day moving average", "200 day moving average"), 0.5, 100000)
        d["ev"]    = _num(_busca(t, "ev/ebitda", "ev / ebitda"), -200, 2000)
        d["rsi"]   = _num(_busca(t, "relative strength index", "rsi"), 0, 100)
        # Aqui NO se busca el precio: /statistics/ no tiene fila de precio,
        # y la unica que contiene "Price" es "52-Week Price Change", que es
        # un porcentaje. Buscarlo aqui fue lo que puso $-23.52 en Meta.
    except Exception as e:
        aviso(f"{ticker}: estadisticas no leidas ({e})")
    try:
        t2 = _tabla_stockanalysis(f"https://stockanalysis.com/stocks/{ticker}/forecast/"
                                  if False else get(f"https://stockanalysis.com/stocks/{ticker}/forecast/"))
        obj = _num(_exacto(t2, "target price"), 0.5, 100000)
        chg = _num(_exacto(t2, "target change"), -95, 500)
        if obj is not None and chg is not None:
            d["objetivo"] = obj
            d["consenso"] = chg                    # el potencial, ya en %
            d["precio"] = obj / (1 + chg / 100.0)  # el precio, deducido
        else:
            aviso(f"{ticker}: objetivo o potencial no leidos")
    except Exception as e:
        aviso(f"{ticker}: prevision no leida ({e})")

    d = {k: v for k, v in d.items() if v is not None}

    # Comprobacion del cociente, no solo de los datos sueltos: una accion
    # grande no cotiza un 60% lejos de su media de 200 dias. Si sale eso,
    # alguno de los dos numeros es falso y se descarta la metrica.
    if "precio" in d and "sma" in d:
        desv = d["precio"] / d["sma"] - 1
        if not (-0.6 <= desv <= 1.5):
            aviso(f"{ticker}: precio vs SMA200 incoherente ({desv * 100:.0f}%), se descarta")
            d.pop("sma")
    return d


def recoge_btc(get):
    """Rangos plausibles para cada metrica; fuera de rango = no leido."""
    d = {}
    try:
        j = json.loads(get("https://api.alternative.me/fng/?limit=1"))
        v = _num(j["data"][0]["value"], 0, 100)
        if v is not None:
            d["fg"] = v
        else:
            aviso("Fear & Greed fuera de rango")
    except Exception as e:
        aviso(f"Fear & Greed no leido ({e})")

    # (clave, url, etiquetas tal como aparecen en la web, minimo, maximo)
    fuentes = [
        ("mvrv",  "mvrv-z-score",        ["MVRV Z Score", "MVRV Z-Score"],      -5,     15),
        ("puell", "puell-multiple",      ["Puell Multiple"],                     0.05,  15),
        ("rhodl", "realized-hodl-ratio", ["Rhold Ratio", "RHODL Ratio"],        50, 200000),
        ("real",  "realized-price",      ["Realized Price"],                  1000, 500000),
        # La media de 200 dias NO se raspa: se deduce del propio Mayer
        # Multiple (media = precio / multiplo). Es mucho mas estable que
        # buscar la etiqueta "200 Day Moving Average", que ya nos escribio
        # un 1 en la pagina, y ademas queda comprobable por construccion.
        ("mayer", "mayer-multiple",      ["Mayer Multiple"],                  0.2,      5),
    ]
    for clave, ruta, etiquetas, lo, hi in fuentes:
        try:
            txt = BeautifulSoup(get("https://newhedge.io/bitcoin/" + ruta), "lxml") \
                .get_text(" ", strip=True)
            v = _tras_etiqueta(txt, etiquetas, lo, hi)
            if v is not None:
                d[clave] = v
            else:
                aviso(f"BTC {clave}: no se encontro un valor plausible")
            # Cada pagina trae su propio precio y pueden diferir unos
            # dolares. Se guarda el de la pagina del Mayer aparte, porque
            # la media de 200 dias hay que dividirla por SU precio, no por
            # el de otra pagina, o el cociente sale sesgado.
            pr = _tras_etiqueta(txt, ["BTC Daily Price", "Bitcoin Price"],
                                1000, 1000000)
            if pr is not None:
                d.setdefault("precio", pr)
                if clave == "mayer":
                    d["precio_mayer"] = pr
        except Exception as e:
            aviso(f"BTC {clave} no leido ({e})")

    # media de 200 dias por division, y comprobacion de que cuadra
    base = d.get("precio_mayer") or d.get("precio")
    if "mayer" in d and base:
        sma = base / d["mayer"]
        if 1000 <= sma <= 500000:
            d["sma"] = sma
        else:
            aviso(f"BTC sma200 derivada fuera de rango ({sma:.1f})")
    else:
        aviso("BTC sma200: falta el Mayer Multiple o el precio")
    d.pop("precio_mayer", None)

    # Ultima red: comprobar los cocientes derivados, no solo los datos
    # sueltos. Un dato aislado puede ser plausible y aun asi producir una
    # metrica absurda; esto es lo que dejo pasar el sma200 = 1.
    if "precio" in d:
        if "sma" in d and not (0.2 <= d["precio"] / d["sma"] <= 5):
            aviso("BTC: Mayer resultante incoherente, se descarta sma200")
            d.pop("sma")
        if "real" in d and not (0.5 <= d["precio"] / d["real"] <= 10):
            aviso("BTC: ratio de precio realizado incoherente, se descarta")
            d.pop("real")
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
        if i == 4 and "cons" in s and "consenso" in d:
            return f"{d['consenso']:+.0f}%".replace("-", "−"), s["cons"]
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


def lee_anchor(html, clave, por_defecto=None):
    m = re.search(rf"\b{clave}\s*:\s*(-?[\d.]+)", html)
    return float(m.group(1)) if m else por_defecto


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
    if "precio" in btc:
        # puell y puellAtPrice DEBEN ir juntos: el script escala el Puell por
        # (precio_actual / puellAtPrice). Si uno se actualiza sin el otro,
        # la metrica queda desplazada de forma silenciosa.
        anchor["price"] = btc["precio"]
        anchor["puellAtPrice"] = btc["precio"]

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
        if "consenso" in d:
            sc["cons"] = s_cons(d["consenso"])
        if "roic" in d: sc["roic"] = s_roic(d["roic"])
        if "sma" in d and precio:
            sc["sma"] = s_sma(precio / d["sma"] - 1)
        if "rsi" in d:  sc["rsi"] = s_rsi(d["rsi"])
        filas[tk] = {"d": d, "sc": sc}

    # Notas estaticas de BTC: el navegador las recalcula en vivo, pero deben
    # ser correctas tambien antes de que el JS corra (y si nunca corre).
    try:
        precio = anchor.get("price", lee_anchor(html, "price"))
        sma200 = anchor.get("sma200", lee_anchor(html, "sma200"))
        realiz = anchor.get("realizedPrice", lee_anchor(html, "realizedPrice"))
        puellv = anchor.get("puell", lee_anchor(html, "puell"))
        rsiv   = lee_anchor(html, "rsiFallback", 50)
        if all(x for x in (precio, sma200, realiz, puellv)):
            banda = next((i for i, (_, u) in enumerate(C.BANDAS_BTC) if precio < u),
                         len(C.BANDAS_BTC) - 1)
            seis = [
                daily.get("mvrv", lee_anchor(html, "mvrv", 50)),
                s_puell(puellv),
                s_real(precio / realiz),
                daily.get("rhodl", lee_anchor(html, "rhodl", 50)),
                s_mayer(precio / sma200),
                BANDA_SCORES[banda],
            ]
            dos = [s_rsi(rsiv), daily.get("fg", lee_anchor(html, "fg", 50))]
            pinta_fila(sopa, "puell",    f"{puellv:.2f}×", s_puell(puellv))
            pinta_fila(sopa, "realized",  f"{precio / realiz:.2f}×", s_real(precio / realiz))
            pinta_fila(sopa, "mayer",     f"{precio / sma200:.2f}×", s_mayer(precio / sma200))
            pinta_fila(sopa, "rainbow",   C.BANDAS_BTC[banda][0], BANDA_SCORES[banda])
            pinta_fila(sopa, "rsi",       f"{rsiv:.1f}", s_rsi(rsiv))
            pinta_nota(sopa, "val", sum(seis) / len(seis))
            pinta_nota(sopa, "mom", sum(dos) / len(dos))
    except Exception as e:
        aviso(f"notas de BTC no recalculadas ({e})")

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
