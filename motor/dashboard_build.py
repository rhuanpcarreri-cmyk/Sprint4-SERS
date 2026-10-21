"""Injeta dados/resultados.json no template do dashboard -> dashboard/index.html (abre offline)."""
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gerar_dashboard():
    with open(os.path.join(RAIZ, "dados", "resultados.json"), encoding="utf-8") as f:
        dados = json.load(f)
    with open(os.path.join(RAIZ, "dashboard", "template.html"), encoding="utf-8") as f:
        html = f.read()
    js = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(RAIZ, "dashboard", "index.html"), "w", encoding="utf-8") as f:
        f.write(html.replace("__DADOS__", js))


if __name__ == "__main__":
    gerar_dashboard()
    print("dashboard/index.html gerado")
