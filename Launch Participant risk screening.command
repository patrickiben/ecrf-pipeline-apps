#!/bin/sh
# Double-clickable macOS launcher for Participant risk screening (Finder runs .command files in Terminal).
# Thin wrapper around run_risk.sh, which does all the real work.
cd "$(dirname "$0")" && exec ./run_risk.sh
