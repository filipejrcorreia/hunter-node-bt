# Hunter NODE-BT — Relatório de Engenharia Reversa (handoff)

**Objetivo final:** criar uma integração Home Assistant (HACS, custom component em Python) que
comunique com um controlador de rega **Hunter NODE-BT** por BLE, da mesma forma que a app oficial.

**Estado:** protocolo BLE essencialmente **todo mapeado** por decompilação estática da app oficial.
Falta validar com captura BLE real e escrever o componente Python. Este documento tem tudo o que o
próximo agente (Gemini) precisa para continuar **sem repetir o trabalho**.

Data: 2026-10-21. Autor da análise: sessão Claude Code (Opus).

---

## 1. Resumo executivo do protocolo

- **Transporte de comandos:** Nordic UART Service (NUS). Comandos são **objetos JSON** serializados
  (Newtonsoft), enviados em **chunks de 20 bytes** por *write-without-response*. As respostas chegam
  por **notificações**, são **JSON terminado em `\0`** e reassembladas até ao `\0`.
- **Autenticação:** serviço PIN separado, com handshake binário **challenge-response** e cifra XOR.
  O PIN é um número u16 (default `0`). **É preciso autenticar antes de enviar comandos.**
- **Chip:** Texas Instruments (UUIDs `f000xxxx-0451-4000-b000-...` presentes → família CC254x/CC264x).
  Serviços de firmware/OTA existem mas **não são precisos** para a integração.

---

## 2. Mapa GATT (de `NodeV2.Service.Interface` → classe `BleGuids`)

| Nome | UUID | Uso |
|---|---|---|
| **MessageService** (NUS) | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | serviço de comandos |
| **MessageRequestCharacteristic** (NUS RX) | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | **write** (app→device), chunks 20B |
| **MessageResponseCharacteristic** (NUS TX) | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | **notify** (device→app), JSON+`\0` |
| **PinService** | `0ed3e3d3-8cd8-4f29-8fec-a7d3a2c5443e` | autenticação |
| **PinServiceCharacteristic** | `4c9dbe52-3566-4dfc-a299-4ea1353970e2` | **write + notify** (handshake PIN) |
| ControllerFirmwareService | `0031f62c-b837-11e7-abc4-cec278b6b50a` | (firmware — ignorar) |
| ControllerFirmwareRequest/Response | `6d9e1460-...` / `41a87e7b-...` | (firmware — ignorar) |
| BootloaderFirmwareService | `3595f2c9-f57c-429c-ae01-185ef51d4020` | (firmware — ignorar) |
| BootloaderFirmwareRequest/Response | `639b5b38-...` / `04498679-...` | (firmware — ignorar) |
| BluetoothOtaFirmwareService | `1D14D6EE-FD63-4FA1-BFA4-8F47B42119F0` | (OTA — ignorar) |
| BluetoothOtaControl / Data | `F7BF3564-...` / `984227F3-...` | (OTA — ignorar) |
| CCCD (descriptor standard) | `00002902-0000-1000-8000-00805f9b34fb` | ativar notificações |

**Descoberta/advertising:** o scan filtra por `ServiceUuids = [MessageService]` e compara o
*advertised name* com o nome do device. Procurar por anúncios que exponham o NUS `6e400001...`.

---

## 3. Autenticação por PIN (crítico) — de `BleDeviceCommunication`

Struct do pacote (little-endian, 6 bytes):

```
DevicePinInfo {
  byte   packetType
  byte   result
  uint16 randomNumber   // LE
  uint16 pin            // LE
}
```

Cifras (exatas, copiar tal e qual):

```python
def message_xor(buf: bytes) -> bytes:        # MessageEncryptDecrypt
    # XOR 0xAC em cada byte, MAS bytes que já são 0 ficam 0 (quirk do original)
    return bytes((b ^ 0xAC) if b > 0 else 0 for b in buf)

def pin_xor(pin: int, rnd: int) -> int:      # PinEncryptDecrypt
    return (pin ^ rnd) & 0xFFFF
```

Enum `PinMessageType` (byte): `None=0, LoginRequest=1, LoginChallengeRequest=2,
LoginChallengeResponse=3, LoginChallengeResult=4, ChangePinRequest=5,
ChangePinChallengeRequest=6, ChangePinChallengeResponse=7, ChangePinChallengeResult=8`.

**Fluxo de login** (tudo na char `4c9dbe52`, com notify ativado):

1. App→dev: `DevicePinInfo{packetType=1}` → `ToBytes()` = `01 00 00 00 00 00` → `message_xor` →
   `AD 00 00 00 00 00`. Write.
2. dev→App (notify): 6 bytes → `message_xor` (decifra) → `DevicePinInfo`. Esperar
   `packetType=2` (LoginChallengeRequest) com `randomNumber=R`. Se `result!=0` → falha.
3. App→dev: `DevicePinInfo{packetType=3, randomNumber=R, pin = pin_xor(PIN, R)}` → `ToBytes` →
   `message_xor` → write.
4. dev→App (notify): esperar `packetType=4` (LoginChallengeResult). `result==0` → **login OK**.

`ActualPin = ushort.Parse(pin_string)`; PIN default da app é `"0"`. Mudança de PIN usa o mesmo padrão
com packetTypes 5/6/7/8 (ver `ChangePinAsync`, `SendChangePinRequestAsync`,
`SendChangePinChallengeResponseAsync`).

Nota: no decode a app chama `message_xor(bytes, sizeof(DevicePinInfo)=6)`. O `randomNumber` vem
"em claro" dentro do envelope XOR-0xAC.

---

## 4. Transporte de mensagens (NUS) — de `BleDeviceCommunication`

**Envio** (`SendCommandAsync`):
1. `json = JsonConvert.SerializeObject(command)` (UTF-8).
2. `ChunkBytesIntoPackets(bytes, chunkSize=20)` → pedaços de 20B (último menor).
3. Cada chunk → write em `MessageRequestCharacteristic` (`6e400002`) *write-without-response*.
   (Não há terminador no envio; a app serializa objetos C# anónimos → JSON compacto.)

**Receção** (`MessageServiceOnNotify`):
- Cada notificação de `6e400003`: `Encoding.UTF8.GetString(bytes)`, procura `\0`.
- Acumula num buffer de string. Deduplica notificações idênticas < 100 ms (anti-eco).
- Se o buffer já tinha conteúdo e chega algo a começar por `{`, descarta o incompleto.
- Quando aparece `\0`: corta no `\0`, e:
  - se faz match `^{\s*"Status"` → é `StatusResponse { int Status }` (0 = OK).
  - caso contrário → é um *read result* (JSON do `CommandModel` ou sub-secção).
- Há um `_singleCommandSemaphore` → **um comando de cada vez** (sem pipelining).

Constantes: `MaxChunkSize = 20`. (As constantes 244/151/155 são só para firmware/OTA.)

---

## 5. Comandos (classe `Commands`) — JSON a enviar

Cada entrada é o objeto JSON serializado. Chaves exatamente como abaixo.

**Leitura (devolvem JSON do estado):**
- ReadAll → `{"Read":"All"}`
- ReadSensor → `{"Read":"Section_Sensor"}`
- ReadController → `{"Read":"Section_Controller"}`
- ReadState → `{"Read":"Section_State"}`
- ReadLastRun → `{"Read":"LastRun"}`
- ReadLog → `{"Read":"Log"}`

**Controlo manual (o essencial para HA):**
- Arrancar estação: `{"Manual":{"StationNumber":<n>,"RunTime":<segundos>}}`
- Correr programa: `{"Manual":{"ProgramLetter":"A"}}` (A/B/C)
- Correr tudo (programa de teste "T"): `{"Manual":{"ProgramLetter":"T","RunTime":<seg>}}`
- **Parar tudo:** `{"Manual":{"StopAll":true}}`

**Configuração do controlador (`{"Controller":{...}}`):**
- Ligar/desligar controlador: `ControllerOff:<bool>`
- Nome: `Name:<string>`
- Hora atual (unix): `CurrentTime:<long>`
- Ajuste sazonal global: `SeasonAdjust:<int>, SeasonAdjustByMonthEnable:false`
- Delay entre estações: `StationDelay:<seg>`
- PMV (pump/master valve): `PmvEnabled:<bool>`
- Sensor Clik: `ClickSensorEnabled:<bool>`; bypass: `SensorBypassEnabled:<bool>`
- Clik delay: `ClickDelaySeconds:<int>`
- Solo: `SoilTriggerLevel:<int>, SoilSensorEnabled:<bool>`
- Solar: `SolarPanelAttached:<bool>`
- Dias off programáveis: `ProgrammableDaysOff:<unix>`
- Runtime manual default: `ManualRunTime:<seg>`
- Data troca bateria: `BatteryChangeDate:<unix>`
- Limpar log: `{"Controller":{"LogCount":0}}`

**Programas** (`{"Program_A":{...}}`, idem B/C):
- Nome: `Name`; arranques: `StartTimes:int[] (minutos)`; tempos: `RunTime:int[] (segundos)`
- Dias de rega: `ScheduleType:int, ScheduleDays:int, IntervalDayCount:int, IntervalDayNext:long`

**Estações** (`{"Station_1":{...}}`, 1..4):
- `Name`, `Cycle:<seg>`, `Soak:<seg>`

**Outros:** `{"HunterCustom":{"FactoryReset":true}}`.

Nº de estações suportado: 1, 2 ou 4 (`RestoreAllStations`).

---

## 6. Modelo de dados `CommandModel` (resposta de ReadAll)

Topo (de `NodeV2.Service.Interface`):
`Controller, Sensor, HunterCustom, Program_A, Program_B, Program_C, Program_T,
Station_1..Station_4, Manual, State`.

Há *malformed-JSON fixups* no código original (strings como `"\"Cycl\"Soak\":0"`,
`"\"St\"Remaining\":0"`, `"SeasonAdjustByMonthEnabl"`) — o firmware **emite JSON ligeiramente
inválido** em certos campos e a app corrige por substituição de string antes de desserializar.
→ **O parser Python tem de tolerar/corrigir isto.** Ver `BleDeviceCommunication` (constantes
`malformed*`) e `CommandModelExtensions` para a lista completa de campos derivados
(`StationStates`, `Stations`, `Programs`, `IsControllerOff`, `IsRainClikTriggered`,
`GetClickDelayEndTime`, etc.).

---

## 7. Ambiente e artefactos (como foi feito / como reproduzir)

**Ficheiros de entrada (Downloads do utilizador):**
- `Hunter+NODE-BT_6.0.611246_APKPure.xapk` ← **este é o certo** (package `com.hunter.nodev2`, v6.0.611246)
- `hunter-node-bt.apk` ← **errado**, é o Aptoide renomeado; ignorar.

**A app é .NET MAUI (C#)**, não Java. Assemblies managed empacotados em
`lib/arm64-v8a/libassembly-store.so` (formato `XABA`), comprimidos LZ4 (`XALZ`).

**Ferramentas instaladas nesta máquina durante a análise:**
- .NET SDK 9 (via `winget install Microsoft.DotNet.SDK.9`) — em `C:\Program Files\dotnet`.
- `ilspycmd` **9.1.0.7988** (global tool). A 8.2 crasha com assemblies .NET 9/10
  (`System.Version.ToString fieldCount`); a mais recente tem bug de packaging. **Usar 9.1.x.**
- Correr ilspycmd com `DOTNET_ROLL_FORWARD=LatestMajor` (só há runtimes 8 e 9 instalados; a tool pede 6).

**Pasta de trabalho (temp — pode ser limpa, re-extrair se faltar):**
`C:\Users\Filipe\AppData\Local\Temp\claude\xapk-analysis\`
- `extractor/` — projeto C# que extrai os DLLs do assembly store (ver abaixo).
- `dlls/` — 208 assemblies managed extraídos (incl. todos os `NodeV2.*`, `Plugin.BLE`).
- `src2/` — C# decompilado. **Ficheiros-chave:**
  - `src2/NodeV2.Service.Interface.cs` → `BleGuids`, `Commands`, `CommandModel` e sub-classes
    (`Controller`, `Program`, `Station`, `Sensor`, `State`, `Manual`), interfaces.
  - `src2/NodeV2.Services.cs` → `BleDeviceCommunication` (linha ~2629): envio/receção, PIN,
    cifra (`MessageEncryptDecrypt`/`PinEncryptDecrypt`), `DevicePinInfo`, enums (linhas 3270–3500).
  - `src2/NodeV2.Services.AcrReactiveBle.cs` → camada GATT (scan/connect/write/notify, MTU).
  - `src2/NodeV2.ViewModelsMaui.cs` → lógica de UI/fluxos (útil p/ sequência connect→login→readAll→poll).

**Reproduzir extração + decompilação do zero (bash/Git-Bash):**
```bash
X=/c/Users/Filipe/AppData/Local/Temp/claude/xapk-analysis
mkdir -p "$X" && cd "$X"
unzip -o "/c/Users/Filipe/Downloads/Hunter+NODE-BT_6.0.611246_APKPure.xapk" config.arm64_v8a.apk
unzip -o config.arm64_v8a.apk 'lib/arm64-v8a/libassembly-store.so' -d nodev2
# build do extractor (ver src do Program.cs guardado em extractor/)
export PATH="/c/Program Files/dotnet:$HOME/.dotnet/tools:$PATH"
export DOTNET_ROLL_FORWARD=LatestMajor
cd extractor && dotnet build -c Release -q
dotnet run -c Release --no-build -- "../nodev2/lib/arm64-v8a/libassembly-store.so" "../dlls"
cd .. && for a in NodeV2.Service.Interface NodeV2.Services NodeV2.Services.AcrReactiveBle; do
  ilspycmd "dlls/$a.dll" > "src2/$a.cs"; done
```

**Lógica do extractor** (`extractor/Program.cs`, resumo): varre o `.so` por blocos `XALZ`
(magic `58 4C 41 5A`); para cada um lê `uint32 uncompressedLen` em `offset+8`, descomprime LZ4-block
de `offset+12` até ao próximo `XALZ` com `K4os.Compression.LZ4` (`LZ4Codec.Decode`), e grava o `.dll`
usando o nome lido via `System.Reflection.Metadata` (`PEReader`→`AssemblyDefinition.Name`). Dá 208 DLLs.

---

## 8. O que falta fazer

1. **Ler as sub-classes do `CommandModel`** em `src2/NodeV2.Service.Interface.cs`
   (`Controller`, `Station`, `Program`, `State`, `Sensor`, `Manual`) — campos exatos e tipos, para
   mapear sensores/entidades HA (estado de rega, estação ativa, tempo restante, nível de bateria,
   flags de sensor de chuva/solo). Ver também `CommandModelExtensions` em `NodeV2.Services.cs`.
2. **Confirmar a sequência de arranque** em `NodeV2.ViewModelsMaui.cs` / `DeviceStateManager`:
   ordem real connect → ativar notify (PIN e NUS) → login PIN → `ReadAll` → polling de `ReadState`/
   `ReadLastRun`. Confirmar MTU (a app observa `WhenMtuChanged`, mas envia sempre em chunks de 20B).
3. **Validar com captura BLE real** (opcional mas recomendado): ativar *Bluetooth HCI snoop log* no
   Android, emparelhar/operar com a app, puxar o log e confirmar frames do PIN e o JSON. Confirma o
   quirk do XOR e o JSON malformado.
4. **Escrever o custom component HA** (Python, `bleak` / `bleak-retry-connector`, base
   `homeassistant.components.bluetooth`):
   - Camada de protocolo (classe `HunterNodeBT`): connect, `authenticate(pin)`, `send_command(dict)`
     com chunking 20B, `read(command)` que acumula notificações até `\0` e faz `json.loads` (com
     fixups do ponto 6), handshake PIN do ponto 3.
   - Entidades: `valve`/`switch` por estação (ManualStation / StopAll), `number` para runtime,
     `sensor` para bateria/estado/último arranque, `binary_sensor` para sensores de chuva/solo.
   - Config flow: descoberta por serviço `6e400001...`, campo PIN (default 0).
   - Estrutura HACS: `custom_components/hunter_node_bt/` + `manifest.json` (`bluetooth` matcher no
     service uuid), `hacs.json`, README.

**Riscos/notas:** `Manual.StopAll`, `StationNumber` 1-based, tempos de estação em **segundos**,
`StartTimes` de programa em **minutos**. Respostas podem vir fragmentadas em várias notificações;
o fim é sempre `\0`. Um comando de cada vez (semáforo). O JSON é compacto e usa chaves PascalCase.

---

## 9. Referências rápidas de código (abrir estes ficheiros)

- GATT UUIDs: `src2/NodeV2.Service.Interface.cs:76` (`class BleGuids`)
- Comandos JSON: `src2/NodeV2.Service.Interface.cs:292` (`class Commands`)
- CommandModel: `src2/NodeV2.Service.Interface.cs:128`
- Envio/chunking: `src2/NodeV2.Services.cs:3061` (`SendCommandAsync`), `:3083` (`ChunkBytesIntoPackets`)
- Receção/parse: `src2/NodeV2.Services.cs:3112` (`MessageServiceOnNotify`)
- Login PIN: `src2/NodeV2.Services.cs:3270` (`LoginUsingPinAsync`), `:3329` (`PinServiceOnNotify`),
  `:3346` (`SendLoginRequestAsync`), `:3359` (`SendLoginChallengeResponseAsync`)
- Cifra/struct/enum: `src2/NodeV2.Services.cs:3428`–`3500`
