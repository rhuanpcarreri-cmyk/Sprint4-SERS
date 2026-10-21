/* ============================================================================
   ELETROPOSTO INTELIGENTE  -  EV Challenge 2026  (ecossistema GoodWe)
   Prova de Conceito Funcional - Sprint 2
   ----------------------------------------------------------------------------
   Plataforma : ESP32 DevKit V1  (simulado no Wokwi)
   Objetivo   : gerenciar a recarga de um veiculo eletrico decidindo, em tempo
                real, de qual fonte puxar energia, na prioridade:
                       SOLAR  ->  BATERIA (BESS)  ->  REDE
                reduzindo custo (evita rede na PONTA) e emissoes de CO2.

   Energias renovaveis e sustentabilidade:
     - A geracao fotovoltaica e a fonte primaria.
     - A bateria so e carregada pelo EXCEDENTE solar (energia limpa armazenada).
     - A rede convencional e o ultimo recurso, evitado sobretudo na ponta.

   CONTROLES NO WOKWI
     - Potenciometro SOLAR  (GPIO34): fator climatico 0-100% (simula nuvens).
       A geracao real = curva do horario x esse fator.
     - Potenciometro DEMANDA(GPIO35): quanta potencia o carro pede (0-100%).
     - Botao CARRO        (GPIO25): conecta/desconecta o veiculo.
     - Botao PAUSA        (GPIO26): pausa/retoma o avanco do relogio simulado.

   SAIDAS
     - LCD 16x2 I2C  : modo/fonte, geracao, SoC da bateria, custo evitado.
     - LED verde (GPIO4) : energia limpa (SOLAR ou BATERIA).
     - LED amarelo(GPIO5): bateria assumindo o deficit.
     - LED vermelho(GPIO2): puxando da REDE.
     - Buzzer (GPIO15)   : alerta curto ao recorrer a rede em horario de PONTA.
     - Serial (115200)   : log hora a hora (gera o dataset da prova de conceito).
   ============================================================================ */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

LiquidCrystal_I2C lcd(0x27, 16, 2);

// -------------------- PINOS --------------------
const int PIN_POT_SOLAR   = 34;
const int PIN_POT_DEMANDA = 35;
const int PIN_BTN_CARRO   = 25;
const int PIN_BTN_PAUSA   = 26;
const int PIN_LED_VERDE   = 4;
const int PIN_LED_AMARELO = 5;
const int PIN_LED_VERM    = 2;
const int PIN_BUZZER      = 15;

// -------------------- PARAMETROS DO SISTEMA (iguais a simulacao Python) -----
const float SOLAR_MAX_KW      = 10.0;   // pico do arranjo fotovoltaico
const float CARREGADOR_MAX_KW = 7.4;    // potencia maxima do carregador EV
const float BAT_CAP_KWH       = 15.0;   // capacidade do banco BESS
const float SOC_MIN_KWH       = 1.5;    // reserva minima (~10%)
const float TARIFA_PONTA      = 1.20;   // R$/kWh na ponta
const float TARIFA_FORA       = 0.60;   // R$/kWh fora de ponta
const float FATOR_CO2_REDE    = 0.12;   // kgCO2/kWh da rede (ilustrativo)

// avanco do relogio simulado: 1 hora a cada N milissegundos
const unsigned long MS_POR_HORA = 3000;   // 24h = 72s (cabe no video de 5 min)

// -------------------- ESTADO --------------------
float socKwh        = 4.0;   // carga inicial da bateria
int   horaSim       = 0;     // 0..23
bool  carroConect   = false;
bool  pausado       = false;

// acumuladores do dia
float custoRede = 0, custoSem = 0, co2Evitado = 0;
float eSolarTot = 0, eBatTot = 0, eRedeTot = 0;

unsigned long tHora = 0, tLcd = 0;
bool ultBtnCarro = HIGH, ultBtnPausa = HIGH;

// fonte atual (para LCD/LED)
enum Fonte { OCIOSO, SOLAR, BATERIA, REDE };
Fonte fonteAtual = OCIOSO;
float geracaoAtual = 0, demandaAtual = 0;

// -------------------- FUNCOES AUXILIARES --------------------
float curvaSolar(int h) {        // geracao normalizada 0..1, pico ao meio-dia
  if (h < 6 || h > 18) return 0.0;
  float x = (h - 6) / 12.0;
  return sin(x * PI);
}
bool ehPonta(int h) { return (h >= 18 && h < 21); }
float tarifa(int h) { return ehPonta(h) ? TARIFA_PONTA : TARIFA_FORA; }

// le potenciometro como percentual 0.0..1.0
float potPerc(int pino) { return analogRead(pino) / 4095.0; }

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BTN_CARRO, INPUT_PULLUP);
  pinMode(PIN_BTN_PAUSA, INPUT_PULLUP);
  pinMode(PIN_LED_VERDE, OUTPUT);
  pinMode(PIN_LED_AMARELO, OUTPUT);
  pinMode(PIN_LED_VERM, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  Wire.begin();
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0); lcd.print(" ELETROPOSTO");
  lcd.setCursor(0, 1); lcd.print(" INTELIGENTE");
  delay(1800);
  lcd.clear();

  Serial.println(F("hora;geracao_kw;demanda_kw;fonte;soc_pct;e_solar;e_bateria;e_rede;tarifa;periodo"));
}

// processa UMA hora simulada: balanco de energia + contabilidade + log
void processarHora() {
  float geracao = SOLAR_MAX_KW * curvaSolar(horaSim) * potPerc(PIN_POT_SOLAR);
  float demanda = carroConect ? (CARREGADOR_MAX_KW * potPerc(PIN_POT_DEMANDA)) : 0.0;
  float t = tarifa(horaSim);

  float eSolar = 0, eBat = 0, eRede = 0;
  Fonte fonte = OCIOSO;

  if (demanda <= 0.001) {                 // sem carro: excedente carrega bateria
    if (geracao > 0) {
      float carga = min(geracao, BAT_CAP_KWH - socKwh);
      socKwh += carga;
    }
  } else {
    if (geracao >= demanda) {             // solar cobre tudo
      fonte  = SOLAR;
      eSolar = demanda;
      float exc = geracao - demanda;
      float carga = min(exc, BAT_CAP_KWH - socKwh);
      socKwh += carga;
    } else {                              // solar parcial + completa
      eSolar = geracao;
      float deficit = demanda - geracao;
      float dispBat = max(0.0f, socKwh - SOC_MIN_KWH);
      if (dispBat > 0) {
        eBat = min(deficit, dispBat);
        socKwh -= eBat;
        deficit -= eBat;
        fonte = BATERIA;
      }
      if (deficit > 0.001) {              // ultimo recurso: rede
        eRede = deficit;
        fonte = REDE;
        if (ehPonta(horaSim)) {           // alerta: rede na ponta
          tone(PIN_BUZZER, 1200, 120);
        }
      }
    }
  }

  // contabilidade do dia
  custoRede  += eRede * t;
  custoSem   += demanda * t;              // cenario sem solar/bateria
  co2Evitado += (eSolar + eBat) * FATOR_CO2_REDE;
  eSolarTot  += eSolar;  eBatTot += eBat;  eRedeTot += eRede;

  fonteAtual = fonte; geracaoAtual = geracao; demandaAtual = demanda;

  // log serial (dataset)
  Serial.print(horaSim); Serial.print(":00;");
  Serial.print(geracao, 2); Serial.print(';');
  Serial.print(demanda, 2); Serial.print(';');
  Serial.print(fonte == SOLAR ? "SOLAR" : fonte == BATERIA ? "BATERIA" :
               fonte == REDE ? "REDE" : "OCIOSO"); Serial.print(';');
  Serial.print(100.0 * socKwh / BAT_CAP_KWH, 1); Serial.print(';');
  Serial.print(eSolar, 2); Serial.print(';');
  Serial.print(eBat, 2);   Serial.print(';');
  Serial.print(eRede, 2);  Serial.print(';');
  Serial.print(t, 2);      Serial.print(';');
  Serial.println(ehPonta(horaSim) ? "PONTA" : "fora");

  horaSim = (horaSim + 1) % 24;
  if (horaSim == 0) {                     // fim do ciclo: imprime resumo e zera
    float ren = eSolarTot + eBatTot;
    float tot = ren + eRedeTot;
    float economia = custoSem - custoRede;
    Serial.println(F("----- RESUMO 24h -----"));
    Serial.print(F("Renovavel %: ")); Serial.println(tot > 0 ? 100.0 * ren / tot : 0, 1);
    Serial.print(F("Economia R$: ")); Serial.println(economia, 2);
    Serial.print(F("CO2 evitado kg: ")); Serial.println(co2Evitado, 2);
    Serial.println(F("----------------------"));
    custoRede = custoSem = co2Evitado = 0;
    eSolarTot = eBatTot = eRedeTot = 0;
  }
}

void atualizarSaidas() {
  // LEDs por fonte
  digitalWrite(PIN_LED_VERDE,   fonteAtual == SOLAR || fonteAtual == BATERIA);
  digitalWrite(PIN_LED_AMARELO, fonteAtual == BATERIA);
  digitalWrite(PIN_LED_VERM,    fonteAtual == REDE);

  const char* nome = fonteAtual == SOLAR ? "SOLAR  " :
                     fonteAtual == BATERIA ? "BATERIA" :
                     fonteAtual == REDE ? "REDE   " : "OCIOSO ";

  lcd.setCursor(0, 0);
  char l0[17];
  snprintf(l0, sizeof(l0), "%02dh %s%s", horaSim,
           ehPonta(horaSim) ? "*" : " ", nome);
  lcd.print(l0); lcd.print("   ");

  lcd.setCursor(0, 1);
  char l1[17];
  float economia = custoSem - custoRede;
  snprintf(l1, sizeof(l1), "B%3d%% Eco R$%4.1f",
           (int)(100.0 * socKwh / BAT_CAP_KWH), economia);
  lcd.print(l1); lcd.print("  ");
}

void loop() {
  // botao CARRO (borda de descida)
  bool bc = digitalRead(PIN_BTN_CARRO);
  if (ultBtnCarro == HIGH && bc == LOW) { carroConect = !carroConect; delay(40); }
  ultBtnCarro = bc;

  // botao PAUSA
  bool bp = digitalRead(PIN_BTN_PAUSA);
  if (ultBtnPausa == HIGH && bp == LOW) { pausado = !pausado; delay(40); }
  ultBtnPausa = bp;

  // avanca o relogio simulado
  if (!pausado && millis() - tHora >= MS_POR_HORA) {
    tHora = millis();
    processarHora();
  }

  // atualiza LCD/LEDs ~4x por segundo
  if (millis() - tLcd >= 250) {
    tLcd = millis();
    atualizarSaidas();
  }
}
