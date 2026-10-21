"""Graficos estaticos (PNG) usados no README, no PDF e no video."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import config as C  # noqa: E402

COR = {  # cores fixas por entidade (nunca por posicao)
    "sem_sistema": "#8f8e88", "regra": "#eb6834", "inteligente": "#2a78d6", "otimo": "#6250d6",
    "solar": "#eda100", "bateria": "#1baf7a", "rede": "#e34948", "ev": "#2a78d6",
}
NOMES = {"sem_sistema": "Só rede", "regra": "Regra fixa (S2–S3)", "inteligente": "Inteligente (S4)"}
TXT, TXT2, GRADE, FUNDO = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRADE, "axes.labelcolor": TXT2,
    "xtick.color": TXT2, "ytick.color": TXT2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRADE, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "figure.facecolor": FUNDO, "axes.facecolor": FUNDO, "savefig.facecolor": FUNDO,
    "legend.frameon": False, "axes.titleweight": "bold", "axes.titlesize": 11, "axes.titlecolor": TXT,
})


def _barras(ax, titulo, valores, fmt, limite=None):
    chaves = list(NOMES)
    xs = range(len(chaves))
    barras = ax.bar(xs, [valores[k] for k in chaves], color=[COR[k] for k in chaves], width=0.6,
                    edgecolor=FUNDO, linewidth=2)
    for b, k in zip(barras, chaves):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), fmt(valores[k]),
                ha="center", va="bottom", fontsize=9, color=TXT)
    if limite:
        ax.axhline(limite, color=TXT2, ls="--", lw=1)
        ax.text(-0.45, limite + 0.3, f"limite contratado {limite:.0f} kW", va="bottom", ha="left", fontsize=8, color=TXT2)
    ax.set_xticks(list(xs), [NOMES[k].replace(" (", "\n(") for k in chaves], fontsize=8.5)
    ax.set_title(titulo, loc="left")
    ax.grid(axis="x", visible=False)


def comparativo(res, pasta):
    t = res["totais"]
    fig, axs = plt.subplots(1, 4, figsize=(14, 3.8))
    _barras(axs[0], "Custo líquido em 30 dias (R$)", {k: t[k]["custo_rs"] for k in NOMES},
            lambda v: f"R$ {v:,.0f}".replace(",", "."))
    _barras(axs[1], "Energia da rede na ponta (kWh)", {k: t[k]["rede_ponta_kwh"] for k in NOMES},
            lambda v: f"{v:.0f}")
    _barras(axs[2], "Pico de demanda da rede (kW)", {k: t[k]["pico_rede_kw"] for k in NOMES},
            lambda v: f"{v:.1f}", limite=C.LIMITE_REDE_KW)
    _barras(axs[3], "CO₂ marginal (kg, 30 dias)", {k: t[k]["co2_marginal_kg"] for k in NOMES},
            lambda v: f"{v:.0f}")
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "comparativo_30dias.png"), dpi=150)
    plt.close(fig)


def perfil_dia(res, pasta, nome_dia):
    fig, axs = plt.subplots(3, 1, figsize=(11, 8.2), sharex=True, gridspec_kw={"height_ratios": [3, 3, 1.6]})
    for ax, chave in zip(axs[:2], ["regra", "inteligente"]):
        p = res["estrategias"][chave]["passos_exemplo"][nome_dia]
        h = [x["hora"] for x in p]
        for x0, x1 in [(18, 21)]:
            ax.axvspan(x0, x1, color="#f3d9d6", alpha=0.45, lw=0)
        ax.fill_between(h, [x["solar_kw"] for x in p], step="post", color=COR["solar"], alpha=0.35,
                        lw=0, label="Geração solar")
        ax.step(h, [x["ev_kw"] for x in p], where="post", color=COR["ev"], lw=2, label="Recarga dos carros")
        ax.step(h, [x["rede_kw"] for x in p], where="post", color=COR["rede"], lw=2, label="Importação da rede")
        ax.step(h, [max(0, -x["bateria_kw"]) for x in p], where="post", color=COR["bateria"], lw=2,
                label="Descarga da bateria")
        ax.axhline(C.LIMITE_REDE_KW, color=TXT2, ls="--", lw=1)
        ax.set_ylabel("kW")
        ax.set_ylim(0, 24)
        ax.set_title(f"{NOMES[chave]} — dia {nome_dia}", loc="left")
        ax.text(19.5, 22.5, "ponta", ha="center", fontsize=8, color=TXT2)
    axs[0].legend(loc="upper left", ncol=4, fontsize=8)
    for chave in ["regra", "inteligente"]:
        p = res["estrategias"][chave]["passos_exemplo"][nome_dia]
        axs[2].plot([x["hora"] for x in p], [x["soc_pct"] for x in p], color=COR[chave], lw=2, label=NOMES[chave])
    axs[2].axvspan(18, 21, color="#f3d9d6", alpha=0.45, lw=0)
    axs[2].set_ylim(0, 100); axs[2].set_ylabel("%")
    axs[2].set_title("Carga da bateria (SoC)", loc="left")
    axs[2].legend(loc="upper left", fontsize=8, ncol=2)
    axs[2].set_xticks(range(0, 25, 2), [f"{x}h" for x in range(0, 25, 2)])
    axs[2].set_xlim(0, 24)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, f"perfil_dia_{nome_dia}.png"), dpi=150)
    plt.close(fig)


def custo_diario(res, pasta):
    fig, ax = plt.subplots(figsize=(11, 3.8))
    for k in NOMES:
        dias = res["estrategias"][k]["dias"]
        ax.plot([d["dia"] for d in dias], [d["custo_rs"] for d in dias], color=COR[k], lw=2,
                marker="o", ms=4, label=NOMES[k])
    dias = res["estrategias"]["inteligente"]["dias"]
    ax.plot([d["dia"] for d in dias], [d["custo_otimo_rs"] for d in dias], color=COR["otimo"], lw=1.5,
            ls="--", label="Ótimo teórico (sabe o futuro)")
    for d in dias:
        if d["tipo"].startswith("nublado"):
            ax.axvspan(d["dia"] - 0.5, d["dia"] + 0.5, color="#dfe6ef", alpha=0.6, lw=0)
    ax.set_title("Custo diário de energia (R$) — faixas cinza = dias nublados", loc="left")
    ax.set_xlabel("dia da simulação")
    ax.legend(ncol=4, fontsize=8, loc="upper left")
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "custo_diario.png"), dpi=150)
    plt.close(fig)


def gerar_graficos(res, pasta):
    os.makedirs(pasta, exist_ok=True)
    comparativo(res, pasta)
    for nome in res["dias_exemplo"]:
        perfil_dia(res, pasta, nome)
    custo_diario(res, pasta)
