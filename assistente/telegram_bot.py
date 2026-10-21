"""
Bot do Telegram para o assistente Volt (sem dependencias externas).

1. Crie um bot com o @BotFather e copie o token.
2. export TELEGRAM_TOKEN="123:ABC..."   (Windows: set TELEGRAM_TOKEN=...)
3. python -m assistente.telegram_bot

Opcional: com `pip install paho-mqtt`, o bot assina o topico de telemetria do
ESP32 e responde "status" com os dados ao vivo do prototipo no Wokwi.
"""
import json
import os
import time
import urllib.parse
import urllib.request

from .assistente import Assistente

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"
BROKER, TOPICO = "broker.hivemq.com", "fiap/evchallenge/chargegrid/telemetria"


def _chamar(metodo, **params):
    dados = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"{API}/{metodo}", data=dados, timeout=40) as r:
        return json.load(r)


def _ligar_mqtt(assistente):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("(paho-mqtt nao instalado: status ao vivo desativado)")
        return
    cli = mqtt.Client()
    cli.on_message = lambda c, u, m: assistente.telemetria.update(json.loads(m.payload))
    cli.connect(BROKER, 1883, 60)
    cli.subscribe(TOPICO)
    cli.loop_start()
    print(f"Assinando {TOPICO} em {BROKER}")


def main():
    if not TOKEN:
        raise SystemExit("Defina a variavel de ambiente TELEGRAM_TOKEN.")
    volt = Assistente()
    _ligar_mqtt(volt)
    offset = 0
    print("Bot Volt no ar. Ctrl+C para sair.")
    while True:
        try:
            upd = _chamar("getUpdates", offset=offset, timeout=30)
            for u in upd.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                texto = msg.get("text")
                if texto:
                    _chamar("sendMessage", chat_id=msg["chat"]["id"], text=volt.responder(texto))
        except Exception as e:  # rede instavel: tenta de novo
            print("erro:", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
