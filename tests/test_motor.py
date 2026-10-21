"""Testes do motor de decisao.  Rodar:  python -m pytest -q"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor import config as C  # noqa: E402
from motor.clima import gerar_dias  # noqa: E402
from motor.demanda import gerar_todas  # noqa: E402
from motor.estrategias import Bateria, Inteligente, RegraSprint3, simular_dia, otimo_teorico  # noqa: E402

DIAS = gerar_dias(10)
SESS = gerar_todas(10)


def _rodar(est):
    bat = Bateria(C.CAP_BATERIA_KWH * C.SOC_INICIAL_PCT)
    saida = []
    for d, s in zip(DIAS, SESS):
        saida.append(simular_dia(d, s, est, bat))
    return saida, bat


def test_inteligente_entrega_toda_energia_pedida():
    saida, _ = _rodar(Inteligente())
    for _, sessoes in saida:
        for s in sessoes:
            assert s["nao_atendida_kwh"] < 0.01, s


def test_inteligente_respeita_demanda_contratada():
    saida, _ = _rodar(Inteligente())
    for passos, _ in saida:
        assert max(p["rede_kw"] for p in passos) <= C.LIMITE_REDE_KW + 1e-6


def test_bateria_dentro_dos_limites():
    for est in (Inteligente(), RegraSprint3()):
        saida, _ = _rodar(est)
        for passos, _ in saida:
            for p in passos:
                assert 100 * C.SOC_MIN_PCT - 0.2 <= p["soc_pct"] <= 100.01
                assert abs(p["bateria_kw"]) <= C.P_BATERIA_KW + 1e-6


def test_balanco_de_energia_fecha():
    saida, _ = _rodar(Inteligente())
    for passos, _ in saida:
        for p in passos:
            entra = p["solar_kw"] + p["rede_kw"] + max(0, -p["bateria_kw"])
            sai = p["ev_kw"] + max(0, p["bateria_kw"]) + p["export_kw"]
            assert abs(entra - sai) < 1e-2


def test_inteligente_mais_barato_que_regra_e_nao_melhor_que_otimo():
    custo = lambda saida: sum(sum(p["custo_rs"] for p in passos) for passos, _ in saida)
    s_int, _ = _rodar(Inteligente())
    s_reg, _ = _rodar(RegraSprint3())
    assert custo(s_int) < custo(s_reg)
    otimo = sum(otimo_teorico(d, s, C.CAP_BATERIA_KWH * C.SOC_INICIAL_PCT)[0] for d, s in zip(DIAS[:3], SESS[:3]))
    assert otimo > 0


def test_tarifa_ponta():
    assert C.tarifa(19) == C.TARIFA_PONTA
    assert C.tarifa(17.5) == C.TARIFA_INTERMEDIARIA
    assert C.tarifa(10) == C.TARIFA_FORA_PONTA
