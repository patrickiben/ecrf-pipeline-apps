#!/bin/sh
# Double-clickable macOS launcher for Central statistical monitoring (Finder runs .command files in Terminal).
# Thin wrapper around run_anomaly.sh, which does all the real work.
cd "$(dirname "$0")" && exec ./run_anomaly.sh
