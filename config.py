"""
Referencias que cambian muy despacio.

El P/E medio de 5 anos y la mediana de 10 anos del EV/EBITDA son promedios
historicos largos: se mueven poquisimo de un mes para otro. No merece la
pena raspar dos webs cada noche por ellos, asi que viven aqui.

Revisalos a mano cada pocos meses (fuentes en el comentario de cada bloque)
y haz commit. Si no los tocas nunca, tampoco pasa nada grave.
"""

TICKERS = ["NVDA", "META", "AMZN", "MSFT", "GOOGL", "AAPL", "TSLA"]

NOMBRES = {
    "NVDA": "Nvidia", "META": "Meta", "AMZN": "Amazon", "MSFT": "Microsoft",
    "GOOGL": "Alphabet", "AAPL": "Apple", "TSLA": "Tesla",
}

# fullratio.com/stocks/nasdaq-<ticker>/pe-ratio  ->  "5 year average PE ratio"
PE_MEDIA_5A = {
    "NVDA": 61.79, "META": 23.20, "AMZN": 62.97, "MSFT": 31.26,
    "GOOGL": 22.61, "AAPL": 30.11, "TSLA": 146.62,
}

# gurufocus.com/term/ev2ebitda/<TICKER>  ->  mediana de 10 anos
EV_EBITDA_MEDIANA_10A = {
    "NVDA": 42.73, "META": 17.72, "AMZN": 27.23, "MSFT": 19.56,
    "GOOGL": 17.37, "AAPL": 20.82, "TSLA": 74.36,
}

# EV/EBITDA actual: stockanalysis lo publica en /statistics/, pero si algun
# dia deja de hacerlo se usa este valor de reserva.
EV_EBITDA_RESERVA = {
    "NVDA": 25.96, "META": 13.27, "AMZN": 11.45, "MSFT": 17.25,
    "GOOGL": 12.40, "AAPL": 27.37, "TSLA": 111.33,
}

# Umbrales del rainbow chart de Bitcoin, de mas barata a mas cara.
# Fuente: busca "bitcoin rainbow chart" y actualiza cada varios meses.
BANDAS_BTC = [
    ("Fire Sale", 59136),
    ('"BUY!"', 79604),
    ('"Accumulate"', 102629),
    ('"Still cheap"', 132355),
    ('"HODL!"', 173036),
    ('"Is this a bubble?"', 220071),
    ('"FOMO intensifies"', 281541),
    ('"Sell. Seriously, SELL!"', 365907),
    ('"Maximum Bubble"', 491369),
]
