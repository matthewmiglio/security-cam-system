# security-cam-setup

DIY Wi-Fi security camera system. Cheap, stateless Pi-based camera nodes stream
RTSP/H.264 to a single old PC running Frigate as the NVR. All storage, motion
detection, and UI lives on the mothership — camera nodes are replaceable.

Stack details & appendix: [docs/plan.md](docs/plan.md)

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

## Setup

### Phase 0 — Bench Prep

#### First time (needs internet)

1. Download and install [Raspberry Pi Imager](https://downloads.raspberrypi.com/imager/imager_latest.exe) (Windows).
2. Run Imager and select:
   - **Device** → Raspberry Pi Zero 2 W
   - **OS** → Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**
   - **Storage** → your microSD card
3. Click **Customisation** in the sidebar and configure:
   - Hostname: `cam01`
   - Enable SSH (use password or public key)
   - Wi-Fi SSID + password
   - Username + password
4. Hit **Write** and wait for it to finish.
5. Before removing the SD card, image it back to your PC as a golden `.img` file for future offline use:
   - **Windows:** Use [Win32 Disk Imager](https://sourceforge.net/projects/win32diskimager/files/latest/download):
     1. Set **Device** to your SD card drive (e.g. `D:\`).
     2. Click the folder icon next to **Image File**, pick a save location and name (e.g. `golden-cam.img`).
     3. Click **Read** and wait for it to finish.
   - **Linux/macOS:** `sudo dd if=/dev/sdX of=golden-cam.img bs=4M status=progress`
6. Put the SD card in the Pi, plug in HDMI **before** power, then power on.
7. SSH in: `ssh cam01.local`, then `sudo apt update && sudo apt full-upgrade -y`.
8. Confirm camera works: `rpicam-hello --timeout 2000` (should detect the IMX219).

#### Additional nodes (offline)

1. In Raspberry Pi Imager: **Device** → Raspberry Pi Zero 2 W, **OS** → **Use custom** → select your `golden-cam.img` file, **Storage** → your SD card.
2. Hit **Write**. No network needed.
3. Boot the Pi and change the hostname (`sudo hostnamectl set-hostname cam02`, etc.).

### Phase 1 — Single Streaming Camera Node

1. Install MediaMTX:
   ```bash
   wget https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_arm64v8.tar.gz
   sudo tar -xzf mediamtx_linux_arm64v8.tar.gz -C /usr/local/bin mediamtx
   sudo mv mediamtx_linux_arm64v8/mediamtx.yml /etc/mediamtx.yml
   ```
2. Configure MediaMTX to publish a path named `cam` that runs `rpicam-vid` and pipes H.264:
   ```yaml
   paths:
     cam:
       runOnInit: >
         bash -c 'rpicam-vid -t 0 --inline --nopreview
         --width 1920 --height 1080 --framerate 15
         --codec h264 --bitrate 2500000 -o - |
         ffmpeg -f h264 -i - -c copy -f rtsp rtsp://localhost:8554/cam'
       runOnInitRestart: yes
   ```
3. Create a systemd unit `/etc/systemd/system/mediamtx.service` → enable + start.
4. Verify from the mothership: `ffplay rtsp://cam01.local:8554/cam` (or VLC).

### Phase 2 — Control API on Each Node

1. Install: `sudo apt install -y python3-pip python3-venv`
2. Create `/opt/camctl/` with venv, install `fastapi uvicorn`.
3. Implement endpoints (see `src/camctl/` in this repo when built):
   - `GET /health` — uptime, temp, free disk
   - `GET /snapshot` — grab a JPEG via `rpicam-still`
   - `POST /stream/restart` — `systemctl restart mediamtx`
   - `POST /reboot`
   - `POST /settings` — bitrate / resolution / fps (writes config, restarts stream)
4. Run under systemd on port 8000, bind to LAN only.
5. Lock down with a shared-secret header or Tailscale/WireGuard if exposed beyond LAN.

### Phase 3 — Mothership / Frigate

1. Install Docker + docker compose on the old PC.
2. Mount the big HDD at `/mnt/nvr`.
3. `docker-compose.yml` for Frigate with:
   - `media` volume → `/mnt/nvr`
   - camera definitions pointing at `rtsp://camNN.local:8554/cam`
   - retention: e.g. 7 days continuous, 30 days motion events
   - detector: CPU detector to start; add Coral USB TPU later for object detection
4. Access the Frigate UI at `http://mothership.local:5000`.
5. Confirm recording writes to the HDD and retention prunes correctly.

### Phase 4 — Enclosure & Deployment

1. Design 3D-printed 2-piece case:
   - Lens cutout aligned to camera module
   - Cable strain relief
   - Vent slots (no fan)
   - Mounting tab / standard tripod thread
2. Print in PETG or ASA (weather resistance if outdoor; add silicone gasket).
3. Build 1–2 units, deploy, watch for a week for thermal / Wi-Fi / SD issues.

### Phase 5 — Fleet Hygiene

1. Bake a "golden" SD image after node is configured → `dd` clone for new nodes.
2. Set predictable hostnames `cam01`..`camNN` + mDNS.
3. Static DHCP reservations on the router.
4. Add Uptime Kuma or simple cron script on mothership pinging each `/health`.
5. Document the flash-and-deploy process in this repo's README.

### Phase 6 — Production Migration (only when v1 is stable)

1. Swap Zero 2 W → CM5 + custom carrier.
2. Swap Camera Module 3 → Camera Module 3 Sensor Assembly.
3. Carrier adds PoE, eMMC, IR driver.
4. Keep the software image nearly identical — that's the whole point.

## Status

Planning phase. See [docs/plan.md](docs/plan.md) for stack details and appendix.
