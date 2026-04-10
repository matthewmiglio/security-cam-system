#!/usr/bin/env bash
# snapshot.sh — Pull a single JPEG frame from an RTSP camera stream.
# Usage: bash scripts/snapshot.sh [host] [output]
#   host    IP or hostname (default: 10.0.0.137)
#   output  Output file path (default: snapshot.jpg in current directory)
set -euo pipefail

HOST="${1:-10.0.0.137}"
PORT="${RTSP_PORT:-8554}"
PATH_NAME="${STREAM_PATH:-cam}"
OUTPUT="${2:-snapshot.jpg}"

RTSP_URL="rtsp://${HOST}:${PORT}/${PATH_NAME}"

ffmpeg -y -rtsp_transport tcp -i "$RTSP_URL" -frames:v 1 -q:v 2 -update 1 "$OUTPUT" 2>&1 \
  | tail -1

echo "Saved: $OUTPUT (from $RTSP_URL)"
