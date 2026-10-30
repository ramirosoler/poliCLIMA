
import csv
import math
import random
from datetime import date, timedelta

# ── Configuración general ───────────────────────────────────────────────
random.seed(42)      # fija la semilla para que el resultado sea reproducible
ANIO = 2026
ESTACION = "El Dorado International"
ID_GHCN = "CO000080222"

# Ruta de salida (ajusta si quieres guardarlo en otra carpeta)
RUTA_DIARIO = "datos_climaticos_bogota_diario.csv"
RUTA_HORARIO = "datos_climaticos_bogota_horario.csv"

# ── Datos reales mensuales ───────────────────────────────────────────────
# (nombre_mes, numero_mes, temp_min_media_C, temp_max_media_C, precipitacion_diaria_media_mm)
MESES = [
    ("Enero",      1, 5.70, 20.27, 1.03),
    ("Febrero",    2, 6.74, 20.41, 1.87),
    ("Marzo",      3, 7.80, 20.20, 2.60),
    ("Abril",      4, 8.78, 19.82, 3.72),
    ("Mayo",       5, 8.99, 19.51, 3.36),
    ("Junio",      6, 8.42, 18.99, 2.11),
    ("Julio",      7, 8.07, 18.54, 1.48),
    ("Agosto",     8, 7.67, 18.83, 1.55),
    ("Septiembre", 9, 7.29, 19.35, 2.44),
    ("Octubre",   10, 7.78, 19.49, 3.49),
    ("Noviembre", 11, 8.02, 19.61, 3.43),
    ("Diciembre", 12, 6.49, 19.90, 2.20),
]

# Índices de MESES para legibilidad
IDX_TMIN = 2
IDX_TMAX = 3
IDX_PRECIP = 4


def dia_del_anio_medio(mes_numero: int, anio: int) -> int:
    """Día del año (1-365/366) correspondiente al día 15 de ese mes."""
    return date(anio, mes_numero, 15).timetuple().tm_yday


def interpolar_valor(doy: int, indice_valor: int, puntos: list) -> float:
    """
    Interpola linealmente el valor mensual (temp min, temp max o precip)
    para un día del año `doy`, usando el punto medio de cada mes como
    referencia y tratando el año como un ciclo (diciembre conecta con enero).
    """
    puntos_ordenados = sorted(puntos, key=lambda p: p[0])
    n = len(puntos_ordenados)

    for i in range(n):
        x0, mes0 = puntos_ordenados[i]
        x1, mes1 = puntos_ordenados[(i + 1) % n]

        if i == n - 1:
            x1 += 365          # conecta diciembre -> enero del año siguiente
            doy_efectivo = doy if doy >= x0 else doy + 365
        else:
            doy_efectivo = doy

        if x0 <= doy_efectivo <= x1:
            t = (doy_efectivo - x0) / (x1 - x0)
            return mes0[indice_valor] + t * (mes1[indice_valor] - mes0[indice_valor])

    # Si no cayó en ningún tramo (caso borde), se usa el primer mes
    return puntos_ordenados[0][1][indice_valor]


def generar_dataset_diario(anio: int) -> list:
    """Genera 365 filas (una por día) con temperatura y precipitación estimadas."""
    puntos = [(dia_del_anio_medio(m[1], anio), m) for m in MESES]

    filas = []
    inicio = date(anio, 1, 1)

    for i in range(365):
        fecha = inicio + timedelta(days=i)
        doy = fecha.timetuple().tm_yday
        mes_info = MESES[fecha.month - 1]

        tmin_base = interpolar_valor(doy, IDX_TMIN, puntos)
        tmax_base = interpolar_valor(doy, IDX_TMAX, puntos)
        precip_base = interpolar_valor(doy, IDX_PRECIP, puntos)

        # Pequeña variación aleatoria día a día alrededor del promedio mensual
        tmin = round(tmin_base + random.uniform(-1.2, 1.2), 2)
        tmax = round(tmax_base + random.uniform(-1.5, 1.5), 2)
        tmedia = round((tmin + tmax) / 2, 2)
        precip = round(max(0.0, precip_base + random.uniform(-0.8, 1.5)), 2)

        filas.append({
            "Fecha": fecha.isoformat(),
            "Anio": anio,
            "Mes": mes_info[0],
            "Mes_Numero": fecha.month,
            "Dia": fecha.day,
            "Temp_Min_C": tmin,
            "Temp_Max_C": tmax,
            "Temp_Media_C": tmedia,
            "Precipitacion_mm": precip,
            "Estacion": ESTACION,
            "ID_GHCN": ID_GHCN,
        })

    return filas


def generar_dataset_horario(filas_diarias: list) -> list:
    """
    A partir de la temperatura mínima y máxima de cada día, genera 24
    valores horarios siguiendo un ciclo diurno típico:
    mínimo cerca de las 5 a.m., máximo cerca de las 2 p.m.
    """
    filas = []

    for fila in filas_diarias:
        tmin = fila["Temp_Min_C"]
        tmax = fila["Temp_Max_C"]

        for hora in range(24):
            # factor va de 0 (mínimo, ~5am) a 1 (máximo, ~14h) y vuelve a bajar
            factor = (1 - math.cos((hora - 5) / 24 * 2 * math.pi)) / 2
            temp_hora = round(
                tmin + factor * (tmax - tmin) + random.uniform(-0.3, 0.3), 2
            )

            filas.append({
                "Fecha": fila["Fecha"],
                "Anio": fila["Anio"],
                "Mes": fila["Mes"],
                "Mes_Numero": fila["Mes_Numero"],
                "Dia": fila["Dia"],
                "Hora": hora,
                "Temp_C": temp_hora,
                "Estacion": ESTACION,
                "ID_GHCN": ID_GHCN,
            })

    return filas


def guardar_csv(filas: list, ruta: str) -> None:
    if not filas:
        return
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        writer.writeheader()
        writer.writerows(filas)


def main():
    filas_diarias = generar_dataset_diario(ANIO)
    guardar_csv(filas_diarias, RUTA_DIARIO)
    print(f"Generado {RUTA_DIARIO}: {len(filas_diarias)} filas")

    filas_horarias = generar_dataset_horario(filas_diarias)
    guardar_csv(filas_horarias, RUTA_HORARIO)
    print(f"Generado {RUTA_HORARIO}: {len(filas_horarias)} filas")


if __name__ == "__main__":
    main()
