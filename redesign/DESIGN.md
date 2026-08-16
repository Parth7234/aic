---
name: Matcha Observability System
colors:
  surface: '#f9faf5'
  surface-dim: '#d9dad6'
  surface-bright: '#f9faf5'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4ef'
  surface-container: '#edeee9'
  surface-container-high: '#e7e9e4'
  surface-container-highest: '#e2e3de'
  on-surface: '#1a1c19'
  on-surface-variant: '#43483f'
  inverse-surface: '#2e312e'
  inverse-on-surface: '#f0f1ec'
  outline: '#73796e'
  outline-variant: '#c3c8bc'
  surface-tint: '#47663a'
  primary: '#47663a'
  on-primary: '#ffffff'
  primary-container: '#9dc08b'
  on-primary-container: '#314f25'
  inverse-primary: '#add19a'
  secondary: '#326a3c'
  on-secondary: '#ffffff'
  secondary-container: '#afecb2'
  on-secondary-container: '#356c3e'
  tertiary: '#52634c'
  on-tertiary: '#ffffff'
  tertiary-container: '#a9bca0'
  on-tertiary-container: '#3b4c36'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#c9edb5'
  primary-fixed-dim: '#add19a'
  on-primary-fixed: '#052100'
  on-primary-fixed-variant: '#304e24'
  secondary-fixed: '#b4f1b7'
  secondary-fixed-dim: '#99d59d'
  on-secondary-fixed: '#002108'
  on-secondary-fixed-variant: '#185126'
  tertiary-fixed: '#d4e8cb'
  tertiary-fixed-dim: '#b9ccb0'
  on-tertiary-fixed: '#101f0d'
  on-tertiary-fixed-variant: '#3a4b36'
  background: '#f9faf5'
  on-background: '#1a1c19'
  surface-variant: '#e2e3de'
  background-matcha-wash: '#EDF1E4'
  dimension-performance: '#7E90D2'
  dimension-cost: '#4FBCCF'
  dimension-responsibility: '#E6A15C'
  risk-high: '#E57373'
  risk-medium: '#FFB74D'
  risk-low: '#81C784'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  data-mono:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  sidebar-width: 320px
  detail-width: 380px
  gutter: 1.5rem
  card-padding: 1.25rem
  stack-gap: 1rem
---

## Brand & Style

The brand personality is rooted in "calm efficiency." While the product monitors high-stakes AI interactions, the UI acts as a soothing agent, transforming overwhelming real-time data into a peaceful, manageable experience. The target audience—Engineering Leads and Compliance Officers—requires high information density without the cognitive fatigue associated with traditional "emergency-red" dashboards.

This design system employs a **Minimalist-Glassmorphic** style. It moves away from the dark, heavy aesthetics of typical security tools toward an "Airy Zen" atmosphere. Key characteristics include:
- **Soft Materiality:** Using frosted glass effects and subtle inner glows to suggest depth.
- **Organic Tech:** Blending natural Matcha greens with structured, technical data visualization.
- **Breatheability:** Increased whitespace and soft-touch surfaces to reduce visual noise during 50+ daily check-ins.

## Colors

The palette is anchored by "Matcha Green," utilizing a range of botanical tones to replace harsh grays. 

- **Primary & Secondary:** Soft Matcha (#9DC08B) and Forest Sage (#609966) drive the brand identity.
- **Background Strategy:** We avoid pure white. Instead, use an off-white "Rice Paper" wash (#F8F9F4) and a slightly deeper "Matcha Wash" (#EDF1E4) for container backgrounds.
- **Dimension Accents:** The legacy Indigo, Cyan, and Amber are softened into Periwinkle, Seafoam, and Terracotta to fit the "peaceful" theme while maintaining semantic distinctness.
- **Risk Indicators:** Semantic colors (Red/Amber/Green) are retained for critical safety functions but used with lower saturation and higher lightness to prevent "alert fatigue."

## Typography

Typography establishes a hierarchy between "Operational UI" and "Raw AI Data."

- **UI Text (Inter):** Used for all navigation, headers, and descriptive text. It should feel invisible—functional and clear.
- **Data & Code (JetBrains Mono):** Reserved for technical dimensions, token counts, latency numbers, and the actual prompt/response text. This creates a clear visual distinction when the user is reading "about" the data versus reading "the" data itself.
- **Mobile Scaling:** Headers should drop by one tier (lg to md) on mobile devices to preserve horizontal space in the live feed.

## Layout & Spacing

The layout follows a **Fixed-Fluid-Fixed** model:
1.  **Sidebar (Fixed 320px):** Housing metrics and charts.
2.  **Live Feed (Fluid):** Expanding to fill the center, prioritizing readability.
3.  **Detail Panel (Fixed 380px):** Anchored to the right for deep inspection.

**Breakpoints:**
- **Desktop (>1200px):** Full 3-column view.
- **Tablet (768px - 1199px):** Sidebar collapses into a top drawer or hidden menu; Detail Panel becomes an overlay.
- **Mobile (<767px):** Single column view focusing on the Feed. Detail view occupies 100% of the viewport when active.

Spacing follows an 8px rhythmic grid to ensure alignment across the dense chart data and text-heavy feed items.

## Elevation & Depth

This system uses **Tonal Layering** and **Glassmorphism** rather than shadow-heavy skeuomorphism.

- **The Ground:** The main background is the softest Matcha wash.
- **Surface Level:** Cards and the Live Feed items use a semi-transparent white (glass) with a 12px backdrop-blur. 
- **Borders:** Instead of solid lines, use 1px inner-strokes in a slightly darker Matcha shade or a 10% opacity white to catch "light" at the edges.
- **Depth:** Higher elevation (like the Detail Panel or active Feed Item) is indicated by a very soft, diffused ambient shadow (color: `#40513B`, opacity: 0.05, blur: 20px) rather than a dark black shadow.

## Shapes

The shape language is "Softly Geometric."
- **Standard UI:** 0.5rem (8px) corners provide a modern feel that isn't overly "bubbly."
- **Interactive Elements:** Buttons and Input fields use the same 8px radius.
- **Specialty Shapes:** Gauge rings should have rounded caps. High-risk "flash" states should apply to the entire rounded container, creating a soft glowing perimeter rather than a sharp border.

## Components

- **Buttons:** Use a solid Matcha Green for primary actions. Ghost buttons with 1px borders for secondary actions. Micro-interactions should include a subtle scale-down (0.98) on click and a gentle lift on hover.
- **Cards (Feed Items):** Implement as glass containers. The "Risk Level" should be a vertical 4px bar on the far left of the card, with a matching very faint background tint across the whole card.
- **Gauges:** Instead of high-contrast rings, use "Matcha Tracks" (faint green) with "Dimension Accents" (Periwinkle/Seafoam/Terracotta) for the progress fill.
- **Chips/Badges:** Small, pill-shaped, using JetBrains Mono for the text. Low contrast (e.g., light green text on a slightly darker green background) to keep the UI "peaceful."
- **Input Fields:** Search and filters should be "inset" style—slightly darker than the background with a soft inner shadow to suggest they are carved into the interface.
- **Charts:** Chart.js configurations must use the named dimension colors with a 0.2 tension for "smooth" lines rather than jagged peaks.