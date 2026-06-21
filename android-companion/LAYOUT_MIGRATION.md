# Layout Migration - Desktop-Inspired Mobile UI

## Overview

The Android companion app has been completely restructured to mirror the desktop HiFi Media Player interface, while maintaining mobile-friendly interaction patterns and responsive design.

## Major Changes

### 1. Now Playing Panel (Top 50-60%)

**File**: `now_playing_fragment_full.xml`

Reorganized to match desktop layout:

```
┌─────────────────────────────────┐
│   HiFi Media Player Companion   │
├─────────────────────────────────┤
│                                 │
│         [Artwork]               │
│         (Square, centered)      │
│                                 │
│  Track Title                    │
│  Artist (Gold)                  │
│  Album (Gray)                   │
│                                 │
│  ──●──────────── (Progress)     │
│  0:00        2:45               │
│                                 │
│  [ Prev ] [  ▶  ] [ Next ]      │
│           (Gold, Large)         │
│                                 │
│  🔊 ─●──────── Volume           │
│            75                    │
│                                 │
└─────────────────────────────────┘
```

#### Key Components:
- **Artwork**: Square, max-width constrained (320dp), centered
- **Track Info**: 
  - Title: 18sp bold white
  - Artist: 14sp gold (#D4AF37)
  - Album: 12sp gray (#808080)
- **Progress Bar**: Material Slider with current/total time
- **Transport Controls**: 
  - Previous: 48dp outlined button, gold icons
  - Play/Pause: 64dp solid button, gold background, black icon (primary focus)
  - Next: 48dp outlined button, gold icons
- **Volume Control**: Icon + slider + percentage

### 2. Library Browser (Bottom 40-50%)

**File**: `home_group.xml`

Added desktop-like navigation and browsing:

```
┌─────────────────────────────────┐
│ Musica │ Radio │ App/CD │ Impo. │ (Tab Bar)
├─────────────────────────────────┤
│ [Home] › Musica › Artists      ← Breadcrumb
├─────────────────────────────────┤
│                                 │
│ • Beatles                   ▶   │
│ • Pink Floyd               ▶   │
│ • David Bowie              ▶   │
│ • The Who                  ▶   │
│                                 │
│ (Scrollable RecyclerView)      │
│                                 │
└─────────────────────────────────┘
```

#### Key Components:
- **Tab Bar**: 
  - Horizontal MaterialTabLayout at top
  - Tabs: Musica, Radio, App/CD, Impostazioni
  - Selected indicator: Gold bottom border (3dp)
  - Height: 48dp
  - Scrollable on narrow screens

- **Breadcrumb Navigation**:
  - Home icon on left
  - Navigation path (Home › Category › Item)
  - Back button on right (conditional)
  - Height: 40dp

- **Content Area**:
  - RecyclerView with library items
  - List items with icons and text
  - Tap to navigate or play

### 3. Color & Styling

**Applied throughout**:
```
Background:      #0a0a0a (deep black)
Surfaces:        #1a1a1a, #2a2a2a, #3a3a3a (grays)
Primary Accent:  #D4AF37 (gold)
Text:            #ffffff (white)
Secondary Text:  #808080 (gray)
Dividers:        #2a2a2a
```

**Component-specific**:
- Play/Pause button: Gold background with black icon
- Volume slider: Gold active track, gray inactive
- Tab indicator: Gold
- Selected tab text: Gold
- Inactive elements: Gray with hover effects

## Layout Structure

### Vertical Arrangement (Mobile)
```
Now Playing Section (Top)     [50-60% height]
├── Artwork
├── Track Info
├── Progress
├── Transport Controls
└── Volume

Library Section (Bottom)       [40-50% height]
├── Tab Bar
├── Breadcrumb
└── Content (RecyclerView)
```

### Responsive Behavior

**Portrait (default)**:
- Single column, vertical layout
- Artwork: Constrained width (max 320dp)
- Full-width controls

**Landscape (optional)**:
- Could support 2-column if beneficial
- Artwork positioned left, controls right
- Library browser optimized for wider screens

## Implementation Notes

### Files Modified
1. `now_playing_fragment_full.xml` - Main now playing layout
2. `home_group.xml` - Library browser with tabs

### Files to Review/Update
- Layout item views (list_item.xml, grid_item.xml)
- Fragment code (now playing + library browser Java/Kotlin)
- Material components dependencies
- Icon drawables (ic_action_previous, ic_action_next, ic_action_play, etc.)

### Dependencies Required
```gradle
implementation 'com.google.android.material:material:1.13.0'
```

### Drawable Resources Needed
- `ic_action_previous` - Skip back icon
- `ic_action_next` - Skip forward icon
- `ic_action_play` - Play icon
- `ic_action_volume` - Volume icon
- `ic_home` - Home icon
- `ic_arrow_back` - Back icon

All should be:
- 24dp icons
- Single color (will be tinted programmatically)
- Vector drawables preferred

## Migration Checklist

- [ ] Verify `now_playing_fragment_full.xml` layout renders correctly
- [ ] Test artwork sizing and centering
- [ ] Verify transport controls touch targets (48dp minimum)
- [ ] Test play/pause button (64dp) styling
- [ ] Verify volume slider interaction
- [ ] Test tab bar navigation
- [ ] Verify breadcrumb navigation updates
- [ ] Test library item selection and playback
- [ ] Verify colors match HiFi theme
- [ ] Test on multiple screen sizes (4", 5.5", 6.5", 7")
- [ ] Test in portrait and landscape
- [ ] Verify responsive layout adjustments
- [ ] Test all tap and long-press interactions
- [ ] Performance test with large lists
- [ ] Test theme color application (dark mode)

## Future Enhancements

1. **Swipe gestures**: Swipe left/right to skip tracks
2. **Landscape optimization**: Proper layout for landscape orientation
3. **Tablet support**: 2-column layout for screens ≥ 600dp
4. **Gesture controls**: Double-tap to play, pinch for volume
5. **Animations**: Smooth transitions between tabs
6. **Quick access**: Favorites or recently played shortcut
7. **Settings integration**: Persist user preferences

## Desktop vs Mobile Comparison

| Aspect | Desktop | Mobile |
|--------|---------|--------|
| Left Panel | Now Playing (340px) | Top Section (50-60%) |
| Right Panel | Library Tabs (684px) | Bottom Section (40-50%) |
| Navigation | Vertical Sidebar | Horizontal Tabs |
| Artwork | Large square | Constrained square |
| Controls | Centered column | Horizontal row |
| Volume | Slider in panel | Slider in controls |
| Library | Full tree view | RecyclerView list |
| Orientation | Landscape (1024x600) | Portrait (primary) |

---

**Last Updated**: 2026-06-21  
**Status**: Layout restructuring complete  
**Next Phase**: Implementation and testing
