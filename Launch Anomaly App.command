#!/bin/sh
# Double-clickable launcher for macOS (Finder runs .command files in Terminal).
# Thin wrapper around run_anomaly.sh, which does all the real work.
cd "$(dirname "$0")" && exec ./run_anomaly.sh
