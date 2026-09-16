# design.md

Design spec reverse-engineered from the Zenith shadcn CRM dashboard
(`zenith-shadcn.dashboardpack.com/crm`). Everything below was pulled from the
live page's computed styles and class strings, so the values are exact rather
than eyeballed.

Use this as the reference when building the dashboard. Match the tokens and the
component recipes and it will read as the same design system.

---

## 1. Stack

| Piece | What it uses |
|---|---|
| Framework | Next.js (App Router) |
| CSS | Tailwind v4 (CSS-first config, `@theme`) |
| Components | shadcn/ui (`data-slot` attributes on every primitive) |
| Fonts | Geist Sans (body), Geist Mono (numeric/code), Figtree (loaded, secondary) |
| Icons | Lucide, rendered at 16px and 20px |
| Charts | Recharts (area, donut, bar) |
| Color space | OKLCH for every single token |

The root element carries state as classes, which is worth copying:

```html
<html class="light density-comfortable layout-sidebar container-fluid dir-ltr">
```

Theme, density, layout mode, container width, and direction are all swappable at
the root. If you want the same flexibility, put them there rather than in React
state scattered through components.

---

## 2. Color tokens

Pure neutral grayscale for the UI (chroma is literally `0` on every surface
token), with color reserved almost entirely for data and status. That restraint
is the single biggest reason it looks expensive. Do not add a brand tint to the
surfaces.

### Light

```css
:root {
  --background:            oklch(100%   0 0);
  --foreground:            oklch(14.5%  0 0);

  --card:                  oklch(100%   0 0);
  --card-foreground:       oklch(14.5%  0 0);
  --popover:               oklch(100%   0 0);
  --popover-foreground:    oklch(14.5%  0 0);

  --primary:               oklch(20.5%  0 0);   /* near-black, not a brand color */
  --primary-foreground:    oklch(98.5%  0 0);
  --secondary:             oklch(96.5%  0 0);
  --secondary-foreground:  oklch(20.5%  0 0);
  --muted:                 oklch(96.5%  0 0);
  --muted-foreground:      oklch(55.6%  0 0);
  --accent:                oklch(96.5%  0 0);
  --accent-foreground:     oklch(20.5%  0 0);

  --destructive:           oklch(57.7%  0.245 27.325);
  --destructive-foreground:oklch(98.5%  0 0);
  --success:               oklch(62%    0.17  145);
  --success-foreground:    oklch(98.5%  0 0);

  --border:                oklch(92.2%  0 0);
  --input:                 oklch(92.2%  0 0);
  --ring:                  oklch(70.8%  0 0);

  --sidebar:                       oklch(98.5% 0 0);
  --sidebar-foreground:            oklch(14.5% 0 0);
  --sidebar-primary:               oklch(20.5% 0 0);
  --sidebar-primary-foreground:    oklch(98.5% 0 0);
  --sidebar-accent:                oklch(96.5% 0 0);
  --sidebar-accent-foreground:     oklch(20.5% 0 0);
  --sidebar-border:                oklch(92.2% 0 0);
  --sidebar-ring:                  oklch(70.8% 0 0);

  --chart-1: oklch(64.6% 0.222 41.116);   /* orange  */
  --chart-2: oklch(60%   0.118 184.704);  /* teal    */
  --chart-3: oklch(39.8% 0.07  227.392);  /* deep blue */
  --chart-4: oklch(82.8% 0.189 84.429);   /* amber   */
  --chart-5: oklch(76.9% 0.188 70.08);    /* orange-amber */
}
```

### Dark

Note the dark theme is not a simple inversion. The page background goes darker
than the cards, so cards float above it. The chart ramp is also swapped out
entirely for higher-chroma hues that survive on a dark ground.

```css
.dark {
  --background:            oklch(7.5% 0 0);   /* darker than the cards */
  --foreground:            oklch(98.5% 0 0);

  --card:                  oklch(19%   0 0);  /* lifted above background */
  --card-foreground:       oklch(98.5% 0 0);
  --popover:               oklch(21%   0 0);  /* lifted above the cards */
  --popover-foreground:    oklch(98.5% 0 0);

  --primary:               oklch(92.2% 0 0);  /* inverts to near-white */
  --primary-foreground:    oklch(20.5% 0 0);
  --secondary:             oklch(23.5% 0 0);
  --secondary-foreground:  oklch(98.5% 0 0);
  --muted:                 oklch(23.5% 0 0);
  --muted-foreground:      oklch(55.6% 0 0);  /* unchanged from light */
  --accent:                oklch(23.5% 0 0);
  --accent-foreground:     oklch(98.5% 0 0);

  --destructive:           oklch(57.7% 0.245 27.325);  /* unchanged */
  --success:               oklch(62%   0.17  145);     /* unchanged */

  --border:                oklch(28%   0 0);
  --input:                 oklch(28%   0 0);
  --ring:                  oklch(55.6% 0 0);

  --sidebar:               oklch(11%   0 0);  /* between bg and card */
  --sidebar-foreground:    oklch(98.5% 0 0);

  --chart-1: oklch(48.8% 0.243 264.376);  /* blue   */
  --chart-2: oklch(69.6% 0.17  162.48);   /* green  */
  --chart-3: oklch(76.9% 0.188 70.08);    /* amber  */
  --chart-4: oklch(62.7% 0.265 303.9);    /* purple */
  --chart-5: oklch(64.5% 0.246 16.439);   /* pink-red */
}
```

### Rules for using color

- Surfaces, text, borders, and buttons: grayscale only.
- `--primary` is near-black in light and near-white in dark. The primary button
  is a black pill, not a blue one.
- Deltas and status: `--success` for positive, `--destructive` for negative.
  Nothing else gets a semantic color.
- Charts and category dots: `--chart-1` through `--chart-5`, in order.
- Tinted backgrounds are always the token at low alpha, never a separate token:
  `bg-chart-1/10`, `hover:bg-sidebar-accent/50`, `hover:border-primary/20`.

---

## 3. Radius, spacing, and other tokens

```css
--radius:        0.625rem;  /* 10px, the base */
--radius-xs:     0.125rem;
--card-padding:  1.25rem;   /* 20px */
--table-row-height: 2.75rem;
--table-cell-py: 0.5rem;
--spacing-unit:  1;
```

Resolved radius in practice:

| Usage | Class | Computed |
|---|---|---|
| Cards | `rounded-xl` | 14px |
| Buttons, nav items, logo tile | `rounded-lg` | 10px |
| Icon tiles inside cards | `rounded-xl` | 14px |
| Pills, avatars, category dots | `rounded-full` | full |

Spacing is a 4px scale. Gaps you will actually use: `gap-1.5` (6px) for a value
and its delta, `gap-3` (12px) for icon-plus-label, `gap-4` (16px) between grid
cards, `mt-6` (24px) between major row groups.

---

## 4. Typography

Body is Geist Sans at 16px base. The scale is tight and there is heavy reliance
on `tracking-tight` at the top end and `tracking-widest` at the very bottom end.

| Role | Classes | Computed |
|---|---|---|
| Page title | `text-2xl font-bold tracking-tight` | 24px / 700 / -0.6px |
| KPI value | `text-2xl font-bold tracking-tight` | 24px / 700 / -0.6px |
| Card title | `text-base font-semibold tracking-tight` | 16px / 600 |
| Card description | `text-sm text-muted-foreground` | 14px / 400 |
| Table cell | `text-sm font-medium` | 14px / 500 |
| Table header | `text-xs font-medium text-muted-foreground` | 12px / 500 |
| KPI label | `text-xs font-medium text-muted-foreground` | 12px / 500 |
| Delta badge | `text-xs font-semibold` | 12px / 600 |
| Button label | `text-xs font-medium` | 12px / 500 |
| Sidebar section label | `text-[10px] font-medium uppercase tracking-widest` | 10px / 1px tracking |

Two things to copy exactly:

1. Anything 20px or larger gets `tracking-tight`. Big bold text with default
   tracking is the most common giveaway of an amateur dashboard.
2. Section labels are 10px, uppercase, `tracking-widest`, and dimmed hard
   (`text-sidebar-foreground/40`). Small, wide, and faint.

---

## 5. Layout shell

```
┌────────────┬──────────────────────────────────────────┐
│  sidebar   │  header  (h-16, sticky, blurred)         │
│  260px     ├──────────────────────────────────────────┤
│  fixed     │  main  (flex-1, p-4 sm:p-6)              │
│  h-screen  │                                          │
└────────────┴──────────────────────────────────────────┘
```

Outer wrapper:

```html
<div class="flex min-h-screen">
```

Sidebar:

```html
<aside class="fixed ltr:left-0 rtl:right-0 top-0 z-40 hidden h-screen flex-col
              bg-sidebar transition-all duration-300 ease-in-out lg:flex w-[260px]">
```

260px fixed, hidden below `lg`, animated width on collapse. There is a small
circular collapse toggle pinned to the sidebar's outer edge, vertically near the
top.

Header:

```html
<header class="flex h-16 items-center justify-between border-b border-border
               bg-background/80 px-4 backdrop-blur-xl sm:px-6">
```

The `bg-background/80` plus `backdrop-blur-xl` combination is what gives the
header its glassy feel as content scrolls under it. Do not use a solid
background.

Main:

```html
<main class="flex-1 p-4 sm:p-6">
```

### Content grids

KPI row:

```html
<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
```

Main content rows use a 12-column grid so panels can be split 8/4 or 7/5:

```html
<div class="mt-6 grid grid-cols-1 gap-4 xl:grid-cols-12">
  <div class="xl:col-span-8"> ... </div>
  <div class="xl:col-span-4"> ... </div>
</div>
```

Breakpoints in use: `sm` (2-up), `xl` (full desktop grid). It collapses straight
to a single column below `sm`.

---

## 6. Components

### Card

The base recipe, used for every panel on the page:

```html
<div class="rounded-xl border bg-card text-card-foreground shadow-sm
            group relative overflow-hidden
            transition-all duration-300
            hover:shadow-md hover:border-primary/20">
```

Resting shadow is Tailwind's `shadow-sm` (`0 1px 3px rgb(0 0 0 / 0.1),
0 1px 2px -1px rgb(0 0 0 / 0.1)`). Do not go heavier. The lift on hover comes
from `shadow-md` plus a border that picks up a hint of the foreground color.
`group` and `overflow-hidden` matter because children animate on hover and
sparklines bleed to the card edge.

Card header and content:

```html
<div class="flex flex-row items-center justify-between space-y-1.5 p-5 pb-2">
  <div>
    <h3 class="text-base font-semibold tracking-tight">Pipeline Overview</h3>
    <p class="text-sm text-muted-foreground">Monthly pipeline performance over the past year</p>
  </div>
  <!-- optional right-side control: segmented toggle, "View all →" link, menu -->
</div>
<div class="p-5 pb-0"> ... </div>
```

Padding is 20px (`p-5`), not shadcn's default `p-6`. The header always has room
for a control on the right, and that slot is used constantly: a Value/Count
segmented toggle, a `View all →` link in `text-sm`, or a kebab menu.

### KPI stat card

The exact internal structure from the live page:

```html
<div class="rounded-xl border bg-card shadow-sm group relative overflow-hidden
            transition-all duration-300 hover:shadow-md hover:border-primary/20">
  <div class="p-5 pb-0">
    <div class="flex items-start justify-between">
      <div class="space-y-2">
        <p class="text-xs font-medium text-muted-foreground">Total Pipeline</p>
        <p class="text-2xl font-bold tracking-tight">$842K</p>
        <div class="flex items-center gap-1.5">
          <TrendingUp class="h-3.5 w-3.5 text-success" />
          <span class="text-xs font-semibold text-success">+12.4%</span>
        </div>
      </div>
      <div class="flex h-10 w-10 items-center justify-center rounded-xl
                  bg-chart-1/10 transition-transform duration-300 group-hover:scale-110">
        <Icon class="h-5 w-5 text-chart-1" />
      </div>
    </div>
  </div>
  <!-- full-bleed sparkline, ~48px tall, anchored to the bottom edge -->
</div>
```

Four details that make it:

- The icon sits in a 40px tile tinted at 10% of its own chart color, and scales
  to 110% on card hover.
- Each KPI in the row uses a different `--chart-N`, so the four tiles read as a
  set.
- The delta is icon plus percentage, `gap-1.5`, colored by `--success` or
  `--destructive`. The arrow icon direction flips with the sign.
- A sparkline area chart runs full-bleed to the bottom edge of the card, in the
  same chart color with a soft gradient fade to transparent. This is why the
  card needs `overflow-hidden` and why the content block is `pb-0`.

### Sidebar navigation

Section label:

```html
<div class="flex w-full items-center gap-2 rounded-md px-3 py-1.5
            text-[10px] font-semibold uppercase tracking-widest
            text-sidebar-foreground/40">
  Overview
  <ChevronDown class="ml-auto h-3 w-3" />
</div>
```

Sections are collapsible: OVERVIEW, COMMERCE, APPS, FINANCE.

Nav item, inactive:

```html
<a class="group relative flex items-center gap-3 rounded-lg px-3 py-2
          text-sm font-medium transition-all duration-200
          text-sidebar-foreground/70
          hover:bg-sidebar-accent/50 hover:text-sidebar-foreground">
  <Icon class="h-4 w-4" />
  Dashboard
</a>
```

Active state is a filled `bg-sidebar-accent` with full-opacity foreground. Note
inactive text is `/70` opacity rather than a separate muted token, which keeps
the hover transition smooth.

Count badges (for example Orders showing 12) are small pills pushed right with
`ml-auto`.

Sidebar footer is a user row: 32px circular avatar with initials, name in
`text-sm font-medium`, role in `text-xs text-muted-foreground`, and a sign-out
icon button on the right.

### Button

Primary, as measured on the "New Order" button:

- height 32px (`h-8`)
- padding `0 10px` (`px-2.5`)
- `rounded-lg` (10px)
- `text-xs font-medium`
- `bg-primary text-primary-foreground`, no border
- leading icon at `h-4 w-4` with `gap-2`

Buttons are noticeably small and tight. Header icon buttons (theme toggle,
palette, notifications) are 32px square, ghost variant, `rounded-lg`, with the
notification bell carrying a small dot indicator.

### Search

```html
<div class="relative">
  <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
  <input class="h-9 w-full rounded-lg border border-input bg-background
                pl-9 pr-12 text-sm placeholder:text-muted-foreground" />
  <kbd class="absolute right-3 top-1/2 -translate-y-1/2 rounded border
              px-1.5 text-[10px] text-muted-foreground">⌘K</kbd>
</div>
```

Roughly 245px wide, left-aligned in the header next to the sidebar edge.

### Table

Borderless and airy. No zebra striping, no vertical rules.

- Header cell: `text-xs font-medium text-muted-foreground`, padding `0 0 12px`,
  no uppercase and no letter-spacing.
- Body cell: `text-sm font-medium`, padding `12px 0`, row height about 61px in
  the sales rep table (`--table-row-height` is 2.75rem for denser tables).
- Horizontal padding on cells is `0`. Spacing comes from the card's own `p-5`.
- Numeric columns are right-aligned.
- First column is often a rank number or an avatar plus name stacked with a
  secondary line.
- Row hover is a subtle `hover:bg-muted/50`.

### Legend and category lists

Used under the donut chart:

```html
<div class="flex items-center justify-between py-1.5">
  <div class="flex items-center gap-2">
    <span class="h-2 w-2 rounded-full bg-chart-1"></span>
    <span class="text-sm text-muted-foreground">Qualified</span>
  </div>
  <span class="text-sm font-medium">124</span>
</div>
```

Label left and muted, value right and full-strength. 8px dot.

---

## 7. Charts

- Library is Recharts, wrapped in shadcn's `ChartContainer`.
- Area charts: 2px stroke in a chart color, fill is a vertical linear gradient
  from about 20% alpha down to 0. Curve is monotone, no dots on the line.
- Grid: horizontal lines only, 1px, in `--border`. No vertical grid lines.
- Axes: no axis lines, no tick marks. Tick labels are `text-xs
  text-muted-foreground`. Y-axis labels are pre-formatted (`$250k`, `$500k`),
  not raw numbers.
- Donut: thick ring with a large centered total (`text-2xl font-bold`) and a
  `text-xs text-muted-foreground` caption under it ("Deals"). Segments are
  `--chart-1` through `--chart-5` in order.
- Sparklines in KPI cards have no axes, no grid, and no tooltip. Pure shape.
- Tooltips are `--popover` surfaced, `rounded-lg`, bordered, `shadow-md`,
  `text-xs`.

---

## 8. Motion

Three durations, used consistently:

| Duration | Where |
|---|---|
| 200ms | Nav item hover, small interactive elements |
| 300ms | Card hover (shadow and border), icon tile scale, sidebar collapse |
| 300ms+ | Page and card entrance fade-in, staggered |

Everything uses `transition-all` with the default ease, except the sidebar which
adds `ease-in-out`. Cards fade and rise in on page load with a stagger across
the grid, which is worth reproducing since it does a lot for the perceived
polish.

---

## 9. Build checklist

1. Next.js + Tailwind v4, shadcn/ui initialized, Geist Sans and Geist Mono via
   `next/font`.
2. Paste the token blocks from section 2 into `globals.css` under `:root` and
   `.dark`, then expose them through `@theme inline`.
3. Build the shell: `flex min-h-screen`, fixed 260px sidebar, `h-16` blurred
   header, `main` with `flex-1 p-4 sm:p-6`.
4. Build the Card recipe once, with the hover and `group` behavior baked in, and
   never restyle it per panel.
5. Build the KPI card as its own component taking label, value, delta, icon,
   chart index, and sparkline data.
6. Lay out KPI row (`sm:grid-cols-2 xl:grid-cols-4`) then 12-column content rows
   with `mt-6 gap-4`.
7. Wire `--chart-1` through `--chart-5` into the Recharts theme so charts follow
   the theme swap automatically.

### What to avoid

- Any brand color on a surface, button, or border. Keep them neutral.
- Shadows heavier than `shadow-sm` at rest.
- Default letter-spacing on large bold text.
- Zebra-striped or fully bordered tables.
- Card padding at the shadcn default of `p-6`. This design uses `p-5`.
- A solid header background. It should blur what scrolls beneath it.
