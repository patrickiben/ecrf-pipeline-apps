#!/bin/sh
# Double-clickable macOS launcher for the Coding QC assist (Finder runs .command files in Terminal).
# Thin wrapper around run_meddra.sh, which does all the real work.
cd "$(dirname "$0")" && exec ./run_meddra.sh
