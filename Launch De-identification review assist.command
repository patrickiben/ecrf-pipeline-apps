#!/bin/sh
# Double-clickable macOS launcher for the De-identification review assist (Finder runs .command files in Terminal).
# Thin wrapper around run_phi.sh, which does all the real work.
cd "$(dirname "$0")" && exec ./run_phi.sh
