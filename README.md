# security-cam-setup

DIY Wi-Fi security camera system. Cheap, stateless Pi-based camera nodes stream
RTSP/H.264 to a single old PC running Frigate as the NVR. All storage, motion
detection, and UI lives on the mothership — camera nodes are replaceable.

Stack details & appendix: [docs/plan.md](docs/plan.md)

![Frigate NVR dashboard](docs/images/ui-preview.webp)

| ![Cam 1 snapshot](docs/images/cam-1-snapshot-example.webp) | ![Cam 2 snapshot](docs/images/cam-2-snapshot-example.webp) |
|---|---|
| Cam 1 snapshot | Cam 2 snapshot |

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

### Phase 0 — Hardware Assembly

Connect the CSI ribbon cable between the Pi Zero 2 W and the Arducam IMX219.

**Parts:**

| Pi Zero 2 W | Arducam IMX219 (back) | CSI ribbon cable |
|---|---|---|
| ![Pi Zero 2 W front](docs/images/pi-zero-2w-front.webp) | ![Arducam back](docs/images/arducam-imx219-back.webp) | ![CSI cable contacts](docs/images/csi-cable-front.webp) |

**Cable orientation:**
- The cable has two sides: a **contacts side** (exposed metal strips) and a **plain side** (white/blue stiffener tab).
- Both the Pi and the Arducam have a small plastic CSI connector with a flip-up latch.

| | ![CSI cable contacts side](docs/images/csi-cable-front.webp) | ![CSI cable plain side](docs/images/csi-cable-back.webp) |
|---|---|---|
| | Contacts side (metal strips) | Plain side (blue stiffener tab) |

**Steps:**
1. Gently flip up the plastic latch on the Pi's CSI connector (near the HDMI port).
2. Slide the ribbon cable in with **contacts facing the board** (toward the PCB).
3. Press the latch back down to lock.
4. Repeat on the Arducam — flip latch, insert cable with **contacts facing AWAY from the board** (opposite of the Pi side), close latch.
5. Insert the microSD card into the Pi's card slot.

**Result:**

| Assembled nodes |
|---|
| ![Two assembled Pi + Arducam units](docs/images/two-pi-zero-2w-with-cables.webp) |
| ![Two Arducams with cables attached](docs/images/two-arducams-with-cables.webp) |

### Phase 1 — Flash the SD Card

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

> **Trixie (Debian 13) note:** If `rpicam-hello` reports "No cameras available" even with
> `camera_auto_detect=1` in `/boot/firmware/config.txt`, you also need `dtoverlay=imx219`.
> The setup script (Phase 2) adds this automatically, but if you're debugging before
> running the script, add it manually and reboot.

#### Additional nodes (offline)

1. In Raspberry Pi Imager: **Device** → Raspberry Pi Zero 2 W, **OS** → **Use custom** → select your `golden-cam.img` file, **Storage** → your SD card.
2. Hit **Write**. No network needed.
3. Boot the Pi and change the hostname (`sudo hostnamectl set-hostname cam02`, etc.).

### Phase 2 — Single Streaming Camera Node

Run the setup script on the Pi (installs MediaMTX, configures RTSP streaming, creates a systemd service):

```bash
# Option A — from the Pi itself:
sudo bash scripts/setup-cam.sh

# Option B — from your workstation over SSH:
ssh cam01.local 'sudo bash -s' < scripts/setup-cam.sh
```

The script handles:
- System update
- Camera detection + `/boot/firmware/config.txt` fixes (`camera_auto_detect=1`, `dtoverlay=imx219`)
- Installing ffmpeg + python3
- Downloading and installing [MediaMTX](https://github.com/bluenviron/mediamtx) v1.17.1
- Configuring MediaMTX to use the native `rpiCamera` source (hardware H.264, no ffmpeg pipe)
- Creating and enabling a `mediamtx.service` systemd unit

Defaults (override with env vars):
| Setting | Default | Env var |
|---|---|---|
| Resolution | 1920×1080 | `STREAM_WIDTH`, `STREAM_HEIGHT` |
| Frame rate | 15 fps | `STREAM_FPS` |
| Bitrate | 2.5 Mbps | `STREAM_BITRATE` |
| RTSP port | 8554 | `RTSP_PORT` |
| Stream path | `cam` | `STREAM_PATH` |

Verify from the mothership:
```bash
ffplay rtsp://cam01.local:8554/cam
# or
vlc rtsp://cam01.local:8554/cam
```

### Phase 3 — Control API on Each Node

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

### Phase 4 — Mothership / Frigate

1. Install Docker Desktop (Windows) or Docker + docker compose (Linux) on the mothership PC.
2. Configure cameras in [`mothership/frigate/config.yml`](mothership/frigate/config.yml) — point each `path` at `rtsp://camNN.local:8554/cam` and tune retention.
3. Adjust the `TZ` env var in [`mothership/docker-compose.yml`](mothership/docker-compose.yml) if you're not on `America/New_York`.
4. Boot the mothership view:
   ```bash
   cd mothership
   docker compose up -d
   ```
   Recordings, clips, exports, and snapshots land under `mothership/storage/` (move that to a larger drive when you outgrow it).
5. Open the Frigate UI at **http://localhost:5000** (or `http://mothership.local:5000` from another LAN machine). The API is on port `8971`.
6. Useful commands:
   ```bash
   docker compose logs -f frigate   # tail logs
   docker compose restart frigate   # reload after config edits
   docker compose down              # stop the stack
   ```
7. Confirm recording writes to `mothership/storage/recordings/` and retention prunes correctly.

### Phase 5 — Enclosure & Deployment

1. Design 3D-printed 2-piece case:
   - Lens cutout aligned to camera module
   - Cable strain relief
   - Vent slots (no fan)
   - Mounting tab / standard tripod thread
2. Print in PETG or ASA (weather resistance if outdoor; add silicone gasket).
3. Build 1–2 units, deploy, watch for a week for thermal / Wi-Fi / SD issues.

### Phase 6 — Fleet Hygiene

1. Bake a "golden" SD image after node is configured → `dd` clone for new nodes.
2. Set predictable hostnames `cam01`..`camNN` + mDNS.
3. Static DHCP reservations on the router.
4. Add Uptime Kuma or simple cron script on mothership pinging each `/health`.
5. Document the flash-and-deploy process in this repo's README.

### Phase 7 — Production Migration (only when v1 is stable)

1. Swap Zero 2 W → CM5 + custom carrier.
2. Swap Camera Module 3 → Camera Module 3 Sensor Assembly.
3. Carrier adds PoE, eMMC, IR driver.
4. Keep the software image nearly identical — that's the whole point.

## Status

Phase 2 complete — single camera node streaming RTSP. See [docs/plan.md](docs/plan.md) for stack details and appendix.
