"""Crea data/estacion.csv de ejemplo con datos faltantes (cortos y largos)."""
import numpy as np
import pandas as pd

rng = np.random.default_rng(1)
t = pd.date_range("2026-07-15", "2026-09-21 23:45", freq="15min")
hora = t.hour + t.minute / 60
temp = 14 + 4 * np.sin((hora - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.3, len(t))
hum = np.clip(78 - 2.5 * (temp - 14) + rng.normal(0, 2, len(t)), 30, 100)
lluvia = np.where(rng.random(len(t)) < 0.03, rng.exponential(0.8, len(t)), 0).round(1)

df = pd.DataFrame({"fecha": t, "temperatura": temp.round(1), "humedad": hum.round(0), "precipitacion": lluvia})
df = df.drop(df.sample(50, random_state=2).index)        # registros que nunca llegaron
df = df.drop(df.index[3000:3012])                          # hueco largo (3 horas)
df.loc[df.sample(40, random_state=3).index, "temperatura"] = np.nan  # valores vacíos
df.to_csv("data/estacion.csv", index=False)
print("Listo:", len(df), "filas")
