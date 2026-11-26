# Handleiding: Qingping Air Monitor Lite (CGDN1) lokaal in Home Assistant

Deze handleiding gaat van een nieuwe of gereset apparaat tot een werkende, cloudvrije koppeling
met Home Assistant. Reken op 20 tot 30 minuten per apparaat, de eerste keer iets langer.

**Inhoud**

1. [Wat je nodig hebt](#1-wat-je-nodig-hebt)
2. [Hoe het werkt](#2-hoe-het-werkt)
3. [De MQTT-broker voorbereiden](#3-de-mqtt-broker-voorbereiden)
4. [Het apparaat naar je broker laten wijzen](#4-het-apparaat-naar-je-broker-laten-wijzen)
   - [4A. Via de Qingping developer portal](#4a-via-de-qingping-developer-portal)
   - [4B. Via Bluetooth (aanbevolen)](#4b-via-bluetooth-geen-account-geen-cloud-aanbevolen)
5. [Controleren of er berichten binnenkomen](#5-controleren-of-er-berichten-binnenkomen)
6. [De integratie installeren](#6-de-integratie-installeren)
7. [Het apparaat toevoegen](#7-het-apparaat-toevoegen)
8. [Instellen en gebruiken](#8-instellen-en-gebruiken)
9. [Temperatuurfilter](#9-temperatuurfilter)
10. [Database en logboek klein houden](#10-database-en-logboek-klein-houden)
11. [Privacy en beveiliging dichtzetten](#11-privacy-en-beveiliging-dichtzetten)
12. [Terug naar HomeKit of de Qingping-app](#12-terug-naar-homekit-of-de-qingping-app)
13. [Problemen oplossen](#13-problemen-oplossen)

---

## 1. Wat je nodig hebt

- Home Assistant **2026.2 of nieuwer**, met de **MQTT-integratie**.
- Een MQTT-broker. De officiële **Mosquitto broker**-add-on is prima.
- Een **Qingping Air Monitor Lite (CGDN1)** met de originele firmware 4.x. Getest met 4.8.5; je
  versie staat in de Qingping-app of later in Home Assistant.
- Eenmalig, voor de koppeling, een van deze twee:
  - **Route A:** een Qingping-account (app Qingping+ of Qingping IoT) en een pc met browser, **of**
  - **Route B:** Bluetooth in Home Assistant (adapter of ESPHome-proxy) óf een pc met Bluetooth
    (Windows, macOS of Linux).

> **Welke route kies ik?**
> Bij **route A** bewaart Qingping je broker-adres en het MQTT-wachtwoord van het apparaat op hun
> servers. **Route B** heeft geen account en geen cloud nodig, en is met Bluetooth in Home Assistant
> ook de makkelijkste route.

## 2. Hoe het werkt

Het apparaat stuurt zijn metingen als JSON naar `qingping/<MAC>/up` en luistert naar commando's op
`qingping/<MAC>/down`. `<MAC>` is het **wifi-MAC-adres** in hoofdletters, zonder dubbele punten,
bijvoorbeeld `7CC29400BEEF`.

De integratie:
- beantwoordt het verplichte "hallo"-bericht (type 10 → 11). Zonder dat antwoord stuurt het apparaat niets;
- vraagt elke paar seconden om realtime-metingen (type 12);
- bevestigt historische berichten (type 17 → 18);
- leest en schrijft de instellingen van het apparaat (type 28/17) en controleert elke wijziging.

Meer detail staat in [PROTOCOL.md](PROTOCOL.md) (Engels).

## 3. De MQTT-broker voorbereiden

### 3.1 Een aparte gebruiker voor de monitors

Geef de monitors hun **eigen** gebruiker. Gebruik niet de gebruiker van Home Assistant.

**Mosquitto-add-on:** Instellingen → Add-ons → Mosquitto broker → *Configuratie* → **Logins**:

```yaml
logins:
  - username: qingping
    password: "kies-een-lang-wachtwoord"
```

### 3.2 Rechten beperken (ACL)

Dit is belangrijker dan het lijkt. Het apparaat accepteert via het down-topic een opdracht om
**nieuwe firmware te installeren, zonder handtekeningcontrole**. Wie naar `qingping/<MAC>/down`
mag schrijven, kan het apparaat dus overnemen.

1. Zet in de Mosquitto-configuratie onder **Customize**:
   ```yaml
   customize:
     active: true
     folder: mosquitto
   ```
2. Maak in `/share/mosquitto/` twee bestanden. Voorbeelden staan in
   [`examples/mosquitto/`](../examples/mosquitto/):
   - `acl.conf` met:
     ```
     acl_file /share/mosquitto/accesscontrollist
     ```
   - `accesscontrollist` met:
     ```
     # Home Assistant (de gebruiker die de MQTT-integratie gebruikt)
     user homeassistant
     topic readwrite #

     # Qingping-monitors: alleen eigen up schrijven, down lezen
     user qingping
     topic write qingping/+/up
     topic read  qingping/+/down
     ```
     Pas `homeassistant` aan naar de gebruiker die jouw MQTT-integratie gebruikt. Geef andere
     gebruikers (Zigbee2MQTT, ESPHome en dergelijke) **geen** schrijfrecht op `qingping/#`.
3. Herstart de Mosquitto-add-on.

> Zet de broker **nooit** open naar het internet. Het apparaat praat MQTT zonder versleuteling.

## 4. Het apparaat naar je broker laten wijzen

### 4A. Via de Qingping developer portal

1. Installeer **Qingping+** of **Qingping IoT** en voeg de monitor toe. Krijg je hem niet gevonden,
   reset dan eerst het netwerk: houd de **balk bovenop ongeveer 8 seconden** ingedrukt tot er een
   groot wifi-icoon verschijnt.
2. Log met hetzelfde account in op <https://developer.qingping.co>. Gebruik een pc; de site werkt
   slecht op een telefoon.
3. Ga naar **Private Access Config → Configurations → Add Configuration**:
   | Veld | Waarde |
   |---|---|
   | Device model | Qingping Air Monitor Lite |
   | Private type | **Self-built MQTT** |
   | Host | het **LAN-IP** van je broker (bijv. `192.168.x.x`) |
   | Port | `1883` |
   | User name / Password | de gebruiker uit stap 3.1 |
   | Up topic | `qingping/{mac}/up` |
   | Down topic | `qingping/{mac}/down` |
4. Ga naar **Push Configuration** (of *Device*), kies je monitor en koppel de configuratie eraan.
5. Reset het netwerk van de monitor (balk 8 s) en stel wifi opnieuw in via de app. Bij het opnieuw
   verbinden haalt de monitor de MQTT-configuratie op. **Wacht ongeveer een minuut**; het eerste
   bericht komt niet meteen.
6. Ga door naar [stap 5](#5-controleren-of-er-berichten-binnenkomen).

### 4B. Via Bluetooth: geen account, geen cloud (aanbevolen)

Hierbij gaan je wifi- en MQTT-gegevens rechtstreeks via Bluetooth naar de monitor. Qingping krijgt
niets te zien. Het **wifi-MAC** voor de topics is het **Bluetooth-MAC min 2** (bevestigd op de CGDN1);
dat rekent de integratie of de tool zelf uit.

**Koppelmodus** is voor alle varianten gelijk: houd de **balk bovenop ongeveer 8 seconden** ingedrukt
tot het grote wifi-icoon verschijnt.

#### Variant 1: vanuit Home Assistant (het makkelijkst)

Nodig: Bluetooth in Home Assistant bij de monitor, dus een Bluetooth-adapter of een **ESPHome
Bluetooth-proxy met actieve verbindingen** (`bluetooth_proxy: active: true`).

1. Installeer eerst de integratie ([stap 6](#6-de-integratie-installeren)) en zet de monitor in koppelmodus.
2. Onder Instellingen → Apparaten & diensten verschijnt **"Ontdekt: Qingping …"** → *Instellen via Bluetooth*.
3. Vul in:
   | Veld | Waarde |
   |---|---|
   | Wifi-netwerk / -wachtwoord | je 2,4 GHz-netwerk (bij voorkeur het IoT-netwerk) |
   | MQTT-broker (LAN-IP) | het IP van Home Assistant/Mosquitto, al voor-ingevuld |
   | MQTT-poort | `1883` |
   | MQTT-gebruiker / -wachtwoord | de aparte gebruiker uit stap 3.1 |
4. Home Assistant schrijft de gegevens via Bluetooth, wacht tot de monitor publiceert (maximaal 2
   minuten) en voegt hem toe. Klaar; stap 5 tot en met 7 kun je overslaan.

> De wachtwoorden worden alleen tijdens deze wizard gebruikt. Ze worden niet opgeslagen en niet
> gelogd. Daarom is dit bewust geen *action*: de data van een action komt als `call_service`-event in
> de database terecht, en dan zouden de wachtwoorden leesbaar in `home-assistant_v2.db` staan.

**Lukt het niet?** Bij "monitor niet bereikbaar" staat er geen verbindbare Bluetooth-adapter of
proxy dicht genoeg bij, of de monitor staat niet meer in koppelmodus (die vervalt na een tijdje).
Bij "nog geen bericht" kloppen meestal het wifi-wachtwoord, het IP of de ACL niet.

#### Variant 2: vanaf een pc met Windows, macOS of Linux

Gebruik [`tools/qingping-provision`](../tools/qingping-provision/README.md).

1. **Windows:** installeer Python 3.11+ van python.org (vink *Add python.exe to PATH* aan) en zet Bluetooth aan.
2. Installeren (PowerShell, in de repo-map):
   ```powershell
   cd tools\qingping-provision
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Monitor in koppelmodus, dan zoeken:
   ```powershell
   python qingping_provision.py scan
   ```
   Je ziet het Bluetooth-adres en het berekende wifi-MAC.
4. Schrijven (de wachtwoorden worden gevraagd zonder dat ze op het scherm verschijnen):
   ```powershell
   python qingping_provision.py provision --address 7C:C2:94:00:BE:F1 `
       --ssid MijnIoTNetwerk --mqtt-host 192.168.x.x --mqtt-user qingping
   ```
   Met `--dry-run` controleer je eerst wat er geschreven zou worden.
5. Na ongeveer een minuut verschijnt de monitor in Home Assistant onder *Ontdekt*.

Op macOS toont Bluetooth geen MAC-adres maar een UUID. Geef dan `--wifi-mac` op, of laat de
monitor het zelf vertellen met `--read-wifi-mac`.

#### Variant 3: de originele Linux-tool

[`tools/qingping-ble-setup`](../tools/qingping-ble-setup/README.md) bevat de oorspronkelijke tool
van bitrate16 (AGPL-3.0, ongewijzigd). Die heeft Linux met `gatttool` nodig. Gebruik bij voorkeur
variant 1 of 2.

**Beperkingen voor alle varianten:** geen spaties in MQTT-host, -gebruiker of -wachtwoord en geen
`"` in de wifi-naam of het wifi-wachtwoord, want het instelprotocol scheidt velden met spaties en
aanhalingstekens. TLS kan het protocol niet instellen.

## 5. Controleren of er berichten binnenkomen

Instellingen → Apparaten & diensten → **MQTT** → *Configureren* → **Luisteren naar een topic** →
`qingping/#` → *Begin met luisteren*.

Binnen een minuut hoort een bericht als dit te verschijnen:

```json
{"type": "13", "wifi_mac": "7CC29400BEEF", "sw_version": "4.8.5", ...}
```

| Wat je ziet | Betekenis |
|---|---|
| Niets | De monitor bereikt de broker niet: verkeerd IP, gebruiker of wachtwoord, of geen wifi. Kijk in het log van de Mosquitto-add-on. |
| `Not authorized` in het Mosquitto-log | De ACL klopt niet (stap 3.2). |
| Type 10 dat steeds terugkomt | Normaal zolang de integratie nog niet draait; die beantwoordt het. |

## 6. De integratie installeren

**Via HACS:** HACS → ⋮ → *Aangepaste repositories* → URL van deze repo, categorie *Integratie* →
zoek **QingPing CGDN1** → *Downloaden* → herstart Home Assistant.

**Handmatig:** kopieer de map `custom_components/qingping_cgdn1` naar `config/custom_components/`
en herstart Home Assistant.

## 7. Het apparaat toevoegen

- **Automatisch:** onder Instellingen → Apparaten & diensten verschijnt **"Ontdekt: Qingping Air
  Monitor Lite"**. Klik op *Toevoegen* en geef hem een naam, bijv. "Woonkamer".
- **Handmatig:** *Integratie toevoegen* → **QingPing CGDN1**. De integratie luistert 10 seconden
  en toont de monitors die hij hoort. Anders vul je het MAC uit het topic in.

Na een paar seconden lopen temperatuur, vocht, CO₂ en PM binnen. In de eerste minuut stelt de
integratie ook de klok, de tijdzone en het interval van de geschiedenis in.

## 8. Instellen en gebruiken

Op de apparaatpagina vind je drie groepen:

**Sensoren:** temperatuur (gefilterd), vocht, CO₂, PM2.5, PM10. "Temperatuur ongefilterd" staat
standaard uit.

**Configuratie** (wordt naar het apparaat geschreven en teruggelezen):

| Entiteit | Toelichting |
|---|---|
| Verversingsinterval | Hoe vaak realtime-metingen binnenkomen, 5–120 s (standaard 15 s) |
| Temperatuur-/vocht-/CO₂-/PM-offset | Correctie in eenheden; bij temperatuur en CO₂ ook in procenten |
| Schermweergave | Wisselend, huidige meting, klok + wisselend, klok + huidige |
| Nachtmodus start/einde | Scherm gedimd of uit in dit venster |
| Automatisch uitschakelen | Alleen op batterij, 0 = nooit |
| Klokweergave, Temperatuureenheid scherm | 24/12 uur, °C/°F |
| CO2 automatische kalibratie (ASC) | Laat aan, tenzij de monitor nooit buitenlucht ziet |
| Tijdzone | Wordt automatisch bijgehouden, inclusief zomertijd |
| PM-/CO₂-meetinterval | Standaard uit; eenheid niet gedocumenteerd, alleen voor experimenten |

> "Scherm uit na" doet op recente firmware niets; Qingping-support noemt die instelling zelf nutteloos.

**Diagnose:** status (online/offline), batterij en laadstatus, firmware, wifi-signaal, laatst gezien,
sensorstatus, CO₂-kalibratiestatus.

## 9. Temperatuurfilter

De CGDN1 corrigeert zijn temperatuur voor de eigen warmte van scherm, wifi en laden. Als die
correctie omschakelt, **springt** de temperatuur binnen seconden een graad of meer. Het filter:

1. vangt sprongen van **≥ 1,0 °C binnen 120 s** op in een *correctie* (maximaal ±5 °C) en maakt een
   melding onder *Reparaties*;
2. negeert uitschieters van meer dan 0,5 °C ten opzichte van de mediaan van de laatste 6 metingen;
3. dempt licht (ongeveer 4 metingen).

Was de waarde **na** de sprong eigenlijk de juiste? Open dan de melding onder Reparaties en vink
*Correctie op 0 zetten* aan, of zet de entiteit *Temperatuur-sprongcorrectie* op 0.

## 10. Database en logboek klein houden

Aanbevolen in `configuration.yaml`; een volledig voorbeeld staat in
[`examples/recorder.yaml`](../examples/recorder.yaml):

**"Laatst gezien" zonder logboekspam.** Een tijdstempel die bij elk bericht verandert, geeft bij
elk bericht een regel in *Activiteit*. Een `logbook: exclude` helpt daar niet tegen: op de
apparaatpagina past Home Assistant die filter bewust niet toe. Daarom:

- wordt de **Status**-sensor bij elk bericht opnieuw gemeld zonder dat de waarde verandert. HA werkt
  dan alleen `last_reported` bij: geen event, geen logboekregel, geen extra databaserij;
- staat de sensor **Last seen standaard uit**. Bij een update vanaf 2.1 of ouder zet de integratie
  hem eenmalig uit. Je mag hem weer aanzetten, maar dan krijg je per bericht een logboekregel.

Laatste bericht op je dashboard (Markdown-kaart):

```yaml
type: markdown
content: >-
  Laatste bericht: {{ relative_time(states.sensor.woonkamer_status.last_reported) }} geleden
```

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.*_last_seen
      - sensor.*_extra_data
      - sensor.*_report_type
```

## 11. Privacy en beveiliging dichtzetten

Na de koppeling heeft het apparaat **geen internet** meer nodig. De volledige analyse staat in
[PRIVACY.md](PRIVACY.md) (Engels). In het kort:

0. **TLS of HTTPS?** Lokaal niet mogelijk: het instelprotocol kent geen TLS-optie, en de
   HTTPS-push van Qingping loopt via hun cloud. Afscherming via het netwerk is daarom de echte beveiliging.
1. **Zet de monitors in een IoT-VLAN of gastnetwerk** zonder toegang tot de rest van je netwerk,
   behalve MQTT (TCP 1883) naar je broker.
2. **Blokkeer internet** voor de monitors in je router of firewall. Laat je DNS de domeinen
   `*.cleargrass.com`, `*.qingping.co` en `*.mi.com` lokaal beantwoorden (bijvoorbeeld met
   `0.0.0.0`) in plaats van te laten verlopen; anders blijft het apparaat DNS-verzoeken sturen.
3. **ACL op de broker** zoals in stap 3.2: alleen Home Assistant mag naar `qingping/+/down` schrijven.
4. **Firmware-updates:** wil je updaten, zet internet dan tijdelijk open, update via de app en sluit
   daarna weer af. Let op: via route B heb je geen app-koppeling.
5. De integratie bewaart **geen SSID, BSSID of HomeKit-salt**, ook al stuurt het apparaat die mee.

## 12. Terug naar HomeKit of de Qingping-app

HomeKit is geen schakelaar maar een **andere manier van koppelen**. Portal, MQTT en de
Bluetooth-tool kunnen HomeKit dus niet aanzetten.

- **Naar HomeKit:** reset het netwerk (balk 8 s), voeg de monitor toe in de **Woning**-app (of in HA
  met *HomeKit Device*) met de code op het apparaat.
- **Naar de Qingping-app:** reset het netwerk en voeg hem toe in Qingping+ of Qingping IoT.
- **Helemaal opnieuw:** fabrieksreset volgens de handleiding van Qingping.

Verwijder daarna de oude invoer van deze integratie, anders blijft de melding "offline" staan.

## 13. Problemen oplossen

| Probleem | Oplossing |
|---|---|
| Niets ontdekt | Stap 5: komen er berichten binnen op `qingping/#`? |
| Berichten komen binnen, entiteiten blijven "niet beschikbaar" | De HA-gebruiker mag niet naar `qingping/+/down` schrijven, dus het type-11-antwoord komt niet aan. Controleer de ACL. |
| Maar één update per 15 minuten | Zelfde oorzaak: het realtime-verzoek komt niet aan. |
| Instelling springt terug | Download de diagnostiek: onder `settings.raw` staat wat het apparaat zelf meldt. Sommige keys negeert de firmware. |
| Klok of nachtmodus klopt niet | Controleer de tijdzone van Home Assistant; de integratie neemt die over. |
| "Offline" na een herstart | Normaal tot het eerste bericht; verdwijnt vanzelf. |
| Temperatuur maakt rare sprongen | Het filter vangt ze op; zie stap 9. Vergelijk met "Temperatuur ongefilterd". |

**Debug-logging aanzetten:**

```yaml
logger:
  logs:
    custom_components.qingping_cgdn1: debug
```

Voeg bij een issue altijd de **diagnostiek** toe: Instellingen → Apparaten → je monitor → ⋮ →
*Diagnostiek downloaden*. Daar zijn wachtwoorden, HomeKit-salt, SSID en BSSID al uit verwijderd.
