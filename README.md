# Hunter NODE-BT Home Assistant Integration

Custom Home Assistant integration (HACS) for **Hunter NODE-BT** Bluetooth battery-operated irrigation controllers (1, 2, and 4 stations).

Reverse-engineered directly from the official Hunter NODE-BT app (`com.hunter.nodev2`).

---

## Features

- **Automatic Bluetooth Discovery**: Home Assistant automatically detects nearby Hunter NODE-BT controllers advertising the Nordic UART Service.
- **PIN Authentication**: Supports default PIN (`0`) and custom security PINs with challenge-response encryption.
- **Valve Control**: One valve entity per station (1–4 depending on your controller model):
  - Turn on a valve to start irrigation for the configured default duration.
  - Turn off a valve to stop irrigation.
- **Sensors**:
  - Controller Battery level (`%`).
  - Soil moisture level (`%`).
  - Controller operational state (Idle, Running, Rain Delay, etc.).
  - Next scheduled watering time timestamp.
  - Remaining run time per station (seconds).
- **Binary Sensors**:
  - Rain sensor active / Clik sensor detection.
  - Rain delay active status.
- **Buttons**:
  - **Stop All Stations**: Instantly halts all active watering valves.
  - **Run Program A / B / C**: Manually start pre-configured irrigation cycles.
  - **Test All Stations**: Runs a quick test sequence across all stations.
- **Options Flow**: Easily change the default manual run time (in minutes) via the integration settings without re-pairing.

---

## Installation

### Via HACS (Recommended)

1. Open **HACS** in your Home Assistant instance.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add the repository URL: `https://github.com/<your-username>/hunter-node-bt` with category **Integration**.
4. Click **Download**, then restart Home Assistant.

### Manual Installation

1. Copy the `custom_components/hunter_node_bt` folder into your Home Assistant `<config_dir>/custom_components/` directory.
2. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to **Settings > Devices & Services > Add Integration**.
2. Search for **Hunter NODE-BT** (or accept the discovered Bluetooth device notification).
3. If prompted, select your controller's Bluetooth address and enter your **PIN** (default is `0`).
4. Set your preferred default manual run time (default is 10 minutes).

---

## Protocol Details

For the full reverse-engineered Bluetooth protocol documentation, see [PROTOCOL.md](PROTOCOL.md).
