#!/bin/bash
set -e

# Install prerequisites
apt install -y libxcb-xinerama0 libxcb-cursor0 libnss3 zstd

# Download Anki 25.09
cd /tmp
wget -nc https://github.com/ankitects/anki/releases/download/25.09/anki-launcher-25.09-linux.tar.zst

# Extract and install
tar xaf anki-launcher-25.09-linux.tar.zst
cd anki-launcher-25.09-linux
./install.sh

echo "Anki installed successfully! Run 'anki' to launch."
