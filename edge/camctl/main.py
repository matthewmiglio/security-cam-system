"""
camctl — FastAPI control API for a Raspberry Pi camera node.

Runs on each Pi Zero 2 W alongside MediaMTX.  Provides health info,
snapshot capture, stream restart, reboot, and settings endpoints.

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import os
import socket
import tempfile
import time
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="camctl", version="0.1.0")

BOOT_TIME = time.time()
MEDIAMTX_CONFIG = Path("/etc/mediamtx/mediamtx.yml")
THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")
RTSP_URL = "rtsp://127.0.0.1:8554/cam"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def run(cmd: list[str], timeout: float = 15.0) -> asyncio.subprocess.Process:
    """Run a subprocess with a timeout.  Returns the completed process."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise HTTPException(status_code=504, detail=f"Command timed out: {cmd}")
    return proc


def read_cpu_temp() -> Optional[float]:
    """Read CPU temperature in celsius, or None if unavailable."""
    try:
        raw = THERMAL_ZONE.read_text().strip()
        return int(raw) / 1000.0
    except Exception:
        return None


def get_local_ip() -> str:
    """Best-effort LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def disk_free_bytes(path: str = "/") -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


async def camera_is_busy() -> bool:
    """Return True if mediamtx currently owns the camera (service active)."""
    proc = await run(["systemctl", "is-active", "--quiet", "mediamtx"], timeout=5.0)
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    uptime_s = time.time() - BOOT_TIME
    return {
        "hostname": socket.gethostname(),
        "ip": get_local_ip(),
        "uptime_s": round(uptime_s, 1),
        "cpu_temp_c": read_cpu_temp(),
        "disk_free_mb": round(disk_free_bytes() / (1024 * 1024), 1),
    }


@app.get("/snapshot")
async def snapshot():
    """Grab a single JPEG frame.

    If MediaMTX is running (owns the camera), pull a frame from the local
    RTSP stream via ffmpeg.  Otherwise, use rpicam-still directly.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    tmp_path = tmp.name

    try:
        if await camera_is_busy():
            # Camera locked by mediamtx — grab from RTSP stream instead
            proc = await run([
                "ffmpeg", "-y",
                "-rtsp_transport", "tcp",
                "-i", RTSP_URL,
                "-frames:v", "1",
                "-q:v", "2",
                tmp_path,
            ], timeout=10.0)
        else:
            proc = await run([
                "rpicam-still",
                "-n",               # no preview
                "-t", "1",          # minimal warm-up
                "-o", tmp_path,
            ], timeout=10.0)

        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Capture failed (exit {proc.returncode})",
            )

        data = Path(tmp_path).read_bytes()
        if not data:
            raise HTTPException(status_code=500, detail="Capture produced empty file")

        return Response(content=data, media_type="image/jpeg")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.post("/stream/restart")
async def stream_restart():
    proc = await run(["systemctl", "restart", "mediamtx"], timeout=15.0)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail="Failed to restart mediamtx")
    return {"status": "ok", "detail": "mediamtx restarted"}


@app.post("/reboot")
async def reboot():
    # Fire and forget — the response may not fully reach the client
    await run(["shutdown", "-r", "now"], timeout=5.0)
    return {"status": "ok", "detail": "rebooting"}


class StreamSettings(BaseModel):
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[int] = None
    bitrate: Optional[int] = None


@app.post("/settings")
async def settings(body: StreamSettings):
    """Update stream settings in mediamtx.yml and restart the service."""
    if not MEDIAMTX_CONFIG.exists():
        raise HTTPException(status_code=500, detail="mediamtx.yml not found")

    cfg = yaml.safe_load(MEDIAMTX_CONFIG.read_text())

    # Find the first path entry to update (typically "cam")
    paths = cfg.get("paths", {})
    if not paths:
        raise HTTPException(status_code=500, detail="No paths defined in mediamtx.yml")

    path_key = next(iter(paths))
    path_cfg = paths[path_key]

    changed = False
    if body.width is not None:
        path_cfg["rpiCameraWidth"] = body.width
        changed = True
    if body.height is not None:
        path_cfg["rpiCameraHeight"] = body.height
        changed = True
    if body.fps is not None:
        path_cfg["rpiCameraFPS"] = body.fps
        changed = True
    if body.bitrate is not None:
        path_cfg["rpiCameraBitrate"] = body.bitrate
        changed = True

    if not changed:
        return {"status": "ok", "detail": "no changes"}

    MEDIAMTX_CONFIG.write_text(yaml.dump(cfg, default_flow_style=False))

    # Restart mediamtx to pick up new config
    proc = await run(["systemctl", "restart", "mediamtx"], timeout=15.0)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail="Config saved but mediamtx restart failed")

    return {"status": "ok", "detail": f"Updated {path_key} and restarted mediamtx"}
