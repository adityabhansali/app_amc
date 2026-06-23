# Northern Star Engineering — AMC Platform Brand Guidelines

A dark, product-led visual system adapted from the **Linear** design language for Northern
Star Engineering's Annual Maintenance Contract platform. The goal: a calm, premium, transparent
surface where the *operational data* (visits, refills, reports, statuses) is the protagonist —
not decorative chrome.

> **Implementation note.** All tokens below live in [`nse/templates/base.html`](nse/templates/base.html):
> the Tailwind config (`tailwind.config.theme.extend`) exposes clean tokens (`bg-canvas`,
> `text-ink`, `bg-primary`, `bg-surface-1`…), and a `<style>` override block remaps the older
> utility classes used across page templates onto this dark palette. To restyle globally, edit
> that one file.

---

## 1. Core principles

1. **Dark-canvas system.** `canvas` (#010102) is the anchor — near-pure black with a faint blue
   tint. Never `#000000`, never a light theme.
2. **Surfaces, not shadows.** Hierarchy comes from a four-step surface ladder + 1px hairline
   borders, not drop shadows. Lifted panels get only a faint top-edge highlight.
3. **One brand accent.** Lavender-blue `primary` (#5e6ad2) is scarce — brand mark, primary CTA,
   focus ring, link emphasis. Never a card fill or section background.
4. **Functional semantics only.** Beyond lavender, color appears *only* to carry meaning:
   **success green** for healthy statuses, and — a deliberate deviation from pure Linear for a
   fire-safety business — **emergency red** for the danger/emergency signal. No decorative
   greens/oranges/pinks.
5. **One typographic voice.** Inter throughout, weight 400 for body and 600–700 for display,
   with aggressively negative letter-spacing on large type.
6. **Data is the hero.** Visit timelines, refill registers, service reports and status pills do
   the heavy lifting; the frame stays quiet and dark around them.

---

## 2. Color

### Brand & accent
| Token | Hex | Use |
|---|---|---|
| `primary` | `#5e6ad2` | Primary CTA, brand mark, links, active states |
| `primary-hover` | `#828fff` | Hovered CTA, lavender text accents (eyebrows, highlights) |
| `primary-focus` | `#5e69d1` | Focus-ring tint on inputs/buttons |

### Surface ladder
| Token | Hex | Use |
|---|---|---|
| `canvas` | `#010102` | Page background, nav, footer, emergency strip |
| `surface-1` | `#0c0d10` | Cards, panels, product/report tiles (the default lift) |
| `surface-2` | `#16171b` | Inset boxes, table headers, hovered cards, featured tier, inputs |
| `surface-3` | `#1c1d22` | Progress tracks, nested chips, dropdowns |
| `surface-4` | `#222329` | Deepest lifted surface (rare) |
| `hairline` | `#23252a` | 1px borders & dividers |
| `hairline-strong` | `#2e3035` | Input borders, stronger dividers |

### Text (ink)
| Token | Hex | Use |
|---|---|---|
| `ink` | `#f7f8f8` | Headlines & emphasized body |
| `ink-muted` | `#d0d6e0` | Secondary body |
| `ink-subtle` | `#8a8f98` | Meta, nav links, deselected tabs, footer |
| `ink-tertiary` | `#62666d` | Footnotes, disabled, placeholders |

### Semantic (meaning-bearing only)
| Token | Hex | Use |
|---|---|---|
| `success` | `#27a644` | "On track" / "Active" / "Completed" / "Paid" pills, approve buttons |
| `danger` | `#e5484d` | Emergency strip & CTA, "Overdue", reject/error states |

Status pills are rendered as a **dark tint background + bright same-hue text** (e.g. completed =
dark green on `#13251a` with `#46d06a` text). See `status_badge` / `refill_badge` in
[`_macros.html`](nse/templates/_macros.html).

---

## 3. Typography

**Family:** `Inter` (fallback `SF Pro Display, -apple-system, system-ui`). Inter is the
recommended open substitute for Linear's proprietary cut. Loaded via Google Fonts at weights
400/500/600/700/800.

| Role | Size | Weight | Tracking |
|---|---|---|---|
| Hero headline | 40–56px | 700 | −0.03em |
| Section heading | 28–32px | 700 | −0.03em |
| Card / sub heading | 18–22px | 600 | −0.02em |
| Body | 16px | 400 | −0.011em |
| Small / meta | 13–14px | 400 | −0.011em |
| Button label | 14px | 500–600 | 0 |
| Eyebrow / uppercase tag | 10–12px | 500 | +0.08em (positive) |

**Rules**
- Negative tracking scales with size — most aggressive on hero type, easing toward body.
- Eyebrows/labels use *positive* tracking + uppercase to read as taxonomy.
- Resist 800 weight on large display; 600–700 carries the voice.
- Money is shown via the `rupees` filter (₹ with thousands separators).

---

## 4. Shape & spacing

**Radius** — buttons & inputs `rounded-md` (8px); cards `rounded-xl`/`rounded-2xl` (12–16px);
status pills & toggles `rounded-full`. CTAs are **never** pill-rounded; pills are reserved for
status/tabs/avatars.

**Spacing** — 4px base. Card padding 24px (feature/pricing) to 32–48px (testimonials/CTA banners).
~96px between major sections. The dark canvas *is* the whitespace — sections separate by lifting
onto `surface-1`, not by white gaps.

**Container** — max content width ~1280px; card grids 3-up desktop → 2-up tablet → 1-up mobile.

---

## 5. Elevation

| Level | Treatment | Use |
|---|---|---|
| 0 flat | no border, no shadow | Body text, hero, footer |
| 1 lift | `surface-1` + 1px `hairline` + faint top-edge highlight | Default cards & panels |
| 2 lift | `surface-2` + 1px `hairline-strong` | Featured/hovered cards, inputs |
| 3 lift | `surface-3` | Sub-nav, nested chips |
| focus | 2px `primary-focus` ring | Focused input/button |

No atmospheric gradients, no spotlight cards, essentially no drop shadows.

---

## 6. Components (as built)

- **Buttons** — *Primary*: `bg-primary` + white label, `rounded-md`, hover `primary-hover`.
  *Secondary*: `surface-2` + `hairline` border. *Danger*: `danger` fill (emergency).
  *Success*: `success` fill (approve / download / refill).
- **Cards** — `surface-1` + `hairline`, `rounded-xl/2xl`. Hover lifts the border toward
  `primary`/`hairline-strong`.
- **Status pills** — dark-tint bg + bright same-hue text, `rounded-full`, 12px caption.
- **Inputs** — `surface-2` fill, `hairline-strong` border, `primary-focus` ring, `rounded-md`;
  placeholders in `ink-tertiary`. Styled globally so every field is consistent.
- **Nav** — sticky translucent `canvas` bar with hairline underline; brand mark left, subtle
  `ink-subtle` links, single `primary` CTA right.
- **Footer** — dense link grid on `canvas`, `ink-subtle` text, hairline top rule.
- **AI chat widget** — lavender floating launcher; user bubbles `primary`, assistant bubbles
  `surface-1` on a `surface-2` log.

---

## 7. Do / Don't

**Do**
- Keep `canvas` (#010102) as the anchor; the blue tint is intentional.
- Use lavender only for brand mark, primary CTA, focus, link emphasis.
- Build hierarchy with the surface ladder + hairlines.
- Apply negative tracking on display type.
- Let the operational data (visits, refills, reports) lead each screen.

**Don't**
- Don't ship a light mode or use `#000000`.
- Don't use lavender as a fill or background.
- Don't add a *decorative* third chromatic accent (green and red are functional only).
- Don't add gradients, spotlights, or heavy drop shadows.
- Don't pill-round CTAs.

---

## 8. Deliberate deviations from the source Linear spec

This is an operational maintenance product, not a marketing site, so two adjustments were made
consciously:

1. **Emergency red is a first-class semantic.** A fire-safety company must surface the emergency
   channel unmistakably, so `danger` (#e5484d) is retained alongside `success` green as the two
   meaning-bearing colors. Both are used strictly functionally.
2. **Richer status palette for ops.** Visit/contract/request statuses need distinguishable pills
   (scheduled/in-progress/completed/overdue/etc.), implemented as restrained dark-tint badges
   rather than the single success pill a pure marketing page would use.

Light-mode, marketing-only product screenshots, and the proprietary Linear typeface are out of
scope; Inter is the sanctioned substitute.
