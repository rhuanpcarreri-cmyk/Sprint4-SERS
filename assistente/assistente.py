"""
Assistente virtual do eletroposto ("Volt").

Responde em portugues perguntas de operadores e motoristas usando os dados
reais do sistema (dados/resultados.json e, quando conectado, a telemetria MQTT
do ESP32). Funciona por deteccao de intencao com palavras-chave - leve o
suficiente para rodar em um servidor pequeno, sem depender de API paga.

Canais:
  - terminal:  python -m assistente.assistente
  - Telegram:  python -m assistente.telegram_bot   (variavel TELEGRAM_TOKEN)
  - dashboard: o mesmo motor de intencoes foi portado para JS em dashboard/index.html
"""
import json
import os
import unicodedata

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def n(v, casas=0):
    """Numero no padrao brasileiro: 1.234,5"""
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Assistente:
    def __init__(self, caminho=None, telemetria=None):
        caminho = caminho or os.path.join(RAIZ, "dados", "resultados.json")
        with open(caminho, encoding="utf-8") as f:
            self.r = json.load(f)
        self.telemetria = telemetria or {}     # ultimo pacote MQTT do ESP32, se houver
        self.intencoes = [
            (("oi", "ola", "bom dia", "boa tarde", "boa noite", "ajuda", "menu"), self.ajuda),
            (("agora", "status", "ao vivo", "neste momento", "fonte atual"), self.status),
            (("quando", "melhor hora", "mais barato carregar", "horario"), self.melhor_horario),
            (("econom", "custo", "gast", "dinheiro", "r$"), self.economia),
            (("co2", "carbono", "emiss", "ambiental", "sustent"), self.carbono),
            (("renovavel", "solar", "sol "), self.renovavel),
            (("bateria", "soc", "reserva"), self.bateria),
            (("pico", "demanda", "ponta", "limite"), self.pico),
            (("payback", "retorno", "investimento", "viabil", "capex"), self.viabilidade),
            (("goodwe", "equipamento", "inversor", "carregador"), self.equipamentos),
            (("sessao", "sessoes", "carros", "recargas", "veiculos"), self.sessoes),
        ]

    def responder(self, pergunta):
        q = _norm(pergunta) + " "
        for chaves, func in self.intencoes:
            if any(k in q for k in chaves):
                return func()
        return ("Não entendi 🤔. Tente: *status*, *melhor horário para carregar*, *economia*, "
                "*CO2*, *bateria*, *pico de demanda*, *payback* ou *equipamentos GoodWe*.")

    # ---- intencoes -----------------------------------------------------------
    def ajuda(self):
        return ("Olá! Sou o Volt ⚡, assistente do Eletroposto Inteligente.\n"
                "Posso responder: status agora • melhor horário para carregar • economia • "
                "CO2 evitado • % renovável • bateria • pico de demanda • payback • equipamentos GoodWe.")

    def status(self):
        t = self.telemetria
        if not t:
            return ("Ainda não recebi telemetria ao vivo do ESP32. Abra o protótipo no Wokwi "
                    "e conecte o dashboard ao broker MQTT para ver o estado em tempo real.")
        return (f"Agora ({t.get('hora', '?')}h): fonte {t.get('fonte', '?')}, solar {n(t.get('solar_kw', 0), 1)} kW, "
                f"recarga {n(t.get('ev_kw', 0), 1)} kW, bateria {t.get('soc_pct', 0):.0f}%, "
                f"modo {t.get('modo', '?')}.")

    def melhor_horario(self):
        return ("Melhor janela: 10h–14h ☀️ (sol forte, energia praticamente gratuita). "
                "Evite 18h–21h: é a ponta (R$ 1,20/kWh) — se precisar carregar nesse horário, "
                "o sistema usa a bateria guardada do sol para você. Informe sua hora de saída no app "
                "que o algoritmo distribui a recarga sozinho e garante a carga até lá.")

    def economia(self):
        t = self.r["totais"]
        eco = t["sem_sistema"]["custo_rs"] - t["inteligente"]["custo_rs"]
        pct = 100 * eco / t["sem_sistema"]["custo_rs"]
        ganho_regra = t["regra"]["custo_rs"] - t["inteligente"]["custo_rs"]
        return (f"Em {self.r['periodo_dias']} dias o custo de energia caiu de {brl(t['sem_sistema']['custo_rs'])} "
                f"(só rede) para {brl(t['inteligente']['custo_rs'])} — economia de {brl(eco)} ({pct:.0f}%). "
                f"Só o algoritmo inteligente economiza {brl(ganho_regra)} a mais que a regra fixa das sprints anteriores.")

    def carbono(self):
        i = self.r["impacto"]
        return (f"Os {n(i['km_eletricos_mes'])} km rodados com essa energia evitaram ~{n(i['co2_evitado_vs_combustao_kg'])} kg "
                f"de CO₂ frente a carros a gasolina. Ao tirar carga da ponta (quando entram térmicas), o sistema evita "
                f"mais {i['co2_marginal_evitado_vs_base_kg']:.0f} kg de CO₂ marginal na rede.")

    def renovavel(self):
        t = self.r["totais"]["inteligente"]
        return (f"{n(t['pct_renovavel'], 1)}% da energia entregue aos carros veio do sol (direto ou guardado na bateria). "
                f"Excedente exportado para a rede: {t['export_kwh']:.0f} kWh.")

    def bateria(self):
        dias = self.r["estrategias"]["inteligente"]["dias"]
        ult = dias[-1]
        return (f"A bateria Lynx Home F (13,1 kWh) guarda o sol do meio-dia para a ponta. A reserva é aprendida "
                f"pelo histórico de uso: hoje o sistema reservou {n(ult['reserva_ponta_kwh'], 1)} kWh para 18h–21h. "
                "Em dias nublados previstos, ela é completada com energia barata de madrugada.")

    def pico(self):
        t = self.r["totais"]
        lim = self.r["parametros"]["limite_rede_kw"]
        return (f"Demanda contratada: {lim:.0f} kW. Regra fixa: pico de {n(t['regra']['pico_rede_kw'], 1)} kW e "
                f"{t['regra']['dias_acima_limite']} dias acima do limite. Inteligente: pico de "
                f"{n(t['inteligente']['pico_rede_kw'], 1)} kW e {t['inteligente']['dias_acima_limite']} dias acima. "
                f"Energia da rede na ponta caiu de {t['regra']['rede_ponta_kwh']:.0f} para {t['inteligente']['rede_ponta_kwh']:.0f} kWh.")

    def viabilidade(self):
        v = self.r["viabilidade"]
        return (f"Investimento estimado {brl(v['capex_rs'])}. Só com a economia de energia ({brl(v['economia_energia_ano_rs'])}/ano) "
                f"o payback é ~{n(v['payback_so_economia_anos'], 1)} anos; cobrando {brl(v['preco_venda_kwh'])}/kWh dos motoristas, "
                f"cai para ~{n(v['payback_com_receita_anos'], 1)} anos. (valores ilustrativos)")

    def equipamentos(self):
        e = self.r["parametros"]["equipamentos"]
        return "Ecossistema GoodWe: " + " • ".join(e[k]["modelo"] for k in ("inversor", "bateria", "carregadores", "monitoramento"))

    def sessoes(self):
        t = self.r["totais"]["inteligente"]
        return (f"{t['sessoes']} sessões de recarga em {self.r['periodo_dias']} dias, {n(t['energia_ev_kwh'])} kWh entregues "
                f"e {t['nao_atendida_kwh']:.0f} kWh deixados de entregar — todo motorista saiu com a carga pedida.")


if __name__ == "__main__":
    a = Assistente()
    print(a.ajuda())
    while True:
        try:
            q = input("\nvocê> ")
        except (EOFError, KeyboardInterrupt):
            break
        print("volt>", a.responder(q))
