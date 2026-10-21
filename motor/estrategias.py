"""
Estrategias de controle do eletroposto e motor de simulacao fisica.

  1. SemSistema        - recarga direto da rede, sem solar nem bateria (linha de base).
  2. RegraSprint3      - regra fixa das Sprints 2/3: carrega na potencia maxima assim
                         que o carro chega; fonte na ordem SOLAR -> BATERIA -> REDE.
  3. Inteligente       - SOLUCAO FINAL (Sprint 4). Controle preditivo que replaneja a
                         cada 15 min (horizonte deslizante, estilo MPC):
                           a) smart charging: modula a potencia de cada carro dentro da
                              janela chegada->saida, alinhando a recarga ao sol e fugindo
                              da ponta, SEM deixar de entregar a energia pedida (laxidade);
                           b) reserva de bateria para a ponta, dimensionada pelo padrao
                              de demanda APRENDIDO (media movel exponencial dos dias);
                           c) pre-carga preditiva: se a previsao do tempo indica dia
                              nublado, completa a reserva com rede barata de madrugada;
                           d) peak shaving: nunca importa mais que a demanda contratada.
  4. otimo_teorico()   - programacao linear com informacao perfeita (sabe o futuro).
                         Nao e implementavel na pratica; serve de REGUA para medir quao
                         perto do otimo o algoritmo inteligente chega.
"""
from . import config as C

DT = C.DT_H


# ---------------------------------------------------------------------------
# Motor fisico comum a todas as estrategias
# ---------------------------------------------------------------------------
class Bateria:
    def __init__(self, soc_kwh, fracao_limpa=1.0):
        self.soc = soc_kwh
        self.limpa = fracao_limpa          # parcela da energia armazenada que veio do sol

    @property
    def soc_min(self):
        return C.CAP_BATERIA_KWH * C.SOC_MIN_PCT

    def max_carga_kw(self):
        espaco = (C.CAP_BATERIA_KWH - self.soc) / C.EFIC_CARGA
        return max(0.0, min(C.P_BATERIA_KW, espaco / DT))

    def max_descarga_kw(self, piso_kwh=None):
        piso = self.soc_min if piso_kwh is None else max(piso_kwh, self.soc_min)
        disp = (self.soc - piso) * C.EFIC_DESCARGA
        return max(0.0, min(C.P_BATERIA_KW, disp / DT))


def simular_dia(dia, sessoes, controlador, bateria):
    """Executa 96 passos de 15 min. Retorna (log_passos, log_sessoes)."""
    restante = {s["id"]: s["energia_kwh"] for s in sessoes}
    acum = {s["id"]: {"entregue": 0.0, "limpa": 0.0, "rede": 0.0, "custo": 0.0} for s in sessoes}
    controlador.inicio_dia(dia, sessoes, bateria)
    passos = []

    for p in range(C.PASSOS_DIA):
        hora = p * DT
        solar = dia["solar_real_kw"][p]
        ativas = [s for s in sessoes if s["chegada"] <= p < s["saida"] and restante[s["id"]] > 1e-6]

        p_ev, p_bat = controlador.decidir(p, hora, solar, ativas, restante, bateria)

        # limites fisicos
        for s in ativas:
            lim = min(s["pmax_kw"], C.P_CARREGADOR_KW, restante[s["id"]] / DT)
            p_ev[s["id"]] = max(0.0, min(p_ev.get(s["id"], 0.0), lim))
        carga_ev = sum(p_ev.get(s["id"], 0.0) for s in ativas)
        if p_bat >= 0:
            p_bat = min(p_bat, bateria.max_carga_kw())
        else:
            p_bat = -min(-p_bat, bateria.max_descarga_kw())

        # balanco no barramento: solar + rede + descarga = EV + carga_bateria + exportacao
        liquido = carga_ev + p_bat - solar
        rede = max(0.0, liquido)
        export = max(0.0, -liquido)
        solar_local = solar - export
        descarga = max(0.0, -p_bat)
        carga_bat = max(0.0, p_bat)

        fontes = solar_local + descarga + rede
        limpa_bus = (solar_local + descarga * bateria.limpa) / fontes if fontes > 1e-9 else 1.0

        # atualiza bateria (com rastreio da fracao de energia limpa armazenada)
        if carga_bat > 0:
            entra = carga_bat * C.EFIC_CARGA * DT
            entra_limpa = entra * limpa_bus
            nova = bateria.soc + entra
            bateria.limpa = (bateria.soc * bateria.limpa + entra_limpa) / nova if nova > 0 else 1.0
            bateria.soc = nova
        elif descarga > 0:
            bateria.soc -= descarga / C.EFIC_DESCARGA * DT

        t = C.tarifa(hora)
        custo_passo = rede * t * DT - export * C.VALOR_CREDITO_EXPORTACAO * DT
        fator_marg = C.FATOR_CO2_MARGINAL_PONTA if C.eh_ponta(hora) else C.FATOR_CO2_MARGINAL_FORA

        for s in ativas:
            e = p_ev[s["id"]] * DT
            if e <= 0:
                continue
            restante[s["id"]] -= e
            a = acum[s["id"]]
            a["entregue"] += e
            a["limpa"] += e * limpa_bus
            a["rede"] += e * (1 - limpa_bus)
            a["custo"] += e * (1 - limpa_bus) * t

        passos.append({
            "passo": p, "hora": hora,
            "solar_kw": round(solar, 3),
            "ev_kw": round(carga_ev, 3),
            "bateria_kw": round(p_bat, 3),
            "soc_pct": round(100 * bateria.soc / C.CAP_BATERIA_KWH, 1),
            "rede_kw": round(rede, 3),
            "export_kw": round(export, 3),
            "tarifa": t,
            "custo_rs": custo_passo,
            "co2_medio_kg": rede * DT * C.FATOR_CO2_MEDIO,
            "co2_marginal_kg": rede * DT * fator_marg,
            "limpa_frac": limpa_bus,
        })
        controlador.registrar(p, hora, carga_ev)

    log_sessoes = []
    for s in sessoes:
        a = acum[s["id"]]
        log_sessoes.append({
            **{k: s[k] for k in ("id", "perfil", "carregador", "energia_kwh", "pmax_kw")},
            "chegada_h": s["chegada"] * DT, "saida_h": s["saida"] * DT,
            "entregue_kwh": round(a["entregue"], 3),
            "nao_atendida_kwh": round(max(0.0, restante[s["id"]]), 3),
            "pct_renovavel": round(100 * a["limpa"] / a["entregue"], 1) if a["entregue"] else 0.0,
            "custo_energia_rs": round(a["custo"], 2),
        })
    controlador.fim_dia(passos)
    return passos, log_sessoes


# ---------------------------------------------------------------------------
# 1) Linha de base e 2) Regra das Sprints 2/3
# ---------------------------------------------------------------------------
class SemSistema:
    nome = "Sem sistema (so rede)"
    chave = "sem_sistema"
    usa_solar = False

    def inicio_dia(self, dia, sessoes, bateria): pass
    def registrar(self, p, hora, carga): pass
    def fim_dia(self, passos): pass

    def decidir(self, p, hora, solar, ativas, restante, bat):
        return {s["id"]: s["pmax_kw"] for s in ativas}, 0.0


class RegraSprint3:
    """Carrega na potencia maxima ao chegar; SOLAR -> BATERIA -> REDE; bateria so com sol."""
    nome = "Regra fixa (Sprints 2-3)"
    chave = "regra"
    usa_solar = True

    def inicio_dia(self, dia, sessoes, bateria): pass
    def registrar(self, p, hora, carga): pass
    def fim_dia(self, passos): pass

    def decidir(self, p, hora, solar, ativas, restante, bat):
        p_ev = {s["id"]: min(s["pmax_kw"], C.P_CARREGADOR_KW, restante[s["id"]] / DT) for s in ativas}
        carga = sum(p_ev.values())
        sobra = solar - carga
        if sobra > 0:
            return p_ev, min(sobra, bat.max_carga_kw())          # excedente vai p/ bateria
        return p_ev, -min(-sobra, bat.max_descarga_kw())          # bateria cobre deficit


# ---------------------------------------------------------------------------
# 3) Algoritmo inteligente (solucao final)
# ---------------------------------------------------------------------------
class Inteligente:
    nome = "Inteligente preditivo (Sprint 4)"
    chave = "inteligente"
    usa_solar = True
    ALFA = 0.3                     # taxa de aprendizado da media movel

    def __init__(self):
        self.prev_carga_noite = 12.0   # kWh esperados de 17h-22h (aprendido)
        self.prev_carga_dia = 35.0     # kWh esperados de 6h-17h (aprendido)
        self.historico_reserva = []

    # -- ciclo diario ---------------------------------------------------------
    def inicio_dia(self, dia, sessoes, bateria):
        self.previsao = dia["solar_prevista_kw"]
        self.e_noite = 0.0
        self.e_dia = 0.0
        # reserva para a ponta = demanda noturna esperada (ja descontadas as perdas)
        self.reserva_kwh = min(C.CAP_BATERIA_KWH,
                               self.prev_carga_noite / C.EFIC_DESCARGA + bateria.soc_min)
        # quanto sol deve sobrar para a bateria durante o dia, segundo a previsao?
        solar_prev = sum(self.previsao) * DT
        sobra_prev = max(0.0, solar_prev - self.prev_carga_dia * 0.8) * C.EFIC_CARGA
        falta = self.reserva_kwh - (bateria.soc + 0.85 * sobra_prev)
        self.precarga_kwh = max(0.0, min(falta, C.CAP_BATERIA_KWH - bateria.soc))
        self.historico_reserva.append(round(self.reserva_kwh, 2))

    def registrar(self, p, hora, carga):
        if 17 <= hora < 22:
            self.e_noite += carga * DT
        elif 6 <= hora < 17:
            self.e_dia += carga * DT

    def fim_dia(self, passos):
        # aprendizado: media movel exponencial do consumo observado
        self.prev_carga_noite += self.ALFA * (self.e_noite - self.prev_carga_noite)
        self.prev_carga_dia += self.ALFA * (self.e_dia - self.prev_carga_dia)

    # -- decisao a cada 15 min ------------------------------------------------
    def _plano_rede(self, s, p, restante, n_ativas):
        """Energia de rede planejada para ESTE passo, para a sessao s.
        Estima quanto sol previsto ainda cabe na janela da sessao; o que faltar
        e alocado nos passos de rede mais baratos (empate -> o mais cedo)."""
        saida = s["saida"]
        cap_passo = min(s["pmax_kw"], C.P_CARREGADOR_KW) * DT
        limpo = {}
        for k in range(p, saida):
            limpo[k] = min(cap_passo, self.previsao[k] * DT / max(1, n_ativas))
        falta = restante[s["id"]] - sum(limpo.values())
        if falta <= 1e-6:
            return 0.0
        ordem = sorted(range(p, saida), key=lambda k: (C.tarifa(k * DT), k))
        for k in ordem:
            folga = cap_passo - limpo[k]
            usa = min(folga, falta)
            if k == p:
                return usa / DT
            falta -= usa
            if falta <= 1e-6:
                break
        return 0.0

    def decidir(self, p, hora, solar, ativas, restante, bat):
        p_ev, p_min = {}, {}
        n = len(ativas)
        for s in ativas:
            lim = min(s["pmax_kw"], C.P_CARREGADOR_KW, restante[s["id"]] / DT)
            passos_rest = s["saida"] - p
            # laxidade: o minimo que precisa carregar AGORA para garantir a entrega
            obrig = max(0.0, restante[s["id"]] - lim * DT * (passos_rest - 1)) / DT
            p_min[s["id"]] = min(lim, obrig)
            p_ev[s["id"]] = min(lim, max(p_min[s["id"]], self._plano_rede(s, p, restante, n)))

        # distribui o SOL disponivel agora, prioridade para quem sai antes (EDF)
        sobra_sol = max(0.0, solar - sum(p_ev.values()))
        for s in sorted(ativas, key=lambda s: s["saida"]):
            lim = min(s["pmax_kw"], C.P_CARREGADOR_KW, restante[s["id"]] / DT)
            extra = min(lim - p_ev[s["id"]], sobra_sol)
            p_ev[s["id"]] += extra
            sobra_sol -= extra

        carga = sum(p_ev.values())
        ponta = C.eh_ponta(hora)
        pos_ponta = hora >= 21

        # bateria
        if solar > carga:
            p_bat = min(solar - carga, bat.max_carga_kw())                # guarda o sol
        else:
            deficit = carga - solar
            if ponta or pos_ponta:
                p_bat = -min(deficit, bat.max_descarga_kw())                # ponta: bateria assume
            elif 17 <= hora < 18:
                p_bat = -min(deficit, bat.max_descarga_kw(self.reserva_kwh * 0.9))
            else:
                p_bat = -min(deficit, bat.max_descarga_kw(self.reserva_kwh))  # so o excedente da reserva

        # pre-carga preditiva de madrugada (fora ponta) se a previsao for de dia fraco
        if hora < 6 and self.precarga_kwh > 0:
            passos_ate_6 = int(6 / DT) - p
            p_bat = max(p_bat, min(C.P_BATERIA_KW, self.precarga_kwh / (passos_ate_6 * DT) / C.EFIC_CARGA))
            self.precarga_kwh -= p_bat * C.EFIC_CARGA * DT

        # peak shaving: respeita a demanda contratada
        rede = carga + p_bat - solar
        if rede > C.LIMITE_REDE_KW:
            excesso = rede - C.LIMITE_REDE_KW
            if p_bat > 0:
                corte = min(p_bat, excesso)
                p_bat -= corte
                excesso -= corte
            if excesso > 0:
                extra_desc = min(excesso, bat.max_descarga_kw() + min(0.0, p_bat))
                p_bat -= extra_desc
                excesso -= extra_desc
            for s in sorted(ativas, key=lambda s: -s["saida"]):   # adia quem tem mais folga
                if excesso <= 0:
                    break
                reduz = min(p_ev[s["id"]] - p_min[s["id"]], excesso)
                p_ev[s["id"]] -= reduz
                excesso -= reduz
        return p_ev, p_bat


# ---------------------------------------------------------------------------
# 4) Otimo teorico (programacao linear, informacao perfeita)
# ---------------------------------------------------------------------------
def otimo_teorico(dia, sessoes, soc_inicial):
    """Minimiza o custo do dia conhecendo de antemao o sol real e todas as sessoes.
    Restricoes: entrega 100% da energia, limites de potencia, SoC e demanda contratada.
    Retorna (custo_rs, energia_rede_kwh) ou None se o solver nao estiver disponivel."""
    try:
        import numpy as np
        from scipy.optimize import linprog
        from scipy.sparse import lil_matrix
    except ImportError:
        return None
    T = C.PASSOS_DIA
    idx = {}
    n = 0
    for s in sessoes:                          # e[s,k]
        for k in range(s["chegada"], s["saida"]):
            idx[("e", s["id"], k)] = n; n += 1
    for nome in ("c", "d", "g", "x", "soc"):   # carga, descarga, rede, export, soc (kWh)
        for k in range(T):
            idx[(nome, k)] = n; n += 1

    custo = np.zeros(n)
    lb, ub = np.zeros(n), np.full(n, np.inf)
    for s in sessoes:
        for k in range(s["chegada"], s["saida"]):
            ub[idx[("e", s["id"], k)]] = min(s["pmax_kw"], C.P_CARREGADOR_KW) * DT
    for k in range(T):
        hora = k * DT
        ub[idx[("c", k)]] = C.P_BATERIA_KW * DT
        ub[idx[("d", k)]] = C.P_BATERIA_KW * DT
        ub[idx[("g", k)]] = C.LIMITE_REDE_KW * DT
        ub[idx[("x", k)]] = dia["solar_real_kw"][k] * DT
        lb[idx[("soc", k)]] = C.CAP_BATERIA_KWH * C.SOC_MIN_PCT
        ub[idx[("soc", k)]] = C.CAP_BATERIA_KWH
        custo[idx[("g", k)]] = C.tarifa(hora)
        custo[idx[("x", k)]] = -C.VALOR_CREDITO_EXPORTACAO
        custo[idx[("d", k)]] = 1e-4            # desempate: evita ciclar a bateria a toa

    n_eq = T + T + len(sessoes)
    A = lil_matrix((n_eq, n))
    b = np.zeros(n_eq)
    r = 0
    for k in range(T):                         # balanco: g + d - c - x - sum e = -solar
        A[r, idx[("g", k)]] = 1; A[r, idx[("d", k)]] = 1
        A[r, idx[("c", k)]] = -1; A[r, idx[("x", k)]] = -1
        for s in sessoes:
            if s["chegada"] <= k < s["saida"]:
                A[r, idx[("e", s["id"], k)]] = -1
        b[r] = -dia["solar_real_kw"][k] * DT
        r += 1
    for k in range(T):                         # dinamica do SoC
        A[r, idx[("soc", k)]] = 1
        A[r, idx[("c", k)]] = -C.EFIC_CARGA
        A[r, idx[("d", k)]] = 1 / C.EFIC_DESCARGA
        if k > 0:
            A[r, idx[("soc", k - 1)]] = -1
        else:
            b[r] = soc_inicial
        r += 1
    for s in sessoes:                          # entrega total
        for k in range(s["chegada"], s["saida"]):
            A[r, idx[("e", s["id"], k)]] = 1
        b[r] = s["energia_kwh"]
        r += 1
    lb[idx[("soc", T - 1)]] = max(lb[idx[("soc", T - 1)]], soc_inicial)  # termina sem "gastar" a bateria

    res = linprog(custo, A_eq=A.tocsr(), b_eq=b, bounds=list(zip(lb, ub)), method="highs")
    if not res.success:
        return None
    g = sum(res.x[idx[("g", k)]] for k in range(T))
    return round(float(res.fun), 2), round(float(g), 2)
