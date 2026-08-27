#!/usr/bin/env python3
"""
Precio del gasoleo A en Tudela (Navarra) y estimacion a 1-2 semanas.

Idea: el surtidor espanol sigue al crudo con un desfase de una o dos
semanas ("efecto cohete y pluma"). Asi que lo que ya se movio el Brent y
todavia NO se ha trasladado al surtidor es, aproximadamente, lo que viene.

Las tres fuentes estan verificadas una a una contra su respuesta real:
  - Ministerio  : precios de todas las gasolineras, actualizado a diario
  - FRED        : Brent diario en texto plano, sin clave
  - Frankfurter : EUR/USD del BCE, sin clave

Igual que en update.py: si un dato no se puede leer, se conserva el
anterior y se avisa. Nunca se escriben cifras inventadas.
"""

import json
import re
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
HTML = RAIZ / "diesel.html"
HIST = RAIZ / "historico-diesel.json"
ESTADO = RAIZ / "senal-diesel.json"     # ultima senal emitida, para no repetir avisos
AVISO_TXT = RAIZ / "aviso-diesel.txt"   # lo lee el workflow; se borra al enviarlo

PROVINCIA_ID = "31"          # Navarra (codigo INE)
MUNICIPIO = "tudela"
COMBUSTIBLE = "Precio Gasoleo A"

URL_ESTACIONES = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes"
                  "/PreciosCarburantes/EstacionesTerrestres/FiltroProvincia/" + PROVINCIA_ID)
URL_BRENT = "https://fred.stlouisfed.org/data/DCOILBRENTEU.txt"
URL_FX = "https://api.frankfurter.dev/v1/latest?from=USD&to=EUR"

LITROS_BARRIL = 159.0
IVA = 1.21
# Traslacion incompleta: historicamente al surtidor llega en torno al 80%
# del movimiento del crudo, y mas despacio cuando baja que cuando sube.
TRASLACION = 0.80
VENTANA = 14                 # dias del desfase que asumimos

avisos = []


def aviso(m):
    avisos.append(m)
    print("  aviso:", m)


def _f(txt):
    """'1,759' -> 1.759 ; '' -> None. El Ministerio usa coma decimal."""
    if not txt:
        return None
    try:
        v = float(str(txt).strip().replace(",", "."))
    except ValueError:
        return None
    return v if 0.3 < v < 5.0 else None      # un litro fuera de ahi no es real


# --------------------------------------------------------------------------
# recogida
# --------------------------------------------------------------------------
def lee_estaciones(get):
    """Devuelve (lista_tudela, medianas) leyendo solo la provincia."""
    crudo = json.loads(get(URL_ESTACIONES))
    lista = crudo.get("ListaEESSPrecio") or []
    if not lista:
        aviso("Ministerio: lista de estaciones vacia")
        return [], {}

    prov, tud = [], []
    for e in lista:
        p = _f(e.get(COMBUSTIBLE))
        if p is None:
            continue
        prov.append(p)
        if (e.get("Municipio") or "").strip().lower() == MUNICIPIO:
            tud.append({
                "precio": p,
                "rotulo": (e.get("Rótulo") or "").strip(),
                "direccion": (e.get("Dirección") or "").strip(),
                "horario": (e.get("Horario") or "").strip(),
            })

    if not tud:
        aviso(f"no hay gasolineras con gasoleo A en {MUNICIPIO.title()}; "
              f"se usara la provincia")
    tud.sort(key=lambda x: x["precio"])
    med = {
        "provincia": round(statistics.median(prov), 4) if prov else None,
        "municipio": round(statistics.median([x["precio"] for x in tud]), 4) if tud else None,
        "min": tud[0]["precio"] if tud else (min(prov) if prov else None),
        "n_prov": len(prov),
        "n_mun": len(tud),
    }
    return tud, med


def lee_brent(get):
    """Ultimo valor valido de la serie de FRED. Formato: 'YYYY-MM-DD| 68.42'.
    Los dias sin dato traen un punto; hay que saltarlos."""
    txt = get(URL_BRENT)
    filas = []
    for linea in txt.splitlines():
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\s*\|\s*(\S+)\s*$", linea.strip())
        if not m:
            continue
        try:
            v = float(m.group(2))
        except ValueError:
            continue                      # '.' = sin cotizacion ese dia
        if 5 < v < 400:
            filas.append((m.group(1), v))
    if not filas:
        aviso("Brent: no se pudo interpretar la serie de FRED")
        return None, None
    return filas[-1][1], filas[-1][0]


def lee_fx(get):
    j = json.loads(get(URL_FX))
    v = (j.get("rates") or {}).get("EUR")
    if not isinstance(v, (int, float)) or not (0.5 < v < 1.6):
        aviso("EUR/USD fuera de rango o ausente")
        return None
    return float(v)


# --------------------------------------------------------------------------
# historico y estimacion
# --------------------------------------------------------------------------
def carga_hist():
    if HIST.exists():
        try:
            return json.loads(HIST.read_text(encoding="utf-8"))
        except Exception as e:
            aviso(f"historico ilegible, se empieza de cero ({e})")
    return {}


def brent_eur_litro(brent_usd, fx):
    """Coste del crudo por litro, en euros. Base de la estimacion."""
    if brent_usd is None or fx is None:
        return None
    return brent_usd * fx / LITROS_BARRIL


def busca_atras(hist, clave, dias):
    """Registro mas cercano a hace N dias, tolerando huecos de fin de semana."""
    objetivo = date.today() - timedelta(days=dias)
    mejor, mejor_dist = None, 99
    for f, reg in hist.items():
        if clave not in reg or reg[clave] is None:
            continue
        try:
            d = datetime.strptime(f, "%Y-%m-%d").date()
        except ValueError:
            continue
        dist = abs((d - objetivo).days)
        if dist <= 4 and dist < mejor_dist:
            mejor, mejor_dist = reg[clave], dist
    return mejor


def estima(hist, hoy):
    """(pendiente_en_euros_litro, texto) o (None, motivo)."""
    crudo_hoy = hoy.get("crudo_l")
    surtidor_hoy = hoy.get("municipio") or hoy.get("provincia")
    if crudo_hoy is None or surtidor_hoy is None:
        return None, "faltan datos de hoy"

    crudo_antes = busca_atras(hist, "crudo_l", VENTANA)
    surtidor_antes = busca_atras(hist, "municipio", VENTANA) or \
        busca_atras(hist, "provincia", VENTANA)
    if crudo_antes is None or surtidor_antes is None:
        return None, "aun no hay suficiente historico"

    esperado = (crudo_hoy - crudo_antes) * IVA * TRASLACION
    ocurrido = surtidor_hoy - surtidor_antes
    return esperado - ocurrido, None


def clasifica(pend):
    """La senal en una palabra. El umbral es medio centimo por litro: por
    debajo de eso el ruido del dia a dia manda mas que la tendencia."""
    if pend is None:
        return "neutro"
    if pend < -0.005:
        return "baja"
    if pend > 0.005:
        return "sube"
    return "neutro"


def revisa_senal(senal, pend, precio_hoy):
    """Escribe aviso-diesel.txt SOLO si la senal ha cambiado a algo accionable.
    Si no cambia, no se escribe nada y no llega ningun correo."""
    previa = None
    if ESTADO.exists():
        try:
            previa = json.loads(ESTADO.read_text(encoding="utf-8")).get("senal")
        except Exception:
            previa = None

    if senal == previa:
        return False

    ESTADO.write_text(json.dumps({"senal": senal, "desde": date.today().isoformat()},
                                 indent=1), encoding="utf-8")

    if senal == "neutro":
        return False        # volver a la calma no merece un correo

    hoy = f"{precio_hoy:.3f} €/l" if precio_hoy else "sin precio"
    if senal == "baja":
        titulo = f"⛽ El diésel debería BAJAR en Tudela ({cent(pend)}/l pendiente)"
        cuerpo = (
            f"El crudo ha bajado más de lo que ha bajado el surtidor.\n\n"
            f"- Recorrido pendiente estimado: **{cent(pend)} por litro**\n"
            f"- Precio más barato ahora mismo: **{hoy}**\n\n"
            f"Si la relación habitual se cumple, eso debería llegar al surtidor "
            f"en una o dos semanas. **Merece la pena esperar** si puedes.\n\n"
            f"Estimación, no certeza. Cierra este aviso cuando lo hayas leído.")
    else:
        titulo = f"⛽ El diésel debería SUBIR en Tudela (+{abs(pend)*100:.1f} c€/l pendiente)"
        cuerpo = (
            f"El crudo ha subido más de lo que ha subido el surtidor.\n\n"
            f"- Recorrido pendiente estimado: **{cent(pend)} por litro**\n"
            f"- Precio más barato ahora mismo: **{hoy}**\n\n"
            f"Ese recorrido suele trasladarse en una o dos semanas. "
            f"**Mejor llenar antes que después.**\n\n"
            f"Estimación, no certeza. Cierra este aviso cuando lo hayas leído.")

    AVISO_TXT.write_text(titulo + "\n" + cuerpo, encoding="utf-8")
    print(f"  señal nueva: {previa or '—'} → {senal} (se enviará aviso)")
    return True


# --------------------------------------------------------------------------
# escritura de la pagina
# --------------------------------------------------------------------------
def cent(v):
    return f"{v * 100:+.1f}".replace("-", "−") + " c€"


def pinta(datos):
    from bs4 import BeautifulSoup
    sopa = BeautifulSoup(HTML.read_text(encoding="utf-8"), "html.parser")

    def poner(sel, txt):
        el = sopa.select_one(sel)
        if el is not None and txt is not None:
            el.string = str(txt)

    m = datos["medianas"]
    if m.get("min") is not None:
        poner("#precio-min", f"{m['min']:.3f} €")
    if m.get("municipio") is not None:
        poner("#precio-med", f"{m['municipio']:.3f} €")
    if m.get("provincia") is not None:
        poner("#precio-prov", f"{m['provincia']:.3f} €")
    poner("#fecha", datos["fecha"])
    poner("#n-est", f"{m.get('n_mun', 0)} en Tudela · {m.get('n_prov', 0)} en Navarra")

    if datos.get("brent") is not None:
        poner("#brent", f"{datos['brent']:.2f} $")
        poner("#brent-fecha", datos.get("brent_fecha") or "")
    if datos.get("fx") is not None:
        poner("#fx", f"{1 / datos['fx']:.4f} $/€")

    # tabla de las mas baratas
    tbody = sopa.select_one("#tabla-estaciones tbody")
    if tbody is not None and datos["estaciones"]:
        tbody.clear()
        for e in datos["estaciones"][:6]:
            tr = sopa.new_tag("tr")
            for valor, clase in ((f"{e['precio']:.3f} €", "num"),
                                 (e["rotulo"] or "—", None),
                                 (e["direccion"] or "—", "dir")):
                td = sopa.new_tag("td")
                if clase:
                    td["class"] = [clase]
                td.string = valor
                tr.append(td)
            tbody.append(tr)

    # tendencia y estimacion
    tend = datos.get("tendencia")
    caja = sopa.select_one("#tendencia")
    if caja is not None:
        if tend is None:
            poner("#tendencia-valor", "—")
            poner("#tendencia-texto", "Aún no hay histórico suficiente. "
                                      "Se acumula solo, un dato por día.")
            caja["data-tono"] = "neutro"
        else:
            poner("#tendencia-valor", cent(tend))
            baja = tend < -0.002
            sube = tend > 0.002
            caja["data-tono"] = "baja" if baja else ("sube" if sube else "neutro")
            poner("#tendencia-texto",
                  "El surtidor viene bajando estos días."
                  if baja else "El surtidor viene subiendo estos días."
                  if sube else "El surtidor lleva días prácticamente plano.")

    pend, motivo = datos["pendiente"], datos["motivo"]
    box = sopa.select_one("#prevision")
    if box is not None:
        if pend is None:
            poner("#prevision-valor", "—")
            poner("#prevision-texto",
                  "Necesita unas dos semanas de histórico para poder estimar. "
                  f"({motivo})")
            box["data-tono"] = "neutro"
        else:
            poner("#prevision-valor", cent(pend))
            senal = clasifica(pend)
            box["data-tono"] = senal
            if senal == "baja":
                t = ("El crudo ya ha bajado más de lo que ha bajado el surtidor. "
                     "Si la relación habitual se cumple, eso debería llegar al "
                     "precio en una o dos semanas. Merece la pena esperar.")
            elif senal == "sube":
                t = ("El crudo ha subido más de lo que ha subido el surtidor. "
                     "Ese recorrido suele trasladarse en una o dos semanas. "
                     "Mejor llenar antes que después.")
            else:
                t = ("El surtidor ya recoge lo que ha hecho el crudo. "
                     "No hay recorrido pendiente en ninguna dirección.")
            poner("#prevision-texto", t)

    HTML.write_text(str(sopa), encoding="utf-8")


# --------------------------------------------------------------------------
def main(get=None):
    if get is None:
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; diesel-tudela/1.0)"})

        def get(url):
            r = s.get(url, timeout=45)
            r.raise_for_status()
            return r.text

    print("Diésel Tudela…")
    try:
        estaciones, medianas = lee_estaciones(get)
    except Exception as e:
        aviso(f"Ministerio no leido ({e})")
        estaciones, medianas = [], {}

    try:
        brent, brent_fecha = lee_brent(get)
    except Exception as e:
        aviso(f"Brent no leido ({e})")
        brent = brent_fecha = None

    try:
        fx = lee_fx(get)
    except Exception as e:
        aviso(f"EUR/USD no leido ({e})")
        fx = None

    hist = carga_hist()
    hoy_k = date.today().isoformat()
    registro = {
        "municipio": medianas.get("municipio"),
        "provincia": medianas.get("provincia"),
        "min": medianas.get("min"),
        "brent": brent,
        "fx": fx,
        "crudo_l": brent_eur_litro(brent, fx),
    }
    # solo se guarda si hay algo que guardar
    if any(v is not None for v in registro.values()):
        hist[hoy_k] = registro
        HIST.write_text(json.dumps(hist, indent=1, sort_keys=True), encoding="utf-8")

    # tendencia del surtidor en la ultima semana
    ref = busca_atras(hist, "municipio", 7) or busca_atras(hist, "provincia", 7)
    actual = registro["municipio"] or registro["provincia"]
    tendencia = (actual - ref) if (ref is not None and actual is not None) else None

    pendiente, motivo = estima(hist, registro)
    revisa_senal(clasifica(pendiente), pendiente, medianas.get("min"))

    if HTML.exists():
        pinta({
            "fecha": date.today().strftime("%d/%m/%Y"),
            "estaciones": estaciones,
            "medianas": medianas,
            "brent": brent,
            "brent_fecha": brent_fecha,
            "fx": fx,
            "tendencia": tendencia,
            "pendiente": pendiente,
            "motivo": motivo,
        })
        print("  diesel.html actualizado")
    else:
        aviso("diesel.html no encontrado; no se pinta nada")

    print("  sin incidencias" if not avisos else f"  {len(avisos)} aviso(s)")
    return 0


if __name__ == "__main__":
    main()
