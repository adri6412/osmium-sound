// Mirrors THIRD-PARTY-NOTICES.md (repo root) in a structured form for the
// Settings UI. Keep the two in sync when a dependency is added/removed —
// the .md is the source handed out for legal/source-code requests, this is
// just its in-app rendering.
export const thirdPartyNotices = [
  {
    section: 'Bundled in the Appliance ISO',
    entries: [
      {
        name: 'Lyrion Music Server',
        version: '9.1.0 (pinned)',
        license: 'GPL-2.0+',
        notes: 'Downloaded on-demand and installed at first boot on the deployed system. Not bundled as a file in the ISO.',
        url: 'https://github.com/LMS-Community/slimserver/releases/tag/v9.1.0'
      },
      {
        name: 'squeezelite',
        version: 'Debian trixie',
        license: 'GPL-3.0+',
        notes: 'Audio playback engine. Installed from official Debian repositories.'
      },
      {
        name: 'cdparanoia, icedax, libcdio-utils',
        version: 'Debian trixie',
        license: 'GPL-2.0, GPL-3.0',
        notes: 'CD reading support. Installed from official Debian repositories.'
      },
      {
        name: 'Qt 6 (qtbase, qtdeclarative, Qt Quick modules, plugins)',
        version: 'Debian trixie',
        license: 'LGPL-3.0',
        notes: 'Runtime of the on-screen interface. Unmodified Debian shared libraries, dynamically linked.',
        url: 'https://www.qt.io/licensing/open-source-lgpl-obligations'
      },
      {
        name: 'libdrm',
        version: 'Debian trixie',
        license: 'MIT',
        notes: 'Display mode setting (DRM/KMS).'
      },
      {
        name: 'DejaVu fonts, Noto CJK fonts',
        version: 'Debian trixie',
        license: 'Bitstream Vera / OFL-1.1',
        notes: 'Interface typeface and CJK glyphs.'
      },
      {
        name: 'Debian base system, kernel, firmware',
        version: 'trixie (Debian 13)',
        license: 'Various (GPL/BSD/firmware EULAs)',
        notes: 'Installed from official Debian repositories.'
      }
    ]
  },
  {
    section: 'Android Companion App',
    entries: [
      {
        name: 'android-squeezer (rebranded)',
        license: 'Apache-2.0',
        notes: 'Rebranded as "Osmium Sound Companion" for remote control. Copyright Kurt Aaholst, Google Inc. Full license text in android-companion/docs/LICENSE.md.',
        url: 'https://github.com/kaaholst/android-squeezer'
      },
      {
        name: 'OkHttp',
        license: 'Apache-2.0',
        url: 'https://square.github.io/okhttp/'
      },
      {
        name: 'ZXing Android Embedded',
        license: 'Apache-2.0',
        url: 'https://github.com/journeyapps/zxing-android-embedded'
      },
      {
        name: 'CometD Java Client',
        license: 'Apache-2.0',
        url: 'https://github.com/cometd/cometd'
      },
      {
        name: 'SLF4J Android',
        license: 'MIT',
        url: 'https://www.slf4j.org/'
      },
      {
        name: 'ckChangeLog',
        license: 'Apache-2.0',
        url: 'https://github.com/cketti/ckChangeLog'
      },
      {
        name: 'RecyclerView-FastScroller',
        license: 'Apache-2.0',
        url: 'https://github.com/quiph/RecyclerView-FastScroller'
      },
      {
        name: 'AndroidX libraries & Material Components',
        notes: 'core, palette, webkit, appcompat, activity, preference, media',
        license: 'Apache-2.0',
        url: 'https://developer.android.com/jetpack/androidx'
      }
    ]
  },
  {
    section: 'On-screen Interface (Qt)',
    entries: [
      { name: 'Lucide icons', license: 'ISC', notes: 'SVG icons generated from lucide-react 0.294.', url: 'https://lucide.dev' }
    ]
  },
  {
    section: 'Earlier Electron Kiosk (npm)',
    entries: [
      { name: 'React, react-dom', license: 'MIT' },
      { name: 'react-use-websocket', license: 'MIT' },
      { name: 'qrcode.react', license: 'MIT' },
      { name: 'framer-motion', license: 'MIT' },
      { name: 'lucide-react', license: 'ISC' },
      { name: 'simple-keyboard', license: 'MIT' },
      { name: 'Electron', license: 'MIT' }
    ]
  },
  {
    section: 'Python Service Dependencies',
    entries: [
      { name: 'Flask', license: 'BSD-3-Clause', notes: 'Web framework for API and settings server.' },
      { name: 'flask-cors', license: 'MIT', notes: 'Cross-origin request support.' },
      { name: 'psutil', license: 'BSD-3-Clause', notes: 'System monitoring for VU meter and CPU stats.' },
      { name: 'websockets', license: 'BSD-3-Clause', notes: 'WebSocket support.' }
    ]
  }
];
