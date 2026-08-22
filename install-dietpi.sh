#!/bin/bash
# Osmium Sound - Installation script for DietPi/Debian
# Optimized for 1024x600 touchscreen displays

set -e

echo "=========================================="
echo "  Osmium Sound - DietPi Installer"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
   echo "⚠️  Please do not run as root. Run as normal user (dietpi)."
   exit 1
fi

# Update package list
echo "📦 Updating package list..."
sudo apt update

# Install Node.js if not present
if ! command -v node &> /dev/null; then
    echo "📥 Installing Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
    sudo apt install -y nodejs
else
    echo "✅ Node.js already installed ($(node --version))"
fi

# Install required system libraries for Electron
echo "📚 Installing Electron dependencies..."
sudo apt install -y \
    libgtk-3-0 \
    libnotify4 \
    libnss3 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    libatspi2.0-0 \
    libdrm2 \
    libgbm1 \
    libxcb-dri3-0 \
    xserver-xorg \
    xinit \
    x11-xserver-utils

# Install project dependencies
echo "📦 Installing npm dependencies..."
npm install

# Build the application
echo "🔨 Building the application..."
npm run build

echo ""
echo "✅ Installation complete!"
echo ""
echo "📱 Your display resolution: $(xrandr | grep '*' | awk '{print $1}' | head -1)"
echo ""
echo "To run the application:"
echo "  Development mode: npm run electron:dev"
echo "  Production mode:  npm run electron"
echo ""
echo "To set 1024x600 resolution:"
echo "  xrandr --output HDMI-1 --mode 1024x600"
echo ""
echo "To enable auto-start on boot, see README.md"
echo ""

