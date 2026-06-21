# HiFi Media Player Companion - Android Design Guidelines

## Design Philosophy

The Android companion app mirrors the desktop HiFi Media Player interface while being optimized for mobile/tablet screens. The design emphasizes clarity, responsive touch interaction, and a premium hi-fi aesthetic.

## Color Palette

### Primary Colors
- **Background Dark**: `#0a0a0a` - Deep black for main backgrounds
- **Surface Dark**: `#1a1a1a` - Primary surface color
- **Surface Medium**: `#2a2a2a` - Secondary surface color
- **Surface Light**: `#3a3a3a` - Tertiary surface color

### Accent Colors
- **Gold Primary**: `#D4AF37` - Main accent color (buttons, highlights)
- **Gold Light**: `#FFD700` - Lighter variant for hover states
- **White**: `#ffffff` - Text and icons on dark backgrounds

### Interactive States
- Hover/Focus: Use `#FFD700` (Gold Light)
- Active/Pressed: Use `#D4AF37` (Gold Primary) with reduced opacity
- Disabled: Use `#3a3a3a` with 50% opacity

## Typography

### Font Family
- **Primary**: System font stack: `'Segoe UI', 'Roboto', 'Ubuntu', 'Helvetica Neue', sans-serif`
- **Monospace** (for time displays): System monospace

### Font Sizes & Weights
- **Display/Header**: 32-48sp, bold
- **Title/Section**: 20-24sp, semibold
- **Body/Content**: 14-16sp, regular
- **Caption/Helper**: 12sp, regular
- **Small Text**: 11sp, regular

## Component Styling

### Buttons
- **Primary Button**: Gold background with black text
- **Secondary Button**: Dark gray background with white text
- **Icon Button**: No background, gold icon
- **Minimum Touch Target**: 48dp x 48dp
- **Corner Radius**: 8-12dp

### Surfaces/Cards
- **Border**: 1px, color `#3a3a3a`
- **Corner Radius**: 8-12dp
- **Elevation/Shadow**: Subtle, depth-based
- **Padding**: 16dp (standard), 12dp (compact)

### Input Fields
- **Background**: `#1a1a1a`
- **Border**: 1px `#3a3a3a`, focused: `#D4AF37`
- **Text Color**: `#ffffff`
- **Placeholder**: `#808080`
- **Corner Radius**: 8dp

### List Items
- **Height**: 48-56dp (minimum touch height)
- **Padding**: 16dp horizontal, 12dp vertical
- **Divider**: 1px `#2a2a2a`
- **Selected State**: Background `#2a2a2a` with left border accent

## Layout Grid

### Mobile (Portrait)
- **Width**: Full width minus safe area margins
- **Margins**: 12-16dp sides
- **Column Structure**: Single column, stack all content vertically

### Tablet (Landscape)
- **Width**: Responsive 2-3 column layout
- **Margins**: 24-32dp sides
- **Grid**: 2-column for content, sidebar for navigation (optional)

## Dark Mode
- The app uses a dark-first approach
- All colors are optimized for dark environments
- No light theme variant needed (unless explicitly requested)

## Navigation Patterns

### Tab Bar (Mobile - Desktop-like)
- Horizontal tab bar at top: **Musica, Radio, App/CD, Impostazioni**
- Active indicator: Gold (#D4AF37) bottom border (3dp height)
- Selected text: Gold (#D4AF37)
- Inactive text: Gray (#808080)
- Height: 48dp
- Scrollable on small screens
- **Matches desktop layout structure**

### Breadcrumb Navigation
- Shows current location in hierarchy
- Home button (icon) on left
- Navigation path in center
- Back button on right (when applicable)
- Height: 40dp
- Divider below: 1px #2a2a2a

## Responsive Behavior

### Phone Screens (< 600dp)
- Single column layout
- Full-width controls
- Bottom navigation
- Stacked modals/dialogs

### Tablet Screens (≥ 600dp)
- 2-3 column layout
- Side-by-side panels
- Top app bar with navigation
- Expanded controls and spacing

## Animations & Transitions

- **Duration**: 200-300ms for normal transitions
- **Easing**: Material Curves (standard: ease-out)
- **Gesture Feedback**: Scale 0.95x on press, restore on release
- **List Animations**: Fade-in on load, slide-in for new items

## Accessibility

- **Contrast Ratio**: Minimum 4.5:1 (text on background)
- **Touch Targets**: Minimum 48x48dp
- **Focus Indicators**: Clear visual focus state (border or background change)
- **Content Descriptions**: All interactive elements have descriptive labels

## Mobile Optimization

- **Orientation**: Support portrait and landscape (if beneficial)
- **Notch/Inset**: Respect safe areas
- **Virtual Keyboard**: Account for keyboard height in layouts
- **Performance**: Optimize for 60fps scrolling

## Desktop-to-Mobile Adaptation

The companion app **mirrors the desktop layout structure** but optimized for smartphone screens:

### Desktop Layout (1024x600)
- **Left Panel (340px)**: Now Playing (Artwork + Controls)
- **Right Panel (684px)**: Tabs + Library Browser

### Mobile Layout (Smartphone)
- **Top Section (50-60%)**: Now Playing Panel
  - Artwork (square, constrained width)
  - Track info (title, artist, album)
  - Progress bar with time
  - Transport controls (Previous - Play/Pause (large gold) - Next)
  - Volume slider
  
- **Bottom Section (40-50%)**: Library + Browsing
  - Horizontal Tab Bar (Musica, Radio, App/CD, Impostazioni)
  - Breadcrumb navigation
  - Scrollable library list

### Key Differences from Desktop

1. **Layout**: Vertical stack (top/bottom) instead of side-by-side panels
2. **Navigation**: Horizontal tab bar instead of vertical sidebar
3. **Controls**: Touch-friendly sizes (48dp minimum for buttons)
4. **Artwork**: Constrained width for readability on narrow screens
5. **Typography**: Optimized for mobile screens
6. **VU Meter**: **Excluded** - not suitable for mobile
7. **Spacing**: Responsive padding based on screen width

### Core Design Philosophy
**Same visual hierarchy and control placement as desktop**, adapted for vertical mobile screens and touch interaction.

## Implementation Notes

- Use Material Design 3 components where applicable
- Apply HiFi theme colors through theme attributes
- Ensure responsive layouts with ConstraintLayout
- Test on multiple screen sizes (4", 5.5", 7", 10")
- Optimize for landscape orientation on tablets

## References

- Desktop UI: HiFi Media Player React/Tailwind CSS
- Material Design 3: https://m3.material.io/
- Android Design System: https://developer.android.com/design
