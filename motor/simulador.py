"""
Simula 30 dias de operacao do eletroposto com cada estrategia e gera:
  dados/resultados.json      -> alimenta o dashboard e o assistente virtual
  dados/resumo_diario.csv    -> uma linha por dia x estrategia
  dados/sessoes.csv          -> uma linha por sessao (estrategia inteligente)
  docs/img/*.png             -> graficos usados no README e no video

Uso:  python -m motor.simulador
"""
import csv
import json
import os
import sys

from . import config as C
from .clima import gerar_dias
from .demanda import gerar_todas
from .estrategias import (Bateria, Inteligente, RegraSprint3, SemSistema,
                          otimo_teorico, simular_dia)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N_DIAS = 30


def resumir_dia(passos, sessoes):
    soma = lambda k: sum(x[k] for x in passos)
    ev = soma("ev_kw") * C.DT_H
    rede = soma("rede_kw") * C.DT_H
    limpa = sum(x["ev_kw"] * x["limpa_frac"] for x in passos) * C.DT_H
    rede_ponta = sum(x["rede_kw"] for x in passos if C.eh_ponta(x["hora"])) * C.DT_H
    return {
        "energia_ev_kwh": round(ev, 2),
        "renovavel_ev_kwh": round(limpa, 2),
        "pct_renovavel": round(100 * limpa / ev, 1) if ev else 0,
        "rede_kwh": round(rede, 2),
        "rede_ponta_kwh": round(rede_ponta, 2),
        "export_kwh": round(soma("export_kw") * C.DT_H, 2),
        "pico_rede_kw": round(max(x["rede_kw"] for x in passos), 2),
        "custo_rs": round(soma("custo_rs"), 2),
        "co2_medio_kg": round(soma("co2_medio_kg"), 3),
        "co2_marginal_kg": round(soma("co2_marginal_kg"), 2),
        "nao_atendida_kwh": round(sum(s["nao_atendida_kwh"] for s in sessoes), 3),
        "sessoes": len(sessoes),
    }


def rodar():
    dias = gerar_dias(N_DIAS)
    sessoes_dias = gerar_todas(N_DIAS)
    estrategias = [SemSistema(), RegraSprint3(), Inteligente()]
    out = {e.chave: {"nome": e.nome, "dias": [], "passos_exemplo": {}, "sessoes": []} for e in estrategias}
    socs_inicio_intel = []

    for est in estrategias:
        bat = Bateria(C.CAP_BATERIA_KWH * C.SOC_INICIAL_PCT)
        for dia, sess in zip(dias, sessoes_dias):
            if not est.usa_solar:
                dia_eff = {**dia, "solar_real_kw": [0.0] * C.PASSOS_DIA,
                           "solar_prevista_kw": [0.0] * C.PASSOS_DIA}
                bat_eff = Bateria(0.0)
            else:
                dia_eff, bat_eff = dia, bat
            if est.chave == "inteligente":
                socs_inicio_intel.append(bat.soc)
            passos, log_s = simular_dia(dia_eff, sess, est, bat_eff)
            r = resumir_dia(passos, log_s)
            r.update({"dia": dia["dia"], "tipo": dia["tipo"], "k_real": dia["k_real"],
                      "k_previsto": dia["k_previsto"],
                      "solar_kwh": round(sum(dia["solar_real_kw"]) * C.DT_H, 2)})
            if est.chave == "inteligente":
                r["reserva_ponta_kwh"] = est.historico_reserva[-1]
            out[est.chave]["dias"].append(r)
            for s in log_s:
                s["dia"] = dia["dia"]
            out[est.chave]["sessoes"].extend(log_s)
            out[est.chave]["passos_exemplo"][dia["dia"]] = [
                {k: (round(v, 3) if isinstance(v, float) else v) for k, v in x.items()
                 if k in ("hora", "solar_kw", "ev_kw", "bateria_kw", "soc_pct", "rede_kw", "export_kw")}
                for x in passos]

    # regua: otimo teorico por dia (informacao perfeita)
    otimo = []
    for dia, sess, soc0 in zip(dias, sessoes_dias, socs_inicio_intel):
        r = otimo_teorico(dia, sess, soc0)
        otimo.append(r[0] if r else None)
    return dias, out, otimo


def totalizar(dias_res):
    soma = lambda k: round(sum(d[k] for d in dias_res), 2)
    ev = soma("energia_ev_kwh")
    ren = soma("renovavel_ev_kwh")
    return {
        "energia_ev_kwh": ev,
        "pct_renovavel": round(100 * ren / ev, 1) if ev else 0,
        "rede_kwh": soma("rede_kwh"),
        "rede_ponta_kwh": soma("rede_ponta_kwh"),
        "export_kwh": soma("export_kwh"),
        "custo_rs": soma("custo_rs"),
        "co2_medio_kg": soma("co2_medio_kg"),
        "co2_marginal_kg": soma("co2_marginal_kg"),
        "pico_rede_kw": max(d["pico_rede_kw"] for d in dias_res),
        "dias_acima_limite": sum(1 for d in dias_res if d["pico_rede_kw"] > C.LIMITE_REDE_KW + 1e-6),
        "nao_atendida_kwh": soma("nao_atendida_kwh"),
        "sessoes": sum(d["sessoes"] for d in dias_res),
    }


def viabilidade(tot_base, tot_intel):
    """Payback simples do investimento (valores ilustrativos de config.CAPEX)."""
    capex = sum(C.CAPEX.values())
    economia_mes = tot_base["custo_rs"] - tot_intel["custo_rs"]
    margem_mes = tot_intel["energia_ev_kwh"] * C.PRECO_VENDA_RECARGA - tot_intel["custo_rs"]
    return {
        "capex_rs": capex,
        "capex_itens": C.CAPEX,
        "economia_energia_mes_rs": round(economia_mes, 2),
        "economia_energia_ano_rs": round(economia_mes * 12, 2),
        "payback_so_economia_anos": round(capex / (economia_mes * 12), 1) if economia_mes > 0 else None,
        "receita_liquida_mes_rs": round(margem_mes, 2),
        "payback_com_receita_anos": round(capex / (margem_mes * 12), 1) if margem_mes > 0 else None,
        "preco_venda_kwh": C.PRECO_VENDA_RECARGA,
    }


def salvar(dias, out, otimo):
    os.makedirs(os.path.join(RAIZ, "dados"), exist_ok=True)
    totais = {k: totalizar(v["dias"]) for k, v in out.items()}
    custo_otimo = round(sum(x for x in otimo if x is not None), 2) if all(x is not None for x in otimo) else None
    for i, d in enumerate(out["inteligente"]["dias"]):
        d["custo_otimo_rs"] = otimo[i]

    base, regra, intel = totais["sem_sistema"], totais["regra"], totais["inteligente"]
    km = intel["energia_ev_kwh"] / C.CONSUMO_EV_KWH_POR_KM
    impacto = {
        "km_eletricos_mes": round(km),
        "co2_evitado_vs_combustao_kg": round(km * C.CO2_CARRO_COMBUSTAO_KG_POR_KM - intel["co2_medio_kg"], 1),
        "co2_marginal_evitado_vs_regra_kg": round(regra["co2_marginal_kg"] - intel["co2_marginal_kg"], 1),
        "co2_marginal_evitado_vs_base_kg": round(base["co2_marginal_kg"] - intel["co2_marginal_kg"], 1),
        "custo_otimo_teorico_rs": custo_otimo,
        "eficiencia_vs_otimo_pct": (round(100 * (base["custo_rs"] - intel["custo_rs"]) /
                                          (base["custo_rs"] - custo_otimo), 1) if custo_otimo is not None else None),
    }

    # dias de exemplo: o mais ensolarado e o mais nublado
    dias_ord = sorted(dias, key=lambda d: d["k_real"])
    exemplos = {"nublado": dias_ord[0]["dia"], "ensolarado": dias_ord[-1]["dia"]}
    for k in out:
        out[k]["passos_exemplo"] = {nome: out[k]["passos_exemplo"][d] for nome, d in exemplos.items()}

    resultado = {
        "periodo_dias": N_DIAS,
        "parametros": {
            "equipamentos": C.EQUIPAMENTOS,
            "limite_rede_kw": C.LIMITE_REDE_KW,
            "tarifas": {"fora_ponta": C.TARIFA_FORA_PONTA, "intermediaria": C.TARIFA_INTERMEDIARIA,
                        "ponta": C.TARIFA_PONTA, "credito_exportacao": C.VALOR_CREDITO_EXPORTACAO},
            "fator_co2_medio": C.FATOR_CO2_MEDIO,
            "fator_co2_marginal_ponta": C.FATOR_CO2_MARGINAL_PONTA,
        },
        "dias_exemplo": exemplos,
        "totais": totais,
        "impacto": impacto,
        "viabilidade": viabilidade(base, intel),
        "estrategias": {k: {"nome": v["nome"], "dias": v["dias"], "passos_exemplo": v["passos_exemplo"]}
                        for k, v in out.items()},
        "sessoes_inteligente": out["inteligente"]["sessoes"],
        "sessoes_regra": out["regra"]["sessoes"],
    }
    with open(os.path.join(RAIZ, "dados", "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=1)

    with open(os.path.join(RAIZ, "dados", "resumo_diario.csv"), "w", newline="", encoding="utf-8") as f:
        campos = ["estrategia", "dia", "tipo", "solar_kwh", "energia_ev_kwh", "pct_renovavel", "rede_kwh",
                  "rede_ponta_kwh", "export_kwh", "pico_rede_kw", "custo_rs", "co2_medio_kg",
                  "co2_marginal_kg", "nao_atendida_kwh"]
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore", delimiter=";")
        w.writeheader()
        for k, v in out.items():
            for d in v["dias"]:
                w.writerow({"estrategia": k, **d})

    with open(os.path.join(RAIZ, "dados", "sessoes.csv"), "w", newline="", encoding="utf-8") as f:
        sess = out["inteligente"]["sessoes"]
        w = csv.DictWriter(f, fieldnames=list(sess[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(sess)
    return resultado


def imprimir(res):
    t = res["totais"]
    print(f"\n=== {res['periodo_dias']} dias simulados | {t['inteligente']['sessoes']} sessoes de recarga ===")
    print(f"{'Indicador':32s}{'So rede':>14s}{'Regra S2-S3':>14s}{'Inteligente':>14s}")
    linhas = [("Energia entregue (kWh)", "energia_ev_kwh"), ("% renovavel na recarga", "pct_renovavel"),
              ("Energia da rede (kWh)", "rede_kwh"), ("Rede na ponta (kWh)", "rede_ponta_kwh"),
              ("Pico de demanda (kW)", "pico_rede_kw"), ("Dias acima do limite", "dias_acima_limite"),
              ("Custo liquido (R$)", "custo_rs"), ("CO2 fator medio (kg)", "co2_medio_kg"),
              ("CO2 marginal (kg)", "co2_marginal_kg"), ("Energia nao entregue (kWh)", "nao_atendida_kwh")]
    for nome, k in linhas:
        print(f"{nome:32s}{t['sem_sistema'][k]:>14}{t['regra'][k]:>14}{t['inteligente'][k]:>14}")
    print("Impacto:", json.dumps(res["impacto"], ensure_ascii=False))
    v = res["viabilidade"]
    print(f"CAPEX R$ {v['capex_rs']:.0f} | economia/ano R$ {v['economia_energia_ano_rs']:.0f} | "
          f"payback so economia {v['payback_so_economia_anos']} anos | com receita {v['payback_com_receita_anos']} anos")


if __name__ == "__main__":
    dias, out, otimo = rodar()
    res = salvar(dias, out, otimo)
    imprimir(res)
    if "--sem-graficos" not in sys.argv:
        from .graficos import gerar_graficos
        gerar_graficos(res, os.path.join(RAIZ, "docs", "img"))
        print("Graficos salvos em docs/img/")
    from .dashboard_build import gerar_dashboard
    gerar_dashboard()
    print("Dashboard atualizado em dashboard/index.html")
