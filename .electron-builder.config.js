/**
 * Electron Builder configuration
 * For creating distributable packages
 */
module.exports = {
  appId: 'com.hifi.mediaplayer',
  productName: 'Osmium Sound',
  directories: {
    output: 'dist',
    buildResources: 'assets'
  },
  files: [
    'main/**/*',
    'renderer-dist/**/*',
    'package.json'
  ],
  linux: {
    target: [
      {
        target: 'deb',
        arch: ['x64']
      },
      {
        target: 'AppImage',
        arch: ['x64']
      }
    ],
    category: 'AudioVideo',
    icon: 'assets/icon.png',
    executableName: 'hifi-media-player',
    desktop: {
      Name: 'HiFi Media Player',
      Comment: 'Touchscreen Hi-Fi Media Player',
      Categories: 'AudioVideo;Audio;Player;',
      Terminal: false,
      Type: 'Application'
    }
  },
  win: {
    target: 'nsis',
    icon: 'assets/icon.ico'
  },
  mac: {
    target: 'dmg',
    icon: 'assets/icon.icns',
    category: 'public.app-category.music'
  }
};

