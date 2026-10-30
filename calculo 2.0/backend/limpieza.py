"""
limpieza.py — Lee el archivo de la estación, detecta datos faltantes e interpola los que se puede.
Devuelve una tabla limpia (df) y un informe con los conteos (informe).

Nota: en Python los comentarios se escriben con # (el // de JavaScript aquí significa otra cosa).
"""
from io import StringIO
from pathlib import Path

import pandas as pd

# ── 1. CONFIGURACIÓN ────────────────────────────────────────────────────────
# Cada variable dice: cómo se llama, con qué palabras se reconoce su columna,
# qué palabras la descartan, y cuántos minutos de hueco se pueden estimar (None = nunca).
VARIABLES = {
    "temperatura":   dict(nombre="Temperatura",        unidad="°C",    claves=["temp"],                 excluir=["dew", "roc", "chill", "heat", "indice", "índice"], max_min=60,   agregado="media", etiqueta="media diaria"),
    "humedad":       dict(nombre="Humedad relativa",   unidad="%",     claves=["hum"],                  excluir=[],                                                  max_min=60,   agregado="media", etiqueta="media diaria"),
    # La lluvia NO se interpola a propósito: estimarla inventaría lluvia que no se midió.
    "precipitacion": dict(nombre="Precipitación",      unidad="mm",    claves=["precip", "lluvia", "rain"], excluir=["rate", "tasa", "intens", "day", "diar", "mes", "month", "year"], max_min=None, agregado="suma",  etiqueta="acumulada diaria"),
    "presion":       dict(nombre="Presión barométrica", unidad="mm Hg", claves=["barom", "baróm", "pres"],        excluir=[],                                                  max_min=60,   agregado="media", etiqueta="media diaria"),
    "viento":        dict(nombre="Viento (media)",     unidad="m/s",   claves=["wind", "viento"],       excluir=["dir", "chill", "gust", "racha", "sens", "run", "high", "max"], max_min=60, agregado="media", etiqueta="media diaria"),
    "radiacion":     dict(nombre="Radiación solar",    unidad="W/m²",  claves=["solar", "radia"],       excluir=["energy", "energ", "high", "max"],                  max_min=30,   agregado="media", etiqueta="media diaria"),
    "uv":            dict(nombre="Índice UV",          unidad="índice", claves=["uv"],                  excluir=["dose", "dosis", "high", "max"],                    max_min=30,   agregado="max",   etiqueta="máximo diario"),
}
CLAVES_FECHA = ["fecha", "date", "time", "hora"]
VALORES_VACIOS = ["--", "---", "-", " "]  # así marca la consola los datos que no pudo medir


# ── 2. LECTURA DE CUALQUIER ARCHIVO ─────────────────────────────────────────
def _fila_encabezado(filas):
    """Busca la fila con los nombres de las columnas, saltando las líneas de título del inicio."""
    for i, f in enumerate(filas[:50]):
        if any(k in f.lower() for k in CLAVES_FECHA) and sum(f.count(c) for c in ",;\t") >= 2:
            return i
    return 0


def _leer(origen, nombre):
    """Lee CSV/TXT (cualquier separador), Excel o JSON según la extensión del archivo."""
    nombre = str(nombre).lower()

    if nombre.endswith((".xlsx", ".xlsm", ".xls")):
        crudo = pd.read_excel(origen, header=None)             # se lee sin encabezado...
        filas = [",".join(map(str, f)) for f in crudo.values]
        i = _fila_encabezado(filas)                             # ...y se busca dónde empiezan los datos
        tabla = crudo.iloc[i + 1:].reset_index(drop=True)
        tabla.columns = crudo.iloc[i].astype(str)
        return tabla

    if nombre.endswith(".json"):
        return pd.read_json(origen)

    # CSV o TXT: se lee como texto para poder saltar las líneas de título
    datos = origen.read() if hasattr(origen, "read") else Path(origen).read_bytes()
    try:
        texto = datos.decode("utf-8-sig")                       # utf-8 (con o sin marca BOM)
    except UnicodeDecodeError:
        texto = datos.decode("latin-1")                         # plan B para archivos antiguos
    filas = texto.splitlines()
    i = _fila_encabezado(filas)
    sep = max(",;\t", key=lambda c: filas[i].count(c))          # el separador más repetido en el encabezado
    return pd.read_csv(StringIO("\n".join(filas[i:])), sep=sep, na_values=VALORES_VACIOS)


def _buscar(columnas, claves, excluir, usadas):
    """Devuelve la posición de la primera columna que contiene alguna palabra clave (y ninguna excluida)."""
    for pos, c in enumerate(columnas):
        nombre = str(c).lower()
        if pos in usadas or any(x in nombre for x in excluir):
            continue
        if any(k in nombre for k in claves):
            return pos


def _fechas(serie):
    """Convierte el texto de fecha (ej. 15/7/26 12:00 AM) en fechas reales."""
    s = serie.astype(str).str.strip()
    # Algunos equipos escriben «a. m.» / «p. m.»; se unifica a AM / PM
    s = s.str.replace(r"(?i)\s*a\.?\s*m\.?", " AM", regex=True).str.replace(r"(?i)\s*p\.?\s*m\.?", " PM", regex=True)
    formatos = ["%d/%m/%y %I:%M %p", "%d/%m/%Y %I:%M %p", "%d/%m/%y %H:%M", "%d/%m/%Y %H:%M",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
    for formato in formatos:
        f = pd.to_datetime(s, format=formato, errors="coerce")
        if f.notna().mean() > 0.9:                              # este formato sirve si entiende casi todas las filas
            return f
    return pd.to_datetime(s, errors="coerce", dayfirst=True)    # último recurso


def _numero(serie):
    """Convierte a número; lo que no se pueda (como «--») queda como dato faltante."""
    if not pd.api.types.is_numeric_dtype(serie):
        serie = serie.astype(str).str.replace(",", ".", regex=False)  # 11,8 → 11.8
    return pd.to_numeric(serie, errors="coerce")


# ── 3. INTERPOLACIÓN ────────────────────────────────────────────────────────
def _interpolar(serie, max_pasos):
    """Rellena huecos cortos con una línea entre el dato anterior y el siguiente.
    Los huecos largos se dejan vacíos para no inventar información."""
    largo_hueco = serie.isna().groupby(serie.notna().cumsum()).transform("sum")  # cuánto dura cada hueco
    rellena = serie.interpolate(method="time", limit_area="inside")               # línea recta entre vecinos
    return serie.where(serie.notna() | (largo_hueco > max_pasos), rellena)        # solo se usa si el hueco es corto


# ── 4. INFORME Y TABLA POR VARIABLE ─────────────────────────────────────────
def calcular_informe(df):
    """Cuenta cuántos datos faltaban, cuántos se estimaron y cuántos quedaron vacíos.
    Sirve para toda la tabla o para un rango filtrado."""
    variables = [v for v in VARIABLES if v in df.columns]
    informe = {"registros": len(df), "variables": {}}
    for v in variables:
        interpolados = int(df[v + "_interp"].sum())
        vacios = int(df[v].isna().sum())
        informe["variables"][v] = {"faltantes": interpolados + vacios, "interpolados": interpolados, "sin_resolver": vacios}

    total = len(df) * len(variables)
    faltan = sum(x["faltantes"] for x in informe["variables"].values())
    quedan = sum(x["sin_resolver"] for x in informe["variables"].values())
    informe.update(
        faltantes=faltan, interpolados=faltan - quedan, sin_resolver=quedan,
        completitud_original=round(100 * (1 - faltan / total), 1) if total else 0,
        completitud_final=round(100 * (1 - quedan / total), 1) if total else 0,
    )
    return informe


def _texto_tratamiento(max_min):
    if max_min is None:
        return "No se interpola"
    return f"Interpolación (huecos ≤ {max_min // 60} h)" if max_min % 60 == 0 else f"Interpolación (huecos ≤ {max_min} min)"


def tabla_variables(df):
    """Una fila por variable: rango, media (con datos originales, sin interpolar) y faltantes."""
    filas = []
    for v, cfg in VARIABLES.items():
        if v not in df.columns:
            continue
        originales = df[v].where(~df[v + "_interp"])             # solo los datos medidos, no los estimados
        faltantes = int(df[v + "_interp"].sum() + df[v].isna().sum())
        filas.append({
            "id": v, "nombre": cfg["nombre"], "unidad": cfg["unidad"],
            "minimo": _redondear(originales.min()), "maximo": _redondear(originales.max()), "media": _redondear(originales.mean()),
            "total": _redondear(originales.sum()) if cfg["agregado"] == "suma" else None,
            "faltantes": faltantes, "porcentaje": round(100 * faltantes / len(df), 1) if len(df) else 0,
            "tratamiento": _texto_tratamiento(cfg["max_min"]),
        })
    return filas


def _redondear(x, decimales=2):
    return None if pd.isna(x) else round(float(x), decimales)


# ── 5. FUNCIÓN PRINCIPAL ────────────────────────────────────────────────────
def cargar(origen, nombre):
    """origen: ruta o archivo en memoria. nombre: nombre del archivo (para saber su formato)."""
    try:
        crudo = _leer(origen, nombre)
    except Exception:
        raise ValueError("No pude leer el archivo. Usa CSV, Excel (.xlsx) o JSON.")

    # 5.1 Reconocer columnas por su nombre, aunque esté escrito distinto
    usadas, posiciones = set(), {}
    pos = _buscar(crudo.columns, CLAVES_FECHA, [], usadas)
    if pos is None:
        raise ValueError("No encontré una columna de fecha (por ejemplo «fecha» o «Date & Time»).")
    posiciones["fecha"] = pos
    usadas.add(pos)
    for v, cfg in VARIABLES.items():
        pos = _buscar(crudo.columns, cfg["claves"], cfg["excluir"], usadas)
        if pos is not None:
            posiciones[v] = pos
            usadas.add(pos)                                      # una columna no puede ser dos variables
    variables = [v for v in VARIABLES if v in posiciones]
    if not variables:
        raise ValueError("No encontré columnas de temperatura, humedad, lluvia u otras variables conocidas.")

    # 5.2 Quedarse solo con esas columnas, con nombres estándar
    df = pd.DataFrame({k: crudo.iloc[:, p] for k, p in posiciones.items()})

    # 5.3 Fechas reales, sin repetidas y en orden
    df["fecha"] = _fechas(df["fecha"])
    df = df.dropna(subset=["fecha"]).drop_duplicates("fecha").set_index("fecha").sort_index()
    if len(df) < 2:
        raise ValueError("El archivo tiene muy pocas filas con fecha válida.")

    # 5.4 Convertir las variables a número
    for v in variables:
        df[v] = _numero(df[v])

    # 5.5 Cuadrícula completa: un registro cada «paso» minutos (normalmente 15). Los que no llegaron quedan vacíos
    paso_min = int(round(df.index.to_series().diff().median().total_seconds() / 60)) or 15
    df = df[variables].resample(f"{paso_min}min").mean()

    # 5.6 Interpolar variable por variable y marcar lo que se estimó
    for v in variables:
        faltaba = df[v].isna()                                   # ¿qué datos faltaban originalmente?
        max_min = VARIABLES[v]["max_min"]
        if max_min:
            df[v] = _interpolar(df[v], max(1, max_min // paso_min))
        df[v + "_interp"] = faltaba & df[v].notna()              # True = dato estimado (sale naranja en la gráfica)

    informe = calcular_informe(df)
    informe["paso_min"] = paso_min
    return df, informe
