"""
Geracao solar e previsao meteorologica.

- `perfil_ceu_limpo`: curva de geracao em dia sem nuvens (Sao Paulo, primavera).
- `gerar_dias`: cria N dias com indice de claridade variavel (sol, parcial, nublado),
  incluindo a passagem de nuvens dentro do dia (ruido correlacionado).
- `previsao_d1`: o que o sistema SABE antes do dia comecar - a previsao do tempo
  (com erro), nao a geracao real. O algoritmo inteligente decide com base nela.
- `buscar_previsao_open_meteo`: em producao, troca a previsao sintetica pela
  irradiancia prevista da API publica Open-Meteo (sem chave).
"""
import json
import math
import random
import urllib.request

from . import config as C

NASCER, POR = 5.9, 18.3  # horas aproximadas em outubro, Sao Paulo


def perfil_ceu_limpo():
    """Potencia FV (kW) em cada passo de 15 min em um dia de ceu limpo."""
    pico = C.POTENCIA_FV_KWP * C.PERFORMANCE_RATIO
    perfil = []
    for p in range(C.PASSOS_DIA):
        h = (p + 0.5) * C.DT_H
        if NASCER < h < POR:
            x = (h - NASCER) / (POR - NASCER)
            perfil.append(pico * math.sin(math.pi * x) ** 1.2)
        else:
            perfil.append(0.0)
    return perfil


def _tipo_dia(rng):
    r = rng.random()
    if r < 0.45:
        return "ensolarado", rng.uniform(0.85, 1.0), 0.05
    if r < 0.80:
        return "parcialmente nublado", rng.uniform(0.55, 0.80), 0.25
    return "nublado/chuvoso", rng.uniform(0.18, 0.40), 0.10


def gerar_dias(n_dias=30, semente=2026):
    """Retorna lista de dias: {tipo, k_medio, solar_real_kw[96], solar_prevista_kw[96]}."""
    rng = random.Random(semente)
    limpo = perfil_ceu_limpo()
    dias = []
    for d in range(n_dias):
        tipo, k, volat = _tipo_dia(rng)
        # nuvens passageiras: ruido AR(1) multiplicativo
        ruido, real = 0.0, []
        for p in range(C.PASSOS_DIA):
            ruido = 0.85 * ruido + rng.gauss(0, volat)
            fator = min(1.05, max(0.05, k + ruido))
            real.append(round(limpo[p] * fator, 3))
        # previsao D-1: acerta a "cara" do dia, mas com erro (~10 p.p. no indice)
        k_prev = min(1.0, max(0.1, k + rng.gauss(0, 0.10)))
        prevista = [round(v * k_prev, 3) for v in limpo]
        dias.append({
            "dia": d + 1,
            "tipo": tipo,
            "k_real": round(k, 2),
            "k_previsto": round(k_prev, 2),
            "solar_real_kw": real,
            "solar_prevista_kw": prevista,
        })
    return dias


def buscar_previsao_open_meteo(timeout=8):
    """Previsao de amanha (kW por passo de 15 min) a partir da irradiancia GHI
    prevista pela Open-Meteo. Retorna None se nao houver internet - o sistema
    entao cai para a previsao de persistencia (dia anterior)."""
    url = ("https://api.open-meteo.com/v1/forecast?"
           f"latitude={C.LATITUDE}&longitude={C.LONGITUDE}"
           "&hourly=shortwave_radiation&forecast_days=2&timezone=America%2FSao_Paulo")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            dados = json.load(r)
    except Exception:
        return None
    ghi = dados["hourly"]["shortwave_radiation"][24:48]  # W/m2, amanha
    # P = kWp * (GHI / 1000 W/m2) * PR  -> repetido em 4 passos de 15 min
    kw_hora = [C.POTENCIA_FV_KWP * g / 1000 * C.PERFORMANCE_RATIO for g in ghi]
    return [round(v, 3) for v in kw_hora for _ in range(4)]
