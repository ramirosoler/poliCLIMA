"""
app.py — Servidor web de PoliClima (Flask).
Recibe archivos, los procesa con limpieza.py y entrega los resultados en JSON a la interfaz.

Nota: en Python los comentarios se escriben con # (el // de JavaScript aquí significa otra cosa).
"""
from io import BytesIO
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request

from limpieza import VARIABLES, cargar, calcular_informe, tabla_variables

# ── 1. CONFIGURACIÓN ────────────────────────────────────────────────────────
RUTA_EJEMPLO = Path(__file__).parent.parent / "data" / "estacion.csv"  # se carga al iniciar si existe
app = Flask(__name__, template_folder="../frontend/templates", static_folder="../frontend/static")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # máximo 50 MB por archivo

# Datos actualmente cargados (se reemplazan cada vez que el usuario sube un archivo)
estado = {"df": None, "informe": None, "archivo": None}

if RUTA_EJEMPLO.exists():
    estado["df"], estado["informe"] = cargar(RUTA_EJEMPLO, RUTA_EJEMPLO.name)
    estado["archivo"] = RUTA_EJEMPLO.name

# Umbrales de las alertas: (desde qué valor, etiqueta, nivel 0-3, consejo). Se evalúan de mayor a menor.
# Nivel: 0 verde, 1 amarillo, 2 naranja, 3 rojo.
# UV: escala de la OMS. Lluvia y temperatura: valores de referencia que el equipo debe justificar y ajustar aquí.
UMBRALES_UV = [
    (11, "Extremo", 3, "Evita el sol del mediodía; usa protector, gorra y gafas."),
    (8, "Muy alto", 2, "Usa protector solar y gafas; busca sombra al mediodía."),
    (6, "Alto", 2, "Se recomienda protector solar."),
    (3, "Moderado", 1, "Protector solar si estarás mucho tiempo afuera."),
    (0, "Bajo", 0, "Sin riesgo especial."),
]
UMBRALES_LLUVIA = [  # milímetros acumulados en el día
    (30, "Muy fuerte", 3, "Evita zonas inundables y lleva impermeable."),
    (10, "Fuerte", 2, "Lleva paraguas e impermeable."),
    (1, "Ligera", 1, "Un paraguas puede servir."),
    (0, "Sin lluvia", 0, "Día seco."),
]
TEMP_CALOR = 21  # °C: máxima a partir de la cual se avisa calor (para Bogotá)
TEMP_FRIO = 9    # °C: mínima a partir de la cual se avisa frío


# ── 2. FUNCIONES DE AYUDA ───────────────────────────────────────────────────
def num(x, decimales=1):
    """Número listo para JSON: los vacíos (NaN) se convierten en None."""
    return None if pd.isna(x) else round(float(x), decimales)


def filtrar(df):
    """Recorta la tabla según los filtros de la URL: fechas (desde, hasta) y horas (hora_desde, hora_hasta)."""
    desde = pd.to_datetime(request.args.get("desde"), errors="coerce")
    hasta = pd.to_datetime(request.args.get("hasta"), errors="coerce")
    if pd.notna(desde):
        df = df[df.index >= desde]
    if pd.notna(hasta):
        df = df[df.index < hasta + pd.Timedelta(days=1)]  # «hasta» incluye todo ese día
    h1 = request.args.get("hora_desde", type=int)
    h2 = request.args.get("hora_hasta", type=int)
    if h1 is not None and h2 is not None and (h1, h2) != (0, 23):
        # Si la hora inicial es mayor (ej. 20 a 6) toma la noche, cruzando la medianoche
        df = df.between_time(f"{max(0, min(h1, 23)):02d}:00", f"{max(0, min(h2, 23)):02d}:59")
    return df


def nivel_por_umbral(valor, umbrales):
    """Busca el primer umbral (de mayor a menor) que el valor alcanza."""
    for desde, etiqueta, nivel, consejo in umbrales:
        if valor >= desde:
            return etiqueta, nivel, consejo


def calcular_alertas(df):
    """Alertas de UV, lluvia y temperatura con los datos del último día del rango elegido."""
    dia = df[df.index.normalize() == df.index[-1].normalize()]
    fecha = dia.index[0].strftime("%d/%m/%Y")
    alertas = []
    if "uv" in dia and dia["uv"].notna().any():
        valor = dia["uv"].max()
        etiqueta, nivel, consejo = nivel_por_umbral(valor, UMBRALES_UV)
        alertas.append({"tipo": "uv", "titulo": "Radiación UV", "etiqueta": etiqueta, "nivel": nivel,
                        "dato": f"Índice máximo {num(valor)}", "consejo": consejo, "fecha": fecha})
    if "precipitacion" in dia and dia["precipitacion"].notna().any():
        valor = dia["precipitacion"].sum()
        etiqueta, nivel, consejo = nivel_por_umbral(valor, UMBRALES_LLUVIA)
        alertas.append({"tipo": "lluvia", "titulo": "Lluvia", "etiqueta": etiqueta, "nivel": nivel,
                        "dato": f"{num(valor)} mm acumulados", "consejo": consejo, "fecha": fecha})
    if "temperatura" in dia and dia["temperatura"].notna().any():
        tmin, tmax = dia["temperatura"].min(), dia["temperatura"].max()
        if tmax >= TEMP_CALOR:
            etiqueta, nivel, consejo = "Calor", 2, "Ropa ligera, hidrátate y evita el sol fuerte."
        elif tmin <= TEMP_FRIO:
            etiqueta, nivel, consejo = "Frío", 1, "Lleva abrigo, sobre todo en la mañana."
        else:
            etiqueta, nivel, consejo = "Templado", 0, "Temperatura típica del campus."
        alertas.append({"tipo": "temperatura", "titulo": "Temperatura", "etiqueta": etiqueta, "nivel": nivel,
                        "dato": f"Entre {num(tmin)} y {num(tmax)} °C", "consejo": consejo, "fecha": fecha})
    return alertas


# ── 3. PÁGINA PRINCIPAL ─────────────────────────────────────────────────────
@app.get("/")
def inicio():
    return render_template("index.html")


# ── 4. SUBIDA DE ARCHIVOS ───────────────────────────────────────────────────
@app.post("/api/subir")
def subir():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return jsonify(error="No se recibió ningún archivo."), 400
    try:
        df, informe = cargar(BytesIO(archivo.read()), archivo.filename)
    except ValueError as e:  # errores esperados, con mensaje claro para el usuario
        return jsonify(error=str(e)), 400
    estado.update(df=df, informe=informe, archivo=archivo.filename)
    return jsonify(ok=True)


# ── 5. RESUMEN: tarjetas, alertas, calidad y tabla (respeta los filtros) ────
@app.get("/api/resumen")
def resumen():
    completo = estado["df"]
    if completo is None:
        return jsonify(vacio=True)

    base = {
        "archivo": estado["archivo"],
        "rango": {"desde": str(completo.index.min().date()), "hasta": str(completo.index.max().date())},
        "variables": [{"id": v, "nombre": VARIABLES[v]["nombre"], "unidad": VARIABLES[v]["unidad"]}
                      for v in VARIABLES if v in completo.columns],
    }
    df = filtrar(completo)
    if df.empty:
        return jsonify(**base, sin_datos=True, mensaje="No hay datos con esos filtros. Prueba con otro rango de fechas u horas.")

    informe = calcular_informe(df)
    tabla = tabla_variables(df)
    fila = {f["id"]: f for f in tabla}
    return jsonify(
        **base,
        filtrado={"desde": str(df.index.min().date()), "hasta": str(df.index.max().date()), "registros": len(df)},
        tarjetas={
            "temperatura": fila.get("temperatura", {}).get("media"),
            "precipitacion": fila.get("precipitacion", {}).get("total"),
            "humedad": fila.get("humedad", {}).get("media"),
            "calidad": informe["completitud_final"],
        },
        informe=informe,
        tabla=tabla,
        alertas=calcular_alertas(df),
    )


# ── 6. SERIE para la gráfica: por día o por hora del día ────────────────────
@app.get("/api/serie")
def serie():
    completo = estado["df"]
    v = request.args.get("variable", "temperatura")
    if completo is None or v not in completo:
        return jsonify(error="Variable no disponible."), 400
    df = filtrar(completo)
    if df.empty:
        return jsonify(error="No hay datos con esos filtros."), 400

    cfg = VARIABLES[v]
    estimado = df[v + "_interp"]
    if request.args.get("vista") == "hora":
        # Ciclo del día: promedio de cada hora (0 a 23) en todos los días del rango
        grupo = df[v].groupby(df.index.hour)
        if cfg["agregado"] == "suma":  # lluvia: lo que llueve en promedio durante esa hora
            valores = grupo.sum(min_count=1) / df.index.normalize().nunique()
        else:
            valores = grupo.mean()
        valores = valores.reindex(range(24))
        marcas = estimado.groupby(df.index.hour).any().reindex(range(24), fill_value=False)
        etiquetas = [f"{h:02d}:00" for h in range(24)]
        titulo = f"{cfg['nombre']}: promedio por hora del día ({cfg['unidad']})"
    else:
        dia = df[v].resample("D")
        valores = {"suma": lambda: dia.sum(min_count=1), "max": dia.max, "media": dia.mean}[cfg["agregado"]]()
        # Días que tienen al menos un dato estimado (se agrupa por día y se alinea con los valores)
        marcas = estimado.groupby(df.index.normalize()).any().reindex(valores.index, fill_value=False)
        etiquetas = [d.strftime("%d/%m") for d in valores.index]
        titulo = f"{cfg['nombre']}: {cfg['etiqueta']} ({cfg['unidad']})"

    return jsonify(
        etiquetas=etiquetas, valores=[num(x) for x in valores],
        interpolados=[bool(x) for x in marcas], titulo=titulo, unidad=cfg["unidad"], tipo="bar" if cfg["agregado"] == "suma" else "line",
    )


if __name__ == "__main__":
    app.run(debug=True)
