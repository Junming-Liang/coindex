# coindex Design System · 1.8

## References and adaptation

Based on [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md), pinned at `c7c1bada4eda972236d124e06ee58df129a9266b`. MIT reference files and provenance are in `design/reference/`.

- Linear: restrained lavender accent, neutral surface hierarchy, thin borders, compact controls, 4-point spacing.
- Apple: native SF typography, system appearance, readable utility controls.
- Both documents analyze marketing websites. coindex adapts their visual principles to a native task workspace: no hero sections, oversized type, decorative charts, or website navigation. Light mode is a deliberate product adaptation requested by the user.

## Product priorities

Task title states the overall goal. Current progress / stopped point and the next action remain separate, visible lines. Conversation and host metadata are secondary. Task behavior, manual titles, completion state, scheduling, nudge receipts, and pet preferences are preserved.

## Color tokens

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| Canvas | #F7F8FA | #101113 | Task workspace |
| Surface | #FFFFFF | #191A1E | Cards, details, sheets |
| Sidebar | #EFF0F4 | #141519 | Navigation |
| Subtle | #F2F3F7 | #212228 | Progress panel / inputs |
| Border | #E1E3EB | #303139 | Hairline separation |
| Ink | #20212B | #F3F3F7 | Primary text |
| Muted | #676A79 | #A4A7B5 | Metadata |
| Accent | #555FC9 | #A3AAFF | Selection, links, focus |
| Action fill | #5862CC | #5862CC | White text primary button |
| Accent wash | #E5E7FA | #2B2D46 | Selected navigation |

Appearance follows macOS dynamically. Semantic blue, amber, green and purple are limited to task state, connection state and warnings; every state also has a text label or symbol.

## Typography and geometry

Use system SF fonts. Page titles 25/600; detail titles 22/600; task titles 16/600; body 12–13/400; sidebar and controls 12/400–600; metadata 10–11. Monospaced numerals for counts; monospaced text only for paths/diagnostics. Headlines have slight negative tracking.

Sidebar 216pt, optional detail pane 332pt; default window 1200×820, minimum 960×660. Main content padding 20pt; card padding 16pt; card gap 12pt. Radii: chip 5, control 7–8, panel 9, card 12. Border 1pt; selection 1.5pt. Minimal shadows, confined to transient toast and app icon.

## Interaction

Primary button: new task / save / complete. Secondary controls: update, nudge, copy. Buttons, icon actions, sidebar rows and text actions use hover fills and a pointing-hand cursor. Disabled actions suppress hover/cursor feedback. Press feedback respects Reduce Motion. Hover borders distinguish interactive task cards, keyboard focus is visible, disabled controls retain their state. Search and host filtering show the visible result count. No-result state offers clear-search action. Existing keyboard shortcuts and accessibility identifiers remain available.

## Brand

## Optional task map

Keep the list as the default workspace and add an independent task-map navigation entry. Group related goals into aligned sections with uniform cards, compact grid spacing and original goal titles. Progression chains share a row where possible; links use shared horizontal/vertical routes, never curved or diagonal paths. Use solid arrows for progression and quiet dashed lines for thematic relationships. Preserve task state and fixed titles; analysis only annotates a separate cache. Search, fit-to-window, zoom and read-only details must work on both clients. macOS follows the existing light/dark palette; Ubuntu uses its established Tk theme.

Original open C plus forward check mark, drawn from one shared normalized vector path in `Sources/BrandGeometry.swift`. The sidebar, app icon and monochrome menu bar icon share that geometry. The app icon uses a restrained indigo tile and is rendered at all native macOS sizes. No third-party logo or pet artwork is copied for the new brand.

## Verification

Build the native app; run existing behavior regressions. Visually inspect isolated light and dark demo bundles, selected detail, empty search, title/manual editor, settings, and pet gallery. Install with the existing transactional updater, which backs up and compares all persisted rows and pet preferences before and after replacement.

## Linux workspace

The Tk frontend applies the same Linear and Apple references to a light desktop workspace. The palette is defined in `linux/palette.py`, and native ttk states, rounded surfaces, and line icons live in `linux/design.py`. Use an installed sans font with Chinese coverage; keep body text readable at 10–12 points and reserve 16–19 points for titles.

The 208px sidebar groups tasks by their actual state and shows counts from the current snapshot. Selected navigation uses a quiet lavender fill. The main header contains the page title and primary action; connection and analysis notices occupy a separate status line. Search and source filtering sit above the task list, with a visible result count and a clear-filter action in empty search results.

Task cards use 12px corners, a 1px edge, 16px internal padding, and 12px gaps. A small state badge and source precede the title. Current progress is secondary text; the next action has its own subtle surface and arrow. The selected card keeps a lavender outline. The 340px detail pane puts completion and opening the original conversation first, followed by progress, next action, evidence, and receipts. Task actions retain their existing state and authorization rules.

Buttons use 6px rounded image surfaces with hover, pressed, disabled, and visible keyboard-focus states while retaining native ttk behavior. Search has one outer focus edge. Settings use separate white sections for local connection, model, schedule, and SSH sources, with a persistent save footer. Forms remain open when validation fails. Mouse-wheel scrolling works in the list, detail pane, and settings; keyboard search and task creation use Ctrl+F and Ctrl+N.

Verify fictional-data rendering at the minimum 1000×680 and normal 1240×820 sizes, navigation and search selection, long task content, demo mutation restrictions, settings validation, and the existing service/connection/nudge regressions before installing.
