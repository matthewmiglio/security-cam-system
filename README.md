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

**Per camera node (~$53):**
- Raspberry Pi Zero 2 W
- Pi Camera Module 2 (IMX219)
- 32 GB microSD + 5V PSU + CSI ribbon
- 3D-printed enclosure

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

## Status

Planning phase. See [docs/plan.md](docs/plan.md) for the step-by-step build.
