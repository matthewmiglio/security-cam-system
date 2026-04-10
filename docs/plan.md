# DIY Wi-Fi Security Camera System — Stack Details & Appendix

> Step-by-step setup instructions are in the [README](../README.md).

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
| Part | Choice | Notes | Price (USD) | Buy |
|---|---|---|---|---|
| Compute | Raspberry Pi Zero 2 W | Built-in 2.4 GHz Wi-Fi, CSI-2, H.264 encode @ 1080p30 | $16.35 | [Canakit](https://www.canakit.com/raspberry-pi-zero-2-w.html?defpid=4783) |
| Camera | Arducam IMX219 8MP (Pi Camera V2 equivalent) | Ships with 22-22pin Zero 2W ribbon in the box. Upgrade to Camera Module 3 NoIR only on nodes that need night vision. | $12.99 | [Amazon](https://www.amazon.com/gp/product/B09V576TFN/ref=ox_sc_act_title_1?smid=A2IAB2RW3LLT8D&psc=1) |
| Storage | 32 GB SanDisk Ultra microSDHC (A1, 2-pack) | OS + app only, no footage | ~$16 (= $32 / 2) | [Amazon](https://www.amazon.com/gp/product/B08J4HJ98L/ref=ox_sc_act_title_2?smid=ATVPDKIKX0DER&th=1) |
| Power | Canakit 5V 2.5A Micro USB supply | Cheap bricks cause instability | $9.95 | [Canakit](https://www.canakit.com/raspberry-pi-adapter-power-supply-2-5a.html) |
| CSI cable | Zero 22-22pin ribbon | **Included with the Arducam camera above** — don't buy separately | $0 | — |
| Enclosure | 3D printed, 2-piece, PETG/ASA | ~40–60 g filament per unit | ~$2 (filament) | self-print |
| Optional | IR LED ring + light sensor | Only for NoIR night-vision units | ~$5 | — |
| **Per-node total** | | | **~$57 (day)** | |

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
- **OS:** Raspberry Pi OS Lite (64-bit, Trixie / Debian 13)
- **Capture:** `libcamera` / `rpicam-apps` (system stack)
- **RTSP server:** [MediaMTX](https://github.com/bluenviron/mediamtx) — small Go binary, publishes the libcamera stream as RTSP
- **Control API:** FastAPI + uvicorn (small Python service)
- **Process management:** systemd (one unit per service, `Restart=always`)

### Mothership
- **NVR:** [Frigate](https://frigate.video/) in Docker — handles recording, retention, live view, motion/object detection, clip export
- **Reverse proxy (optional):** Caddy or nginx for HTTPS on your LAN
- **Monitoring (optional):** Uptime Kuma pinging each node's `/health`

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
