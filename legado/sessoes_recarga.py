"""
Sprint 3 - Eletroposto Inteligente (EV Challenge 2026)
Simulacao de MULTIPLAS SESSOES DE RECARGA em um dia, usando a mesma logica
de gestao de energia da Sprint 2 (prioridade SOLAR -> BATERIA -> REDE).

Evolucao em relacao a Sprint 2:
- Sprint 2: uma unica logica continua de decisao de fonte (prova de conceito).
- Sprint 3: multiplos eventos discretos de "sessao de recarga" (carro chega,
  carrega, sai), com registro individual de cada sessao -> integra a
  logica de energia com o conceito de "gestao de sessoes" pedido na Sprint 3.
"""

import json
import math

# ---------------------------------------------------------------------------
# Parametros do sistema (mesmos principios da Sprint 1 e 2)
# ---------------------------------------------------------------------------
CAPACIDADE_BATERIA_KWH = 12.0
SOC_INICIAL_PCT = 0.4
SOC_MINIMO_RESERVA_PCT = 0.2
POTENCIA_INSTALADA_KWP = 10.0

TARIFA_PONTA_RS = 1.20
TARIFA_FORA_PONTA_RS = 0.60
HORA_PONTA_INICIO = 18
HORA_PONTA_FIM = 21

FATOR_EMISSAO_KG_CO2_POR_KWH = 0.12  # fator ilustrativo (grid BR), parametrizavel

# Sessoes de recarga simuladas ao longo do dia (evento = chegada de 1 veiculo)
# Demandas escolhidas para evidenciar as 3 fontes (solar / bateria / rede) ao
# longo do dia, mostrando a integracao completa da logica de decisao.
SESSOES = [
    {"id": 1, "veiculo": "EV-A", "hora_inicio": 8,  "duracao_h": 1, "demanda_kwh": 8},
    {"id": 2, "veiculo": "EV-B", "hora_inicio": 12, "duracao_h": 1, "demanda_kwh": 10},
    {"id": 3, "veiculo": "EV-C", "hora_inicio": 15, "duracao_h": 1, "demanda_kwh": 14},
    {"id": 4, "veiculo": "EV-D", "hora_inicio": 19, "duracao_h": 1, "demanda_kwh": 16},
]


def geracao_solar(hora):
    """Curva solar simplificada (gaussiana centrada ao meio-dia)."""
    pico, desvio = 12, 3.5
    fator = math.exp(-((hora - pico) ** 2) / (2 * desvio ** 2))
    return round(POTENCIA_INSTALADA_KWP * fator, 2)


def tarifa(hora):
    return TARIFA_PONTA_RS if HORA_PONTA_INICIO <= hora < HORA_PONTA_FIM else TARIFA_FORA_PONTA_RS


def simular_dia():
    soc_kwh = CAPACIDADE_BATERIA_KWH * SOC_INICIAL_PCT
    log_horario = []
    sessoes_por_id = {}

    for hora in range(24):
        geracao = geracao_solar(hora)
        sessao_ativa = next(
            (s for s in SESSOES if s["hora_inicio"] <= hora < s["hora_inicio"] + s["duracao_h"]),
            None,
        )
        demanda = (sessao_ativa["demanda_kwh"] / sessao_ativa["duracao_h"]) if sessao_ativa else 0

        usa_solar = usa_bateria = usa_rede = 0.0

        if demanda == 0:
            excedente = geracao
            carga_possivel = min(excedente, CAPACIDADE_BATERIA_KWH - soc_kwh)
            soc_kwh += carga_possivel
        else:
            if geracao >= demanda:
                usa_solar = demanda
                excedente = geracao - demanda
                soc_kwh = min(CAPACIDADE_BATERIA_KWH, soc_kwh + excedente)
            else:
                usa_solar = geracao
                deficit = demanda - geracao
                reserva = CAPACIDADE_BATERIA_KWH * SOC_MINIMO_RESERVA_PCT
                disponivel_bateria = max(0.0, soc_kwh - reserva)
                usa_bateria = min(deficit, disponivel_bateria)
                soc_kwh -= usa_bateria
                deficit -= usa_bateria
                if deficit > 0:
                    usa_rede = deficit

        custo_hora = usa_rede * tarifa(hora)
        co2_evitado_hora = (usa_solar + usa_bateria) * FATOR_EMISSAO_KG_CO2_POR_KWH

        log_horario.append({
            "hora": hora,
            "geracao_solar_kwh": geracao,
            "demanda_kwh": round(demanda, 2),
            "soc_bateria_kwh": round(soc_kwh, 2),
            "usa_solar_kwh": round(usa_solar, 2),
            "usa_bateria_kwh": round(usa_bateria, 2),
            "usa_rede_kwh": round(usa_rede, 2),
            "custo_rs": round(custo_hora, 2),
            "co2_evitado_kg": round(co2_evitado_hora, 3),
            "sessao_ativa": sessao_ativa["id"] if sessao_ativa else None,
        })

        if sessao_ativa:
            sid = sessao_ativa["id"]
            reg = sessoes_por_id.setdefault(sid, {
                "id": sid, "veiculo": sessao_ativa["veiculo"],
                "hora_inicio": sessao_ativa["hora_inicio"],
                "hora_fim": sessao_ativa["hora_inicio"] + sessao_ativa["duracao_h"],
                "demanda_kwh": sessao_ativa["demanda_kwh"],
                "solar_kwh": 0.0, "bateria_kwh": 0.0, "rede_kwh": 0.0,
                "custo_rs": 0.0, "co2_evitado_kg": 0.0,
            })
            reg["solar_kwh"] += usa_solar
            reg["bateria_kwh"] += usa_bateria
            reg["rede_kwh"] += usa_rede
            reg["custo_rs"] += custo_hora
            reg["co2_evitado_kg"] += co2_evitado_hora

    log_sessoes = []
    for s in sessoes_por_id.values():
        for k in ("solar_kwh", "bateria_kwh", "rede_kwh", "custo_rs", "co2_evitado_kg"):
            s[k] = round(s[k], 3)
        total = round(s["solar_kwh"] + s["bateria_kwh"] + s["rede_kwh"], 3)
        s["total_kwh"] = total
        s["pct_renovavel"] = round(100 * (s["solar_kwh"] + s["bateria_kwh"]) / total, 1) if total else 0
        s["custo_sem_sistema_rs"] = round(total * tarifa(s["hora_inicio"]), 2)
        s["economia_rs"] = round(s["custo_sem_sistema_rs"] - s["custo_rs"], 2)
        log_sessoes.append(s)
    log_sessoes.sort(key=lambda x: x["id"])

    return log_horario, log_sessoes


if __name__ == "__main__":
    horario, sessoes = simular_dia()

    with open("log_horario_sprint3.json", "w", encoding="utf-8") as f:
        json.dump(horario, f, ensure_ascii=False, indent=2)
    with open("log_sessoes_sprint3.json", "w", encoding="utf-8") as f:
        json.dump(sessoes, f, ensure_ascii=False, indent=2)

    total_kwh = sum(s["total_kwh"] for s in sessoes)
    total_renov_kwh = sum(s["solar_kwh"] + s["bateria_kwh"] for s in sessoes)
    total_custo = sum(s["custo_rs"] for s in sessoes)
    total_custo_sem = sum(s["custo_sem_sistema_rs"] for s in sessoes)
    total_economia = sum(s["economia_rs"] for s in sessoes)
    total_co2 = sum(s["co2_evitado_kg"] for s in sessoes)

    print("=== RESUMO DO DIA - SPRINT 3 (4 sessoes de recarga) ===")
    for s in sessoes:
        print(f"Sessao {s['id']} ({s['veiculo']}, {s['hora_inicio']}h-{s['hora_fim']}h): "
              f"{s['total_kwh']} kWh | solar={s['solar_kwh']} bateria={s['bateria_kwh']} rede={s['rede_kwh']} "
              f"| {s['pct_renovavel']}% renovavel | custo R$ {s['custo_rs']} | economia R$ {s['economia_rs']}")
    print("-" * 60)
    print(f"Total entregue no dia: {round(total_kwh,2)} kWh")
    print(f"Total renovavel: {round(total_renov_kwh,2)} kWh ({round(100*total_renov_kwh/total_kwh,1)}%)")
    print(f"Custo total: R$ {round(total_custo,2)} (seria R$ {round(total_custo_sem,2)} sem o sistema)")
    print(f"Economia total: R$ {round(total_economia,2)}")
    print(f"CO2 evitado no dia: {round(total_co2,2)} kg")
