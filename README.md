# security-cam-setup

DIY Wi-Fi security camera system. Cheap, stateless Pi-based camera nodes stream
RTSP/H.264 to a single old PC running Frigate as the NVR. All storage, motion
detection, and UI lives on the mothership — camera nodes are replaceable.

Full build plan: [docs/plan.md](docs/plan.md)

## Architecture

```
[Cam Node 1] --Wi-Fi/RTSP--> \
[Cam Node 2] --Wi-Fi/RTSP-->  --> [Mothership PC: Frigate + HDD]
[Cam Node N] --Wi-Fi/RTSP--> /
```

Edge nodes: capture + stream. Mothership: record, retain, view, manage.

## Hardware

**Per camera node (~$57):**
- [Raspberry Pi Zero 2 W](https://www.canakit.com/raspberry-pi-zero-2-w.html?defpid=4783) — $16.35 (Canakit)
- [Arducam IMX219 8MP camera](https://www.amazon.com/gp/product/B09V576TFN/ref=ox_sc_act_title_1?smid=A2IAB2RW3LLT8D&psc=1) — $12.99 (Amazon, ribbon cable included)
- [32 GB SanDisk Ultra microSD (2-pack)](https://www.amazon.com/gp/product/B08J4HJ98L/ref=ox_sc_act_title_2?smid=ATVPDKIKX0DER&th=1) — ~$16/card (Amazon)
- [Canakit 5V 2.5A Micro USB PSU](https://www.canakit.com/raspberry-pi-adapter-power-supply-2-5a.html) — $9.95 (Canakit)
- 3D-printed enclosure — ~$2 filament

**Mothership:**
- Any old PC (reuse what you have)
- Big HDD, wired Gigabit Ethernet
- Linux + Docker

## Software

```
Edge node                           Mothership
---------                           ----------
libcamera / rpicam-vid       -->    Frigate (NVR)
  |                                   - records streams
  v                                   - retention policy
MediaMTX (RTSP server)  -----\        - live dashboard
                              \       - motion/object detection
FastAPI control API            ---->  - clip export
  - /health /snapshot
  - /reboot /settings
systemd (auto-restart)
```

## Why this design

- **No storage at the edge** — no HDDs, no per-node DB, nodes stay cheap
- **Stateless nodes** — flash an SD card, plug in, done
- **RTSP/H.264** — efficient enough for many cameras on one Wi-Fi AP
- **Central complexity** — easier to manage, back up, and upgrade

## Quick Start — Phase 0: Flash the SD Card

1. Download and install [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Run Imager and select:
   - **Device** → Raspberry Pi Zero 2 W
   - **OS** → Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**
   - **Storage** → your microSD card
3. Click the **gear/settings icon** before writing and configure:
   - Hostname: `cam01`
   - Enable SSH (use password or public key)
   - Wi-Fi SSID + password
   - Username + password
4. Hit **Write** and wait for it to finish
5. Put the SD card in the Pi, plug in HDMI **before** power, then power on
6. You should see boot text on the monitor within a few seconds

Full build plan: [docs/plan.md](docs/plan.md)

## Status

Planning phase. See [docs/plan.md](docs/plan.md) for the step-by-step build.
