"""
Geracao das sessoes de recarga de um eletroposto em estacionamento comercial.

Perfis de usuario (cada um com flexibilidade diferente):
  - "expediente": chega de manha, sai no fim da tarde -> MUITO flexivel
  - "visita":     fica 1-3 h durante o dia            -> pouco flexivel
  - "noturno":    chega no inicio da noite (ponta)    -> pouco flexivel, horario caro

Cada sessao informa chegada, saida prevista (o motorista informa no app/QR),
energia desejada e a potencia maxima que o carro aceita em AC.
"""
import random

from . import config as C


def _hora_para_passo(h):
    return int(round(h / C.DT_H))


def gerar_sessoes_dia(dia, rng):
    sessoes = []
    sid = 0

    def nova(perfil, carregador, ini_h, fim_h, energia, pmax):
        nonlocal sid
        sid += 1
        ini, fim = _hora_para_passo(ini_h), _hora_para_passo(fim_h)
        energia = min(energia, pmax * (fim - ini) * C.DT_H * 0.95)  # fisicamente viavel
        sessoes.append({
            "id": f"D{dia:02d}-S{sid}",
            "perfil": perfil,
            "carregador": carregador,
            "chegada": ini,
            "saida": fim,
            "energia_kwh": round(energia, 2),
            "pmax_kw": pmax,
        })
        return fim

    # Carregador 1: carro de expediente + sessao noturna
    t = rng.uniform(7.0, 9.0)
    fim = nova("expediente", 1, t, rng.uniform(16.5, 18.0),
               rng.uniform(18, 32), rng.choice([7.4, 11.0]))
    ini_n = max(fim * C.DT_H + 0.25, rng.uniform(18.0, 19.0))
    nova("noturno", 1, ini_n, ini_n + rng.uniform(1.5, 2.5),
         rng.uniform(8, 14), rng.choice([7.4, 11.0]))

    # Carregador 2: visitas curtas ao longo do dia, ultima pode cair na ponta
    h = rng.uniform(8.0, 10.0)
    while h < 19.5:
        dur = rng.uniform(1.0, 2.5)
        fim_h = min(h + dur, 22.0)
        nova("visita", 2, h, fim_h, rng.uniform(5, 13), rng.choice([7.4, 11.0]))
        h = fim_h + rng.uniform(0.5, 2.0)
    return sessoes


def gerar_todas(n_dias=30, semente=7):
    rng = random.Random(semente)
    return [gerar_sessoes_dia(d + 1, rng) for d in range(n_dias)]
