# HiFi Media Player

A professional touchscreen-friendly hi-fi media player built with Electron, React, and Tailwind CSS. Designed for DietPi x86 systems with 7-10" touchscreen displays.

![HiFi Media Player](https://img.shields.io/badge/platform-Electron-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> ## ⚠️ APPLIANCE ISO — DESTRUCTIVE, UNATTENDED INSTALL
>
> The appliance ISO (built under `distro/`) installs **fully unattended**. It does
> **NOT** ask where to install and does **NOT** ask for confirmation before
> formatting.
>
> - It automatically picks the **first disk it detects** (`list-devices disk | head -n1`)
>   and **wipes it entirely** (new GPT label, all existing partitions/data erased).
> - It then **reboots automatically** with no final prompt.
> - The installed system has root login enabled with a **default password (`hifi`)** —
>   change it on first boot.
>
> **Before booting the ISO on any machine, physically disconnect every drive you
> don't want erased.** "First detected disk" is not necessarily the one you expect
> (USB enumeration order, NVMe vs SATA, etc.). There is no undo and no confirmation
> screen. See [`distro/config/includes.installer/preseed.cfg`](distro/config/includes.installer/preseed.cfg).

## ✨ Features

- **Modern Hi-Fi Aesthetic**: Dark metallic theme with golden accents
- **Touch-Optimized UI**: Large buttons and intuitive gestures for 1024x600 displays
- **Lyrion Music Server front-end**: native browser for the local library, plus
  **Radio** and **Apps** tabs driven by Lyrion's own menus
- **Compatible with Lyrion plugins**: streaming and radio sources are provided by
  Lyrion plugins (e.g. Spotty for Spotify Connect, internet radio, YouTube,
  UPnP/DLNA, AirPlay) — install them from the Lyrion web UI and they appear in the
  Radio/Apps tabs. No separate per-service screens to maintain.
- **Simple Navigation**: home screen for source selection, each view loads independently
- **System Settings**: Network info, display controls, audio device selection
- **Clean Design**: Each source uses its native interface and controls

## 📋 Requirements

### System Requirements
- **OS**: DietPi x86, Debian 11+, or any modern Linux distribution
- **CPU**: x86_64 processor with good performance
- **RAM**: 2GB minimum, 4GB recommended
- **Display**: 1024x600 touchscreen (optimized for this resolution)

### Software Dependencies
- Node.js 18.x or higher
- npm 9.x or higher

## 🚀 Installation

### On Windows (for Development/Testing)

1. **Install Node.js**:
   - Download from [nodejs.org](https://nodejs.org/)
   - Install version 18.x LTS or higher
   - Verify installation:
   ```powershell
   node --version
   npm --version
   ```

2. **Navigate to project folder**:
   ```powershell
   cd path\to\hifi-media-player
   ```

3. **Run installation script**:
   ```powershell
   .\install-windows.bat
   ```
   
   Or manually:
   ```powershell
   npm install
   npm run build
   ```

4. **Start the application**:
   - Development mode: `.\start-dev.bat` or `npm run electron:dev`
   - Production mode: `.\start-prod.bat` or `npm run electron`

### On DietPi / Debian (Production Environment)

1. **Install Node.js and npm**:
```bash
# Update package list
sudo apt update

# Install Node.js and npm
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Verify installation
node --version
npm --version
```

2. **Install additional dependencies**:
```bash
# Install required system libraries for Electron
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
    libxcb-dri3-0
```

3. **Clone or download this project**:
```bash
cd ~
# If using git:
git clone <repository-url> hifi-media-player
# Or extract from archive
cd hifi-media-player
```

4. **Run installation script**:
```bash
chmod +x install-dietpi.sh
./install-dietpi.sh
```

Or manually:
```bash
npm install
npm run build
```

## 🎮 Running the Application

### On Windows

**Development Mode** (with hot-reload):
```powershell
# Using batch script
.\start-dev.bat

# Or directly
npm run electron:dev
```

**Production Mode**:
```powershell
# Using batch script
.\start-prod.bat

# Or manually
npm run build
npm run electron
```

### On Linux/DietPi

**Development Mode** (with hot-reload):
```bash
# Start Vite dev server and Electron
npm run electron:dev

# Or use the script
./start-fullscreen.sh
```

**Production Mode**:
```bash
# Build first
npm run build

# Then run
npm run electron
```

### Testing on Windows (1024x600 simulation)

To test the touchscreen interface on Windows:

1. **Resize the window** to 1024x600 manually, or
2. **Use browser DevTools**:
   - Open DevTools in Electron (automatically opened in dev mode)
   - Press `Ctrl+Shift+M` for responsive design mode
   - Set custom resolution: 1024 x 600
   - Enable touch simulation
3. **External monitor**: If you have a secondary monitor, set it to 1024x600 in Windows Display Settings

## 📦 Building for Distribution

To create a distributable package:

```bash
npm run package
```

The built application will be in the `dist/` directory.

## 🔧 Configuration

### Audio Backend Integration
The app includes IPC hooks for audio playback. To integrate with a media backend:

1. **Using MPV**:
```bash
sudo apt install mpv
# Integrate via IPC in main/main.js
```

2. **Using VLC**:
```bash
sudo apt install vlc
# Use VLC's HTTP interface or node-vlc
```

3. **Using PipeWire**:
```bash
sudo apt install pipewire pipewire-pulse
# Configure audio routing
```

### Lyrion Server Setup
1. Install Lyrion Music Server:
```bash
# Download from lyrion.org or use package manager
sudo apt install lyrionmusicserver
```

2. Configure server URL in app (default: `http://localhost:9000/material/`)

### Display Configuration for 1024x600

The app is optimized for 1024x600 resolution. To set your display:

```bash
# Check current resolution
xrandr

# Set resolution (replace HDMI-1 with your display)
xrandr --output HDMI-1 --mode 1024x600

# Make it permanent in /boot/config.txt or X11 config
```

### Fullscreen/Kiosk Mode

To run in fullscreen mode, edit `main/main.js` and change:

```javascript
fullscreen: true,  // Enable fullscreen
// or
kiosk: true,      // Enable kiosk mode (harder to exit)
```

### Auto-start on Boot

Create a systemd service:

```bash
sudo nano /etc/systemd/system/hifi-player.service
```

Add the following:

```ini
[Unit]
Description=HiFi Media Player
After=graphical.target

[Service]
Type=simple
User=dietpi
Environment=DISPLAY=:0
WorkingDirectory=/home/dietpi/hifi-media-player
ExecStart=/usr/bin/npm run electron
Restart=always

[Install]
WantedBy=graphical.target
```

Enable and start:

```bash
sudo systemctl enable hifi-player
sudo systemctl start hifi-player
```

## 📁 Project Structure

```
hifi-media-player/
├── main/                   # Electron main process
│   ├── main.js            # Main window and IPC handlers
│   └── preload.js         # Context bridge for security
├── src/                   # React application
│   ├── components/        # Reusable components
│   │   └── NavigationBar.jsx
│   ├── pages/            # Page components
│   │   ├── Settings.jsx   # System settings + OTA updates
│   │   ├── SetupWizard.jsx # First-run setup
│   │   └── LyrionServer.jsx # Lyrion front-end (Music / Radio / Apps)
│   ├── App.jsx           # Main app component
│   ├── main.jsx          # React entry point
│   └── index.css         # Global styles
├── index.html            # HTML template
├── package.json          # Dependencies and scripts
├── vite.config.js        # Vite configuration
├── tailwind.config.js    # Tailwind CSS configuration
├── postcss.config.js     # PostCSS configuration
├── install-windows.bat   # Windows installation script
├── start-dev.bat         # Windows dev mode script
├── start-prod.bat        # Windows production script
├── install-dietpi.sh     # DietPi installation script
├── start-fullscreen.sh   # Linux fullscreen startup script
├── README.md             # Full documentation (English)
└── GUIDA-RAPIDA.md       # Quick guide (Italian)
```

## 🎨 Customization

### Changing Theme Colors
Edit `tailwind.config.js`:

```javascript
colors: {
  'hifi-dark': '#0a0a0a',    // Main background
  'hifi-gray': '#1a1a1a',    // Secondary background
  'hifi-light': '#2a2a2a',   // Elevated elements
  'hifi-accent': '#3a3a3a',  // Borders
  'hifi-gold': '#d4af37',    // Primary accent
  'hifi-silver': '#c0c0c0',  // Secondary text
}
```

### Adding New Sources

Sources are not coded into the app — they come from **Lyrion plugins**. To add a
streaming service or radio source, install the matching plugin from the Lyrion
web UI (Settings → Plugins); it then shows up automatically under the **Radio**
or **Apps** tab of the Lyrion front-end. No UI changes or rebuilds required.

## 🔌 IPC API Reference

The app exposes these IPC methods for backend integration:

### System Info
```javascript
window.electronAPI.getSystemInfo()
// Returns: { hostname, platform, arch, version, electronVersion }

window.electronAPI.getNetworkInfo()
// Returns: [{ name, address, netmask }, ...]
```

### Playback Control
```javascript
window.electronAPI.playbackControl(action, data)
// Actions: 'play', 'pause', 'next', 'previous', 'seek'

window.electronAPI.setVolume(volume)
// volume: 0-100

window.electronAPI.setAudioDevice(deviceId)
// deviceId: string
```

## 🐛 Troubleshooting

### App doesn't start
- Check Node.js version: `node --version` (should be 18+)
- Reinstall dependencies: `rm -rf node_modules && npm install`
- Check Electron dependencies: `sudo apt install libgtk-3-0 libnss3`

### Lyrion front-end not loading
- Check the Lyrion server URL in Settings (default `http://localhost:9000`)
- Verify the Lyrion service is running and reachable on the network
- For missing streaming/radio sources, install the matching plugin in the Lyrion web UI

### Touch screen not responding
- Calibrate touch screen in DietPi settings
- Check if X11 touch drivers are installed
- Verify display configuration

### Audio not working
- Check ALSA/PulseAudio/PipeWire status
- Test with: `speaker-test -t wav -c 2`
- Verify audio device in Settings

## 📄 License

**The application code authored by this project** (Electron/React frontend, Python services, distro packaging, hardware designs) is released under the **MIT License** — see [`LICENSE`](LICENSE) for the full text.

**This project also includes and redistributes third-party components** under their own licenses (Lyrion Music Server and squeezelite under GPL, Android companion app under Apache-2.0, and npm/Python dependencies under MIT/BSD/ISC). Please see [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) for the complete list, license texts, and source locations.

**Disclaimer of Affiliation:** HiFi Media Player is an independent open-source project and is **NOT affiliated with, sponsored by, endorsed by, or officially associated with** the Lyrion Music Server project or the LMS-Community. The name "Lyrion" is used in a nominative sense only to describe the service that this frontend connects to.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues.

## 📧 Support

For issues and questions, please open a GitHub issue or consult the documentation.

---

**Built with ❤️ for music lovers**

