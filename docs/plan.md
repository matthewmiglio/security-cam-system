# DIY Wi-Fi Security Camera System — Build Plan

## Architecture (one-line summary)

Cheap, dumb, identical Pi-based camera nodes stream H.264/RTSP over Wi-Fi to a
single "mothership" PC running Frigate as the NVR. All real storage, motion
detection, retention, and UI lives on the mothership. Edge nodes are basically
stateless IP cameras.

```
[Cam Node 1] --Wi-Fi/RTSP--> \
[Cam Node 2] --Wi-Fi/RTSP-->  --> [Mothership: Frigate + big HDDs]
[Cam Node N] --Wi-Fi/RTSP--> /
```

### Design principles
- One sensor, one compute platform across all nodes (easy to mass produce later).
- No hard drives at the edge. Storage lives centrally.
- Edge nodes are stateless — replace one by flashing an SD card.
- Push complexity into software on the mothership, not into each node.
- RTSP/H.264, not MJPEG. Wi-Fi bandwidth matters once you have 3+ cameras.

---

## Hardware

### Per camera node (v1 — cheapest useful)
| Part | Choice | Notes | Price (USD) |
|---|---|---|---|
| Compute | Raspberry Pi Zero 2 W | Built-in 2.4 GHz Wi-Fi, CSI-2, H.264 encode @ 1080p30 | ~$15 |
| Camera | Raspberry Pi Camera Module 2 (official, IMX219 8MP, fixed focus) | First-class libcamera support, no clone lottery. Upgrade to Module 3 NoIR (~$25) only on nodes that need night vision. | ~$15 |
| Storage | 32 GB microSD (A2, Samsung Evo / SanDisk High Endurance) | OS + app only, no footage | ~$8 |
| Power | 5V 2.5A USB supply (official Pi PSU ideal) | Cheap bricks cause instability | ~$10 |
| CSI cable | Zero-compatible ribbon (22-pin to 15-pin) | Zero uses the mini CSI connector | ~$3 |
| Enclosure | 3D printed, 2-piece, PETG/ASA | ~40–60 g filament per unit | ~$2 (filament) |
| Optional | IR LED ring + light sensor | Only for NoIR night-vision units | ~$5 |
| **Per-node total** | | | **~$53 (day) / ~$68 (night w/ Module 3 NoIR + IR ring)** |

### Mothership (you already have this)
| Part | Choice | Price (USD) |
|---|---|---|
| PC | Any old desktop / mini PC you already own | $0 |
| OS | Linux (Debian / Ubuntu LTS) | $0 |
| Storage | Surveillance-rated HDD (WD Purple / Seagate Skyhawk), 4–8 TB if buying new | ~$90–$180 (4–8 TB) / $0 if reusing |
| Network | Wired Gigabit Ethernet to the router (critical — don't put the NVR on Wi-Fi) | $0 |
| Optional | Google Coral USB TPU (for object detection in Frigate) | ~$60 |

### Network
- 5 GHz capable access point (even though Zero 2 W is 2.4 GHz only, this keeps the 2.4 band less congested for the cameras)
- Budget ~2–4 Mbps per 1080p camera
- Put cameras on a dedicated VLAN/SSID if your router supports it

### Production path (later, after v1 works)
- Raspberry Pi Compute Module 5 instead of Zero 2 W
- Camera Module 3 Sensor Assembly (bare sensor board for OEM)
- Custom carrier board: CSI + PoE + eMMC + IR LED driver + status LED
- PoE replaces Wi-Fi for permanent installs

---

## Software stack

### Edge node (per camera)
- **OS:** Raspberry Pi OS Lite (64-bit, Bookworm)
- **Capture:** `libcamera` / `rpicam-apps` (system stack)
- **RTSP server:** [MediaMTX](https://github.com/bluenviron/mediamtx) — small Go binary, publishes the libcamera stream as RTSP
- **Control API:** FastAPI + uvicorn (small Python service)
- **Process management:** systemd (one unit per service, `Restart=always`)

### Mothership
- **NVR:** [Frigate](https://frigate.video/) in Docker — handles recording, retention, live view, motion/object detection, clip export
- **Reverse proxy (optional):** Caddy or nginx for HTTPS on your LAN
- **Monitoring (optional):** Uptime Kuma pinging each node's `/health`

---

## Step-by-step build plan

### Phase 0 — Bench prep
1. Flash Raspberry Pi OS Lite 64-bit to the microSD using Raspberry Pi Imager.
   - In Imager: preset hostname (`cam01`), SSH on, Wi-Fi credentials, username, SSH key.
2. Boot the Pi Zero 2 W headless, SSH in, `sudo apt update && sudo apt full-upgrade -y`.
3. Confirm camera works: `rpicam-hello --timeout 2000` (should report the IMX708 detected).

### Phase 1 — Single streaming camera node
1. Install MediaMTX:
   ```bash
   wget https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_arm64v8.tar.gz
   sudo tar -xzf mediamtx_linux_arm64v8.tar.gz -C /usr/local/bin mediamtx
   sudo mv mediamtx_linux_arm64v8/mediamtx.yml /etc/mediamtx.yml
   ```
2. Configure MediaMTX to publish a path named `cam` that runs `rpicam-vid` and pipes H.264 to it. Example path config:
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

### Phase 2 — Control API on each node
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
   - detector: CPU detector to start; add Coral USB TPU later if you want object detection
4. Access the Frigate UI at `http://mothership.local:5000`.
5. Confirm recording writes to the HDD and retention prunes correctly.

### Phase 4 — Enclosure & deployment
1. Design 3D-printed 2-piece case:
   - Lens cutout aligned to camera module
   - Cable strain relief
   - Vent slots (no fan)
   - Mounting tab / standard tripod thread
2. Print in PETG or ASA (weather resistance if outdoor; add silicone gasket).
3. Build 1–2 units, deploy, watch them for a week for thermal / Wi-Fi / SD issues.

### Phase 5 — Fleet hygiene
1. Bake a "golden" SD image after node is configured → `dd` clone for new nodes.
2. Set predictable hostnames `cam01`..`camNN` + mDNS.
3. Static DHCP reservations on the router.
4. Add Uptime Kuma or simple cron script on mothership pinging each `/health`.
5. Document the flash-and-deploy process in this repo's README.

### Phase 6 — Production migration (only when v1 is stable)
1. Swap Zero 2 W → CM5 + custom carrier.
2. Swap Camera Module 3 → Camera Module 3 Sensor Assembly.
3. Carrier adds PoE, eMMC, IR driver.
4. Keep the software image nearly identical — that's the whole point.

---

## Repo layout (planned)

```
security-cam-setup/
├── docs/
│   ├── plan.md                (this file)
│   └── raw-chatgpt-planning.txt
├── edge/
│   ├── camctl/                FastAPI control service
│   ├── mediamtx/              mediamtx.yml + systemd unit
│   └── systemd/               *.service files
├── mothership/
│   ├── docker-compose.yml     Frigate
│   └── frigate/
│       └── config.yml
├── enclosure/
│   └── *.stl / *.step         3D-print files
└── scripts/
    ├── flash-node.sh          provision a fresh SD card
    └── clone-golden.sh
```

---

## What NOT to build (yet)

- Per-camera hard drives
- Cloud streaming / remote access beyond LAN
- Mobile app
- Custom PCB
- Battery power
- Audio
- Face recognition
- WebRTC (use RTSP first)
- On-device motion detection (let Frigate do it centrally)

---

## Bandwidth budget (sanity check)

| Cameras | Resolution | Bitrate each | Total |
|---|---|---|---|
| 4 | 1080p @ 15fps | 2.5 Mbps | 10 Mbps |
| 8 | 1080p @ 15fps | 2.5 Mbps | 20 Mbps |
| 8 | 720p @ 15fps | 1.5 Mbps | 12 Mbps |

A single cheap Wi-Fi router handles this fine. If you go past ~12 cameras on
Wi-Fi, move some to Ethernet or PoE.
