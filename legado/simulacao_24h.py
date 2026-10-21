"""
Eletroposto Inteligente - EV Challenge 2026 (GoodWe)
Simulacao de 24h da logica de gestao de energia (SOLAR -> BATERIA -> REDE).

Reproduz a MESMA logica de decisao do firmware ESP32 (eletroposto_inteligente.ino),
gerando um dataset reproduzivel (dados_simulacao_24h.csv) e graficos para o README.

Sem dependencias exoticas: usa apenas matplotlib e csv.
"""

import csv
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------
# PARAMETROS DO SISTEMA (identicos aos do firmware)
# Valores ilustrativos e parametrizaveis - servem de base para a prova de conceito.
# ----------------------------------------------------------------------
SOLAR_MAX_KW      = 10.0    # potencia de pico do arranjo fotovoltaico
CARREGADOR_MAX_KW = 7.4     # potencia maxima do carregador EV (AC trifasico tipico)
BAT_CAP_KWH       = 15.0    # capacidade do banco de baterias BESS
SOC_MIN_KWH       = 1.5     # reserva minima da bateria (~10%)
SOC_INICIAL_KWH   = 4.0     # carga inicial no comeco do dia

TARIFA_PONTA  = 1.20        # R$/kWh no horario de ponta
TARIFA_FORA   = 0.60        # R$/kWh fora de ponta
HORAS_PONTA   = {18, 19, 20}  # janela de ponta (18h-21h)

FATOR_CO2_REDE = 0.12       # kgCO2 por kWh vindo da rede (ilustrativo)

# ----------------------------------------------------------------------
# PERFIS DO DIA DE REFERENCIA
# ----------------------------------------------------------------------
def curva_solar(h):
    """Geracao solar normalizada (0..1) ao longo do dia. Pico ao meio-dia."""
    if h < 6 or h > 18:
        return 0.0
    x = (h - 6) / 12.0
    return math.sin(x * math.pi)

# fator climatico: 1.0 = ceu limpo. Nuvens reduzem a geracao em alguns horarios.
clima = {h: 1.0 for h in range(24)}
clima[13] = 0.55   # nuvem passando a tarde
clima[14] = 0.50

# demanda do carro (kW) por hora - carro chega de manha e a noite (na ponta)
demanda_carro = {h: 0.0 for h in range(24)}
for h in [7, 8]:
    demanda_carro[h] = 7.4         # carga matinal
demanda_carro[9] = 3.0
for h in [18, 19, 20]:
    demanda_carro[h] = 7.4         # carga noturna - bem no horario de ponta
demanda_carro[21] = 4.0
demanda_carro[22] = 2.0

def tarifa(h):
    return TARIFA_PONTA if h in HORAS_PONTA else TARIFA_FORA

# ----------------------------------------------------------------------
# LOOP DE SIMULACAO (passo = 1 hora)
# ----------------------------------------------------------------------
soc = SOC_INICIAL_KWH
custo_rede = 0.0
custo_sem_sistema = 0.0
co2_evitado = 0.0
e_solar_total = 0.0
e_bateria_total = 0.0
e_rede_total = 0.0

linhas = []
for h in range(24):
    geracao = SOLAR_MAX_KW * curva_solar(h) * clima[h]
    demanda = demanda_carro[h]
    t = tarifa(h)

    e_solar = e_bateria = e_rede = 0.0
    fonte = "OCIOSO"

    if demanda <= 0.001:
        # sem carro: excedente solar carrega a bateria
        fonte = "OCIOSO"
        if geracao > 0:
            carga = min(geracao, BAT_CAP_KWH - soc)
            soc += carga
    else:
        if geracao >= demanda:
            # solar cobre tudo; excedente vai para a bateria
            fonte = "SOLAR"
            e_solar = demanda
            excedente = geracao - demanda
            carga = min(excedente, BAT_CAP_KWH - soc)
            soc += carga
        else:
            # solar nao cobre: usa o que tem de solar e completa
            e_solar = geracao
            deficit = demanda - geracao
            disp_bat = max(0.0, soc - SOC_MIN_KWH)
            if disp_bat > 0:
                e_bateria = min(deficit, disp_bat)
                soc -= e_bateria
                deficit -= e_bateria
                fonte = "BATERIA"
            if deficit > 0.001:
                e_rede = deficit
                fonte = "REDE"

    # contabilidade
    custo_rede        += e_rede * t
    custo_sem_sistema += demanda * t            # cenario sem solar/bateria: tudo da rede
    co2_evitado       += (e_solar + e_bateria) * FATOR_CO2_REDE
    e_solar_total     += e_solar
    e_bateria_total   += e_bateria
    e_rede_total      += e_rede

    linhas.append({
        "hora": f"{h:02d}:00",
        "geracao_solar_kw": round(geracao, 2),
        "demanda_kw": round(demanda, 2),
        "fonte": fonte,
        "soc_bateria_pct": round(100 * soc / BAT_CAP_KWH, 1),
        "e_solar_kwh": round(e_solar, 2),
        "e_bateria_kwh": round(e_bateria, 2),
        "e_rede_kwh": round(e_rede, 2),
        "tarifa_rs_kwh": t,
        "periodo": "PONTA" if h in HORAS_PONTA else "fora de ponta",
    })

economia = custo_sem_sistema - custo_rede
perc = 100 * economia / custo_sem_sistema if custo_sem_sistema else 0

# ----------------------------------------------------------------------
# SAIDA: CSV
# ----------------------------------------------------------------------
with open("dados_simulacao_24h.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
    w.writeheader()
    w.writerows(linhas)

# ----------------------------------------------------------------------
# RESUMO
# ----------------------------------------------------------------------
print("="*58)
print("RESUMO DA SIMULACAO DE 24h - ELETROPOSTO INTELIGENTE")
print("="*58)
print(f"Energia entregue ao carro (total)...: {e_solar_total+e_bateria_total+e_rede_total:6.2f} kWh")
print(f"  - de energia solar................: {e_solar_total:6.2f} kWh")
print(f"  - de bateria (solar armazenado)...: {e_bateria_total:6.2f} kWh")
print(f"  - da rede eletrica................: {e_rede_total:6.2f} kWh")
ren = e_solar_total + e_bateria_total
tot = ren + e_rede_total
print(f"% atendido por energia renovavel....: {100*ren/tot:5.1f} %")
print("-"*58)
print(f"Custo SEM o sistema (tudo da rede)..: R$ {custo_sem_sistema:6.2f}")
print(f"Custo COM o sistema (so a rede res.): R$ {custo_rede:6.2f}")
print(f"Economia no dia.....................: R$ {economia:6.2f}  ({perc:.0f}%)")
print(f"CO2 evitado no dia..................: {co2_evitado:6.2f} kg")
print("="*58)

# guarda o resumo para o README
with open("resumo_simulacao.txt", "w", encoding="utf-8") as f:
    f.write(f"energia_total_kwh={tot:.2f}\n")
    f.write(f"e_solar_kwh={e_solar_total:.2f}\n")
    f.write(f"e_bateria_kwh={e_bateria_total:.2f}\n")
    f.write(f"e_rede_kwh={e_rede_total:.2f}\n")
    f.write(f"perc_renovavel={100*ren/tot:.1f}\n")
    f.write(f"custo_sem={custo_sem_sistema:.2f}\n")
    f.write(f"custo_com={custo_rede:.2f}\n")
    f.write(f"economia={economia:.2f}\n")
    f.write(f"economia_perc={perc:.0f}\n")
    f.write(f"co2_evitado={co2_evitado:.2f}\n")

# ----------------------------------------------------------------------
# GRAFICOS
# ----------------------------------------------------------------------
horas = list(range(24))
ger   = [SOLAR_MAX_KW * curva_solar(h) * clima[h] for h in horas]
dem   = [demanda_carro[h] for h in horas]
soc_l = [l["soc_bateria_pct"] for l in linhas]
e_sol = [l["e_solar_kwh"] for l in linhas]
e_bat = [l["e_bateria_kwh"] for l in linhas]
e_red = [l["e_rede_kwh"] for l in linhas]

AZUL   = "#1a1f5e"
AZUL2  = "#4a5bc4"
VERDE  = "#1d9e75"
AMARELO= "#e0a106"
VERM   = "#d23b3b"

# Grafico 1: geracao solar x demanda + SoC
fig, ax1 = plt.subplots(figsize=(10, 4.5))
ax1.plot(horas, ger, color=AMARELO, lw=2.5, marker="o", ms=3, label="Geracao solar (kW)")
ax1.plot(horas, dem, color=AZUL, lw=2.5, marker="s", ms=3, label="Demanda do carro (kW)")
ax1.axvspan(18, 21, color=VERM, alpha=0.10, label="Horario de ponta")
ax1.set_xlabel("Hora do dia"); ax1.set_ylabel("Potencia (kW)")
ax1.set_xticks(range(0, 24, 2)); ax1.grid(alpha=0.25)
ax2 = ax1.twinx()
ax2.plot(horas, soc_l, color=VERDE, lw=2, ls="--", label="Bateria SoC (%)")
ax2.set_ylabel("SoC da bateria (%)"); ax2.set_ylim(0, 105)
l1, lb1 = ax1.get_legend_handles_labels()
l2, lb2 = ax2.get_legend_handles_labels()
ax1.legend(l1+l2, lb1+lb2, loc="upper left", fontsize=8, framealpha=0.9)
plt.title("Geracao solar, demanda do carro e carga da bateria ao longo do dia",
          color=AZUL, fontweight="bold")
plt.tight_layout(); plt.savefig("assets/grafico_geracao_demanda.png", dpi=130); plt.close()

# Grafico 2: fonte de energia que atende o carro (empilhado)
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.bar(horas, e_sol, color=AMARELO, label="Solar")
ax.bar(horas, e_bat, bottom=e_sol, color=VERDE, label="Bateria (solar armazenado)")
base2 = [a+b for a, b in zip(e_sol, e_bat)]
ax.bar(horas, e_red, bottom=base2, color=VERM, label="Rede eletrica")
ax.axvspan(17.5, 20.5, color="black", alpha=0.05)
ax.set_xlabel("Hora do dia"); ax.set_ylabel("Energia entregue (kWh)")
ax.set_xticks(range(0, 24, 2)); ax.grid(alpha=0.25, axis="y")
ax.legend(fontsize=8)
plt.title("De onde vem a energia que carrega o carro, hora a hora",
          color=AZUL, fontweight="bold")
plt.tight_layout(); plt.savefig("assets/grafico_fontes_energia.png", dpi=130); plt.close()

# Grafico 3: custo com x sem sistema + CO2
fig, (axa, axb) = plt.subplots(1, 2, figsize=(10, 4.2))
axa.bar(["Sem o sistema\n(tudo da rede)", "Com o sistema\n(eletroposto)"],
        [custo_sem_sistema, custo_rede], color=[VERM, VERDE])
axa.set_ylabel("Custo de energia no dia (R$)")
for i, v in enumerate([custo_sem_sistema, custo_rede]):
    axa.text(i, v+0.3, f"R$ {v:.2f}", ha="center", fontweight="bold")
axa.set_title(f"Economia de R$ {economia:.2f} no dia ({perc:.0f}%)",
              color=AZUL, fontweight="bold", fontsize=10)
axa.grid(alpha=0.2, axis="y")

axb.bar(["Energia\nrenovavel", "Energia\nda rede"], [ren, e_rede_total],
        color=[VERDE, VERM])
axb.set_ylabel("Energia no dia (kWh)")
for i, v in enumerate([ren, e_rede_total]):
    axb.text(i, v+0.3, f"{v:.1f} kWh", ha="center", fontweight="bold")
axb.set_title(f"{100*ren/tot:.0f}% da carga veio de fonte limpa\nCO2 evitado: {co2_evitado:.1f} kg",
              color=AZUL, fontweight="bold", fontsize=10)
axb.grid(alpha=0.2, axis="y")
plt.tight_layout(); plt.savefig("assets/grafico_custo_co2.png", dpi=130); plt.close()

print("\nArquivos gerados: dados_simulacao_24h.csv, resumo_simulacao.txt,")
print("assets/grafico_geracao_demanda.png, assets/grafico_fontes_energia.png, assets/grafico_custo_co2.png")
