#!/bin/bash
# Start Osmium Sound in fullscreen mode
# Optimized for 1024x600 touchscreen

# Set display resolution to 1024x600
xrandr --output HDMI-1 --mode 1024x600 2>/dev/null || \
xrandr --output LVDS-1 --mode 1024x600 2>/dev/null || \
xrandr --output eDP-1 --mode 1024x600 2>/dev/null || \
echo "⚠️  Could not set resolution automatically. Please set manually."

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Hide cursor after 5 seconds of inactivity (optional)
# unclutter -idle 5 &

# Start the application
cd "$(dirname "$0")"
npm run electron

