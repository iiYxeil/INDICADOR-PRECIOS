#!/usr/bin/env python3
"""
Precios de las gasolineras de Tudela y alrededores (30 km).

Lee la API oficial del Ministerio y deja gasolineras.json, que el workflow
publica en la rama "datos". Asi no toca main ni se pisa con actualizar.yml.

Igual que en diesel.py: si el dato no se puede leer no se escribe nada y la
pagina sigue con la ultima copia buena, avisando de su antiguedad. Nunca se
escriben cifras inventadas.

Prueba sin red:  python gasolineras.py --selftest
"""

import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo("Europe/Madrid")
except Exception:                                # sin base de husos: UTC+1
    MADRID = timezone(timedelta(hours=1))

RAIZ = Path(__file__).resolve().parent
SALIDA = RAIZ / "gasolineras.json"

URL_MINISTERIO = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes"
                  "/PreciosCarburantes/EstacionesTerrestres/")
URL_PREVIA = ("https://raw.githubusercontent.com/iiYxeil/INDICADOR-PRECIOS"
              "/datos/gasolineras.json")

CENTRO = (42.0617, -1.6045)      # Tudela
RADIO_KM = 30
MIN_ESPANA = 5000                # menos que esto no es la lista completa
MIN_ZONA = 20                    # alrededor de Tudela siempre hay mas
CAMBIOS_GUARDADOS = 12           # por estacion y combustible

ESPERAS = (0, 30, 90, 180)       # la API falla a ratos: varios intentos

COMBUSTIBLES = {
    "gA": "Precio Gasoleo A",
    "gP": "Precio Gasoleo Premium",
    "g95": "Precio Gasolina 95 E5",
    "g98": "Precio Gasolina 98 E5",
}


def numero(txt, lo, hi):
    """'1,759' -> 1.759 ; vacio o fuera de rango -> None. Usa coma decimal."""
    if not txt:
        return None
    try:
        v = float(str(txt).strip().replace(",", "."))
    except ValueError:
        return None
    return v if lo < v < hi else None


def km(a, b):
    r = math.radians
    x = (math.sin(r(b[0] - a[0]) / 2) ** 2 +
         math.cos(r(a[0])) * math.cos(r(b[0])) * math.sin(r(b[1] - a[1]) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(x))


def descarga(get, esperas=ESPERAS):
    """Lista completa del Ministerio, o None si no hay manera."""
    for n, espera in enumerate(esperas, 1):
        if espera:
            time.sleep(espera)
        try:
            crudo = json.loads(get(URL_MINISTERIO))
            lista = crudo.get("ListaEESSPrecio") or []
            if len(lista) >= MIN_ESPANA:
                return crudo
            print(f"  intento {n}: lista incompleta ({len(lista)} estaciones)")
        except Exception as e:
            print(f"  intento {n}: {e}")
    return None


def lee_previa(get):
    """Ultima copia publicada, para conservar el historial de cambios."""
    try:
        previa = json.loads(get(URL_PREVIA))
        return {e["id"]: e for e in previa.get("estaciones", [])}
    except Exception as e:
        print(f"  sin copia previa ({e})")
        return {}


def normaliza(crudo, previas, hoy):
    estaciones = []
    for e in crudo.get("ListaEESSPrecio") or []:
        if (e.get("Tipo Venta") or "P").strip().upper() == "R":
            continue                      # venta restringida a socios
        lat = numero(e.get("Latitud"), 27, 44)
        lon = numero(e.get("Longitud (WGS84)"), -19, 5)
        if lat is None or lon is None or km(CENTRO, (lat, lon)) > RADIO_KM:
            continue

        precios = {}
        for clave, campo in COMBUSTIBLES.items():
            p = numero(e.get(campo), 0.3, 5.0)
            if p is not None:
                precios[clave] = p
        if not precios:
            continue

        ident = str(e.get("IDEESS") or "").strip()
        if not ident:
            continue

        cambios = dict((previas.get(ident) or {}).get("hs") or {})
        for clave, p in precios.items():
            serie = list(cambios.get(clave) or [])
            if not serie or serie[-1][1] != p:
                serie.append([hoy, p])
            cambios[clave] = serie[-CAMBIOS_GUARDADOS:]

        estaciones.append({
            "id": ident,
            "r": (e.get("Rótulo") or "").strip(),
            "d": (e.get("Dirección") or "").strip(),
            "m": (e.get("Municipio") or "").strip(),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "h": (e.get("Horario") or "").strip(),
            "pr": precios,
            "hs": cambios,
        })
    estaciones.sort(key=lambda x: x["id"])
    return estaciones


def main(get=None, esperas=ESPERAS):
    if get is None:
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; gasolineras-tudela/1.0)",
                          "Accept": "application/json"})

        def get(url):
            r = s.get(url, timeout=120)
            r.raise_for_status()
            return r.text

    print("Gasolineras…")
    crudo = descarga(get, esperas)
    if crudo is None:
        print("  Ministerio no leido: no se publica nada, sigue la copia anterior")
        return 0

    ahora = datetime.now(MADRID)
    estaciones = normaliza(crudo, lee_previa(get), ahora.date().isoformat())
    if len(estaciones) < MIN_ZONA:
        print(f"  solo {len(estaciones)} estaciones en la zona: no se publica")
        return 0

    SALIDA.write_text(json.dumps({
        "generado": ahora.isoformat(timespec="minutes"),
        "fecha_ministerio": str(crudo.get("Fecha") or ""),
        "estaciones": estaciones,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(estaciones)} estaciones escritas")
    return 0


def selftest():
    """Sin red: comprueba filtros, historial y que un fallo no escriba nada."""
    def estacion(i, lat, lon, a="1,699", venta="P", mun="Tudela"):
        return {"IDEESS": str(i), "Latitud": str(lat).replace(".", ","),
                "Longitud (WGS84)": str(lon).replace(".", ","), "Tipo Venta": venta,
                "Rótulo": "X", "Dirección": "C/ Y", "Municipio": mun,
                "Horario": "L-D: 24H", "Precio Gasoleo A": a, "Precio Gasolina 95 E5": ""}

    relleno = [estacion(100 + i, 42.05, -1.6) for i in range(MIN_ZONA)]
    crudo = {"Fecha": "03/11/2026 9:42:18", "ListaEESSPrecio": [
        estacion(1, 42.04, -1.59),
        estacion(2, 42.04, -1.59, venta="R"),          # socios: fuera
        estacion(3, 40.41, -3.70, mun="Madrid"),       # lejos: fuera
        estacion(4, 42.04, -1.59, a=""),               # sin precios: fuera
        estacion(5, 42.04, -1.59, a="99,9"),           # absurdo: fuera
    ] + relleno + [estacion(9000 + i, 40.0, -3.0) for i in range(MIN_ESPANA)]}

    previas = {"1": {"hs": {"gA": [["2026-11-01", 1.709]]}}}
    est = {e["id"]: e for e in normaliza(crudo, previas, "2026-11-03")}
    assert set(est) == {"1"} | {str(100 + i) for i in range(MIN_ZONA)}, sorted(est)
    assert est["1"]["pr"] == {"gA": 1.699}
    assert est["1"]["hs"]["gA"] == [["2026-11-01", 1.709], ["2026-11-03", 1.699]]

    repetida = normaliza(crudo, {"1": est["1"]}, "2026-11-04")
    assert repetida[0]["hs"]["gA"] == est["1"]["hs"]["gA"], "sin cambio no anade"

    def caida(url):
        raise OSError("sin conexion")

    SALIDA.unlink(missing_ok=True)
    assert main(caida, (0,)) == 0 and not SALIDA.exists(), "un fallo no debe escribir"

    def corta(url):
        return json.dumps({"ListaEESSPrecio": [estacion(1, 42.04, -1.59)]})

    assert main(corta, (0,)) == 0 and not SALIDA.exists(), "lista corta no se publica"
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
