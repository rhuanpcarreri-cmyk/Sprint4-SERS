"""
Parametros do Eletroposto Inteligente (Sprint 4 - solucao final).

Todos os valores ficam centralizados aqui para que firmware, simulacao,
dashboard e assistente usem a MESMA base. Valores marcados como
(ilustrativo) sao premissas de projeto academico e podem ser trocados.
"""

# ---------------------------------------------------------------------------
# Passo de tempo
# ---------------------------------------------------------------------------
DT_H = 0.25                      # passo de 15 minutos (resolucao de medicao do SEMS+)
PASSOS_DIA = int(24 / DT_H)      # 96 passos por dia

# ---------------------------------------------------------------------------
# Equipamentos do ecossistema GoodWe
# ---------------------------------------------------------------------------
EQUIPAMENTOS = {
    "inversor": {
        "modelo": "GoodWe GW10K-ET (inversor hibrido trifasico)",
        "potencia_ac_kw": 10.0,
        "papel": "Converte a energia FV, gerencia carga/descarga da bateria e "
                 "faz a interface com a rede (on-grid com backup).",
    },
    "fotovoltaico": {
        "modelo": "Arranjo FV 10 kWp (ex.: 18 modulos de ~550 Wp)",
        "potencia_kwp": 10.0,
    },
    "bateria": {
        "modelo": "GoodWe Lynx Home F - 4 modulos de 3,28 kWh (alta tensao, LFP)",
        "capacidade_kwh": 13.1,
        "potencia_max_kw": 6.5,      # ~0,5C (premissa conservadora)
    },
    "carregadores": {
        "modelo": "2 x GoodWe GW11K-HCA (carregador AC 11 kW, serie HCA)",
        "quantidade": 2,
        "potencia_max_kw": 11.0,
    },
    "monitoramento": {
        "modelo": "SEMS+ (plataforma/app GoodWe) + controlador ESP32 do grupo",
        "papel": "Telemetria, agendamento de recarga e visualizacao.",
    },
}

POTENCIA_FV_KWP = EQUIPAMENTOS["fotovoltaico"]["potencia_kwp"]
PERFORMANCE_RATIO = 0.75         # perdas de temperatura, sujeira, cabos, inversor
CAP_BATERIA_KWH = EQUIPAMENTOS["bateria"]["capacidade_kwh"]
P_BATERIA_KW = EQUIPAMENTOS["bateria"]["potencia_max_kw"]
EFIC_CARGA = 0.96                # eficiencia de carga da bateria
EFIC_DESCARGA = 0.96             # eficiencia de descarga (ida+volta ~92%)
SOC_MIN_PCT = 0.10               # protecao da vida util (LFP)
SOC_INICIAL_PCT = 0.40
N_CARREGADORES = EQUIPAMENTOS["carregadores"]["quantidade"]
P_CARREGADOR_KW = EQUIPAMENTOS["carregadores"]["potencia_max_kw"]

# Limite de importacao da rede (demanda contratada) - o modo inteligente
# respeita; a regra simples das sprints anteriores nao controla isso.
LIMITE_REDE_KW = 15.0

# ---------------------------------------------------------------------------
# Tarifa (modelo horo-sazonal tipo "Tarifa Branca") - valores ilustrativos
# ---------------------------------------------------------------------------
TARIFA_FORA_PONTA = 0.60         # R$/kWh
TARIFA_INTERMEDIARIA = 0.85      # 17h-18h e 21h-22h
TARIFA_PONTA = 1.20              # 18h-21h
VALOR_CREDITO_EXPORTACAO = 0.40  # R$/kWh injetado (compensacao, apos Lei 14.300) - ilustrativo
PRECO_VENDA_RECARGA = 1.90       # R$/kWh cobrado do motorista (ilustrativo)


def tarifa(hora: float) -> float:
    if 18 <= hora < 21:
        return TARIFA_PONTA
    if 17 <= hora < 18 or 21 <= hora < 22:
        return TARIFA_INTERMEDIARIA
    return TARIFA_FORA_PONTA


def eh_ponta(hora: float) -> bool:
    return 18 <= hora < 21


# ---------------------------------------------------------------------------
# Emissoes
# ---------------------------------------------------------------------------
# Fator medio oficial do SIN em 2023 (MCTI): 0,0385 tCO2/MWh = 0,0385 kg/kWh.
FATOR_CO2_MEDIO = 0.0385
# Na ponta, o despacho marginal tende a usar termicas a gas; usamos um fator
# marginal ILUSTRATIVO para a analise de sensibilidade (ciclo combinado ~0,40).
FATOR_CO2_MARGINAL_PONTA = 0.40
FATOR_CO2_MARGINAL_FORA = 0.10

# Comparacao com carro a combustao (ilustrativo, gasolina C):
CONSUMO_EV_KWH_POR_KM = 0.16
CO2_CARRO_COMBUSTAO_KG_POR_KM = 0.13

# ---------------------------------------------------------------------------
# Investimento (CAPEX) - valores ilustrativos de mercado para estudo de viabilidade
# ---------------------------------------------------------------------------
CAPEX = {
    "Sistema FV 10 kWp + inversor GW10K-ET": 42000.0,
    "Bateria Lynx Home F 13,1 kWh": 38000.0,
    "2 carregadores GW11K-HCA + instalacao": 22000.0,
    "Controlador ESP32, sensores e integracao": 1500.0,
}

# Localizacao (para a previsao meteorologica real via Open-Meteo)
LATITUDE = -23.5505
LONGITUDE = -46.6333
