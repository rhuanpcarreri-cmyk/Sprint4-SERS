# Roteiro do vídeo técnico — Sprint 4 (até 5 minutos)

Grave a tela mostrando o dashboard e o Wokwi lado a lado (ou em cortes), narrando os pontos abaixo. Marcações de tempo são sugestões, não regra fixa.

## 0:00–0:30 — Abertura
"Este é o ChargeGrid, o eletroposto inteligente do nosso grupo para o EV Challenge 2026, em parceria com a GoodWe. Nas sprints anteriores provamos que o sistema decide entre solar, bateria e rede, e que integra isso a sessões de recarga completas. Nesta sprint final, trocamos a regra fixa por um algoritmo de controle preditivo e testamos contra 30 dias simulados, contra o sistema antigo e contra um ótimo teórico que conhece o futuro."

## 0:30–1:30 — O problema que a regra fixa não resolvia
Mostrar a tabela comparativa no dashboard (aba "Resultados 30 dias").
"A regra das Sprints 2 e 3 funciona, mas carrega cada carro na potência máxima assim que ele chega. Em 15 dos 30 dias simulados, isso estourou a demanda contratada de 15 kW — na vida real, isso é multa ou disjuntor desarmando. O algoritmo inteligente nunca estourou, porque o controle de demanda é parte da decisão, não um ajuste manual depois."

## 1:30–2:45 — Como o algoritmo decide (aba "Um dia por dentro")
Mostrar o gráfico do dia nublado comparando Regra fixa x Inteligente.
"Aqui comparamos o mesmo dia nublado nas duas estratégias. A regra fixa carrega tudo de uma vez e descarrega a bateria cedo, sem reserva pra ponta. O algoritmo inteligente, sabendo pela previsão que o dia seria fraco em sol, pré-carregou a bateria de madrugada com energia barata, e guardou o suficiente pra cobrir o horário de ponta das 18h às 21h — vejam a curva de carga da bateria aqui embaixo. Isso é aprendido: a cada dia, o sistema reajusta quanta reserva precisa, com base no consumo real observado, não um número fixo no código."

## 2:45–3:30 — Protótipo no Wokwi (hardware real)
Trocar para a aba do Wokwi, protótipo rodando.
"O mesmo algoritmo roda embarcado num ESP32. Aqui simulamos nuvens no potenciômetro de sol, conectamos um carro e definimos a hora de saída. O firmware publica os dados por MQTT em tempo real — e esse mesmo canal alimenta a aba 'Ao vivo' do dashboard."
Mostrar o LCD trocando entre fontes (solar/bateria/rede) e o dashboard recebendo a telemetria ao vivo (aba "Ao vivo").

## 3:30–4:15 — Assistente virtual e viabilidade
"Também criamos o Volt, um assistente que responde perguntas usando os mesmos dados — por exemplo, 'qual o pico de demanda?' ou 'qual o payback do investimento?'." (fazer 1-2 perguntas ao vivo no chat do dashboard)
"Em 30 dias, o sistema inteligente economiza R$ 852 frente a não ter sistema nenhum, e captura 93% da economia que seria possível com informação perfeita do futuro — mostrado aqui no gráfico de custo diário, comparado à linha tracejada do ótimo teórico."

## 4:15–5:00 — Fechamento
"Essa é a nossa solução final: um algoritmo que não só segue solar, bateria e rede na ordem certa, mas decide quando usar cada um, aprende com o uso, respeita o limite de demanda, e conversa com quem opera o eletroposto. Repositório completo, com testes automatizados do algoritmo, no GitHub. Obrigado!"

---

### Checklist antes de gravar
- [ ] Rodar `python -m motor.simulador` para garantir que os dados estão atualizados
- [ ] Abrir `dashboard/index.html` e testar as 4 abas
- [ ] Abrir o projeto no Wokwi, iniciar a simulação, testar os botões CARRO/PAUSA e a chave MODO
- [ ] Testar 2-3 perguntas no assistente Volt (no dashboard, sem precisar do Telegram)
- [ ] Vídeo não listado no YouTube, link colado no `entrega.txt`
