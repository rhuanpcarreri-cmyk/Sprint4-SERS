/* ============================================================================
   ELETROPOSTO INTELIGENTE - EV Challenge 2026 (FIAP + GoodWe)
   Sprint 4 - Solucao final integrada  |  firmware v4
   ----------------------------------------------------------------------------
   Plataforma: ESP32 DevKit V1 (Wokwi)  |  Wi-Fi + MQTT (broker publico HiveMQ)

   O ESP32 faz o papel do controlador de borda (edge) que, na instalacao real,
   conversa com o inversor hibrido GoodWe GW10K-ET, a bateria Lynx Home F e o
   carregador GW11K-HCA. Ele roda o MESMO algoritmo inteligente do motor Python:

     1. SMART CHARGING por laxidade: o motorista informa a hora de saida; o
        controlador calcula a potencia MINIMA que garante a carga ate la e usa
        o resto da janela para seguir o sol e fugir da ponta.
     2. RESERVA DE PONTA: a bateria so e usada fora da ponta acima da reserva;
        das 18h as 21h ela assume a recarga.
     3. PEAK SHAVING: nunca importa mais que LIMITE_REDE_KW da rede.
     4. TELEMETRIA a cada 15 min simulados -> MQTT -> dashboard e assistente Volt.
     5. COMANDOS remotos via MQTT: modo, limite de demanda, previsao do tempo.

   CONTROLES (Wokwi)
     Pot SOL     (GPIO34): fator climatico 0-100%  (nuvens)
     Pot ENERGIA (GPIO35): energia pedida pelo motorista 5-40 kWh
     Pot SAIDA   (GPIO32): horas ate a saida 1-10 h
     Botao CARRO (GPIO25): conecta/desconecta o veiculo
     Botao PAUSA (GPIO26): congela o relogio (para explicar no video)
     Chave MODO  (GPIO27): INTELIGENTE / RAPIDO (regra fixa das sprints 2-3)
   SAIDAS
     LCD 16x2 I2C, LED verde (limpa), amarelo (bateria), vermelho (rede),
     buzzer (rede na ponta), Serial 115200 e MQTT.
   ============================================================================ */
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ---------------- rede ----------------
const char* WIFI_SSID   = "Wokwi-GUEST";
const char* WIFI_PASS   = "";
const char* MQTT_BROKER = "broker.hivemq.com";
const int   MQTT_PORT   = 1883;
const char* TOPICO_TELEM = "fiap/evchallenge/chargegrid/telemetria";
const char* TOPICO_CMD   = "fiap/evchallenge/chargegrid/comando";

WiFiClient wifi;
PubSubClient mqtt(wifi);
LiquidCrystal_I2C lcd(0x27, 16, 2);

// ---------------- pinos ----------------
const int PIN_POT_SOL = 34, PIN_POT_ENERGIA = 35, PIN_POT_SAIDA = 32;
const int PIN_BTN_CARRO = 25, PIN_BTN_PAUSA = 26, PIN_CHAVE_MODO = 27;
const int PIN_LED_VERDE = 4, PIN_LED_AMARELO = 5, PIN_LED_VERM = 2, PIN_BUZZER = 15;

// ---------------- parametros (iguais a motor/config.py) ----------------
const float DT = 0.25;                  // passo de 15 min
const float FV_PICO_KW = 10.0 * 0.75;   // 10 kWp x performance ratio
const float BAT_CAP = 13.1, BAT_P = 6.5, BAT_MIN = 1.31, EFIC = 0.96;
const float P_CARREGADOR = 11.0;        // GoodWe GW11K-HCA
const float T_FORA = 0.60, T_INTER = 0.85, T_PONTA = 1.20;
const float CO2_MEDIO = 0.0385;         // kgCO2/kWh SIN 2023 (MCTI)
float limiteRede = 15.0;                // ajustavel por MQTT
float reservaPonta = 8.0;               // kWh, ajustavel por MQTT (motor Python envia o valor aprendido)
float kPrevisto = 0.8;                  // indice de claridade previsto, ajustavel por MQTT
const unsigned long MS_POR_PASSO = 750; // 24 h simuladas = 72 s

// ---------------- estado ----------------
int passo = 32;                         // comeca as 8h
float soc = 5.2;
bool carro = false, pausado = false, modoRapido = false, forcarModoRemoto = false;
float restante = 0, saidaH = 0, pedido = 0;
float custoDia = 0, custoSemDia = 0, co2Dia = 0, renovDia = 0, totalDia = 0;
float solarKw = 0, evKw = 0, batKw = 0, redeKw = 0;
const char* fonte = "OCIOSO";
unsigned long tPasso = 0, tLcd = 0;
bool ultCarro = HIGH, ultPausa = HIGH;

float hora() { return passo * DT; }
float tarifa(float h) {
  if (h >= 18 && h < 21) return T_PONTA;
  if ((h >= 17 && h < 18) || (h >= 21 && h < 22)) return T_INTER;
  return T_FORA;
}
bool ponta(float h) { return h >= 18 && h < 21; }
float curvaSolar(float h) {
  if (h <= 5.9 || h >= 18.3) return 0;
  return pow(sin(PI * (h - 5.9) / 12.4), 1.2);
}
float pot(int pino) { return analogRead(pino) / 4095.0; }

// ---------------- algoritmo inteligente ----------------
// energia de rede planejada para AGORA: o que o sol previsto nao cobre ate a
// saida e alocado nos passos mais baratos (empate -> mais cedo)
float planoRede(float lim) {
  int ini = passo, fim = (int)(saidaH / DT);
  if (fim <= ini) return lim;
  float limpo = 0;
  for (int k = ini; k < fim; k++) limpo += min(lim * DT, FV_PICO_KW * kPrevisto * curvaSolar(k * DT) * DT);
  float falta = restante - limpo;
  if (falta <= 0.001) return 0;
  float tarifas[3] = {T_FORA, T_INTER, T_PONTA};
  for (int t = 0; t < 3; t++) {
    for (int k = ini; k < fim; k++) {
      if (tarifa(k * DT) != tarifas[t]) continue;
      float solarK = min(lim * DT, FV_PICO_KW * kPrevisto * curvaSolar(k * DT) * DT);
      float usa = min(lim * DT - solarK, falta);
      if (k == ini) return usa / DT;
      falta -= usa;
      if (falta <= 0.001) return 0;
    }
  }
  return 0;
}

float maxCarga()    { return max(0.0f, min(BAT_P, (BAT_CAP - soc) / EFIC / DT)); }
float maxDescarga(float piso) { return max(0.0f, min(BAT_P, (soc - max(piso, BAT_MIN)) * EFIC / DT)); }

void processarPasso() {
  float h = hora();
  solarKw = FV_PICO_KW * curvaSolar(h) * pot(PIN_POT_SOL);
  if (!forcarModoRemoto) modoRapido = digitalRead(PIN_CHAVE_MODO) == HIGH;

  // 1) potencia de recarga
  evKw = 0;
  if (carro && restante > 0.001) {
    float lim = min(P_CARREGADOR, restante / DT);
    if (modoRapido) {
      evKw = lim;                                       // regra fixa: carrega tudo ja
    } else {
      float passosRest = max(1.0f, (saidaH - h) / DT);
      float pMin = max(0.0f, restante - lim * DT * (passosRest - 1)) / DT;
      evKw = min(lim, max(pMin, planoRede(lim) + solarKw)); // garante + segue o sol
    }
  }

  // 2) bateria
  if (solarKw >= evKw) {
    batKw = min(solarKw - evKw, maxCarga());            // guarda o excedente solar
  } else {
    float deficit = evKw - solarKw;
    float piso = (modoRapido || ponta(h) || h >= 21) ? BAT_MIN : reservaPonta;
    batKw = -min(deficit, maxDescarga(piso));
  }

  // 3) peak shaving (so no modo inteligente)
  redeKw = evKw + batKw - solarKw;
  if (!modoRapido && redeKw > limiteRede) {
    float extra = min(redeKw - limiteRede, maxDescarga(BAT_MIN) + batKw);
    if (extra > 0) batKw -= extra;
    redeKw = evKw + batKw - solarKw;
    if (redeKw > limiteRede) { evKw -= (redeKw - limiteRede); redeKw = limiteRede; }
  }
  float exportKw = max(0.0f, -redeKw);
  redeKw = max(0.0f, redeKw);

  // 4) atualiza estado
  if (batKw > 0) soc += batKw * EFIC * DT; else soc += batKw / EFIC * DT;
  soc = constrain(soc, BAT_MIN, BAT_CAP);
  float e = evKw * DT;
  restante = max(0.0f, restante - e);
  float t = tarifa(h);
  custoDia += redeKw * DT * t;
  custoSemDia += e * t;
  float limpa = (evKw > 0) ? max(0.0f, e - redeKw * DT) : 0;
  renovDia += limpa; totalDia += e;
  co2Dia += limpa * CO2_MEDIO;

  fonte = evKw <= 0.01 ? (exportKw > 0.01 ? "EXPORTA" : "OCIOSO")
        : redeKw > 0.05 ? "REDE" : (batKw < -0.05 ? "BATERIA" : "SOLAR");
  if (redeKw > 0.05 && ponta(h)) tone(PIN_BUZZER, 1200, 120);
  if (carro && restante <= 0.001) carro = false;        // recarga concluida

  publicar(exportKw);
  passo = (passo + 1) % 96;
  if (passo == 0) { custoDia = custoSemDia = co2Dia = renovDia = totalDia = 0; }
}

// ---------------- MQTT ----------------
void publicar(float exportKw) {
  JsonDocument d;
  d["hora"] = hora();
  d["modo"] = modoRapido ? "rapido" : "inteligente";
  d["fonte"] = fonte;
  d["solar_kw"] = solarKw;  d["ev_kw"] = evKw;  d["bateria_kw"] = batKw;
  d["rede_kw"] = redeKw;    d["export_kw"] = exportKw;
  d["soc_pct"] = 100.0 * soc / BAT_CAP;
  d["carro"] = carro;       d["restante_kwh"] = restante; d["saida_h"] = saidaH;
  d["tarifa"] = tarifa(hora()); d["limite_kw"] = limiteRede;
  d["custo_dia"] = custoDia; d["economia_dia"] = custoSemDia - custoDia;
  d["pct_renovavel"] = totalDia > 0 ? 100.0 * renovDia / totalDia : 0;
  d["co2_evitado_kg"] = co2Dia;
  char buf[512];
  size_t n = serializeJson(d, buf);
  Serial.println(buf);
  if (mqtt.connected()) mqtt.publish(TOPICO_TELEM, buf, n);
}

void aoReceber(char* topico, byte* payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) return;
  if (!d["modo"].isNull()) { forcarModoRemoto = true; modoRapido = strcmp(d["modo"], "rapido") == 0; }
  if (!d["modo_local"].isNull()) forcarModoRemoto = false;
  if (!d["limite_kw"].isNull()) limiteRede = d["limite_kw"];
  if (!d["reserva_kwh"].isNull()) reservaPonta = d["reserva_kwh"];
  if (!d["k_previsto"].isNull()) kPrevisto = d["k_previsto"];
  if (!d["saida_h"].isNull() && carro) saidaH = d["saida_h"];
  Serial.println(F("[cmd] comando MQTT aplicado"));
}

void conectar() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connected()) return;
  String id = "chargegrid-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  if (mqtt.connect(id.c_str())) {
    mqtt.subscribe(TOPICO_CMD);
    Serial.println(F("[mqtt] conectado"));
  }
}

// ---------------- interface ----------------
void atualizarTela() {
  bool limpo = strcmp(fonte, "SOLAR") == 0 || strcmp(fonte, "BATERIA") == 0;
  digitalWrite(PIN_LED_VERDE, limpo);
  digitalWrite(PIN_LED_AMARELO, strcmp(fonte, "BATERIA") == 0);
  digitalWrite(PIN_LED_VERM, strcmp(fonte, "REDE") == 0);

  char l0[17], l1[17];
  int hh = (int)hora(), mm = (int)((hora() - hh) * 60);
  snprintf(l0, 17, "%02d:%02d%c%s %-7s", hh, mm, ponta(hora()) ? '*' : ' ',
           modoRapido ? "R" : "I", fonte);
  if (carro) snprintf(l1, 17, "B%3d%% %4.1fk>%02dh", (int)(100 * soc / BAT_CAP), restante, (int)saidaH);
  else       snprintf(l1, 17, "B%3d%% Eco R$%4.1f", (int)(100 * soc / BAT_CAP), custoSemDia - custoDia);
  lcd.setCursor(0, 0); lcd.print(l0);
  lcd.setCursor(0, 1); lcd.print(l1);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BTN_CARRO, INPUT_PULLUP);
  pinMode(PIN_BTN_PAUSA, INPUT_PULLUP);
  pinMode(PIN_CHAVE_MODO, INPUT_PULLUP);
  pinMode(PIN_LED_VERDE, OUTPUT); pinMode(PIN_LED_AMARELO, OUTPUT);
  pinMode(PIN_LED_VERM, OUTPUT);  pinMode(PIN_BUZZER, OUTPUT);
  lcd.init(); lcd.backlight();
  lcd.print(" CHARGEGRID v4"); lcd.setCursor(0, 1); lcd.print(" GoodWe + IA");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(aoReceber);
  mqtt.setBufferSize(600);
  delay(1500);
  lcd.clear();
}

void loop() {
  conectar();
  mqtt.loop();

  bool bc = digitalRead(PIN_BTN_CARRO);
  if (ultCarro == HIGH && bc == LOW) {
    carro = !carro;
    if (carro) {                                   // nova sessao de recarga
      pedido = 5 + 35 * pot(PIN_POT_ENERGIA);
      restante = pedido;
      saidaH = min(23.75f, hora() + 1 + 9 * pot(PIN_POT_SAIDA));
      Serial.printf("[sessao] %.1f kWh ate %.2fh\n", pedido, saidaH);
    }
    delay(40);
  }
  ultCarro = bc;
  bool bp = digitalRead(PIN_BTN_PAUSA);
  if (ultPausa == HIGH && bp == LOW) { pausado = !pausado; delay(40); }
  ultPausa = bp;

  if (!pausado && millis() - tPasso >= MS_POR_PASSO) { tPasso = millis(); processarPasso(); }
  if (millis() - tLcd >= 250) { tLcd = millis(); atualizarTela(); }
}
