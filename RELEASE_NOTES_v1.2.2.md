# v1.2.2 — Faster Home Assistant startup

## What's new

### The integration no longer holds up Home Assistant's startup
When the controller is far from the Bluetooth adapter or proxy, the first connection can take minutes, or fail a few times before one gets through. Until now, Home Assistant waited for that first poll before it finished starting. Its log said *"Waiting for integrations to complete setup: hunter_node_bt"*.

From v1.2.2, the integration starts at once with the **last known state**: valves, battery, rain delay, programs and settings. This is the last good read saved by v1.2.1. It then connects to the controller **in the background** and updates the entities when the poll gets through.

- On the very first setup there is nothing saved yet, so the integration still waits for one successful read. It needs the controller's station layout to create the entities.
- If no poll succeeds for 2 hours, the entities become unavailable, the same as in v1.2.1.

## Recap of v1.2.1 (weak Bluetooth signal)
- The last good data is kept for up to **2 hours** after the last successful poll. Before, the entities went unavailable after 2 failed polls.
- After a failed poll the integration retries in **3 minutes**, instead of waiting for the normal scan interval.
- The last good read is **saved** and loaded at startup.

## Upgrade notes
- No configuration changes are needed.
- Restart Home Assistant after updating.
