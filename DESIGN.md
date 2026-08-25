---
version: alpha
name: "SMYA Co-Tutor"
description: "An evidence-led practice workspace that feels like an annotated maths workbook: calm for students, precise for tutors."
colors:
  ink: "#18243A"
  paper: "#F7F3EA"
  surface: "#FFFFFF"
  primary: "#0E5B5B"
  accent: "#E56B55"
  success: "#2F7E6D"
  warning: "#B7791F"
  danger: "#B54747"
  border: "#D9D4CA"
  muted: "#6F756F"
typography:
  display:
    fontFamily: "Georgia, 'Times New Roman', serif"
    fontSize: "2rem"
    lineHeight: "1.1"
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    lineHeight: "1.5"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
rounded:
  DEFAULT: "0.75rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
spacing:
  section-gap: "2rem"
  page-max: "72rem"
  control-min: "2.75rem"
components:
  button:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    height: "2.75rem"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    height: "2.75rem"
    rounded: "{rounded.md}"
---

# SMYA Co-Tutor Design System

## Overview

### Creative North Star

SMYA should feel like an annotated maths workbook laid open on a quiet tutor's
desk: warm paper, dark ink, deliberate marks, and enough whitespace to see the
next step. The interface is a working product, not a classroom game and not a
generic AI chat surface.

### Product context and register

- **Audience and primary job:** Students complete approved objective practice; tutors review evidence and approve the next action.
- **Target market(s) and evidence:** A synthetic Singapore tuition-centre prototype, grounded in `context.md` and the S0 discovery record. No real student or SME data is used.
- **Locale(s) and language policy:** English UI with system font fallbacks; dates and numbers use the browser locale. No Japanese-market behavior is in scope.
- **Usage scene:** Phone-sized student sessions between lessons and small-laptop tutor review at a desk. Reading and one-handed answer entry matter more than dense dashboards.
- **Register:** Product-first hybrid: quiet, familiar student practice; denser evidence review for tutors.
- **Memorable signature:** A small coral “next mark” accent travels with the current question and active progress step, echoing a tutor's annotation without turning the UI into a game.
- **Restraint:** Keep status, permissions, source provenance, and approval state explicit. Avoid confetti, chat bubbles, gamified streaks, and decorative gradients.
- **Anti-references:** Generic chatbot panels, neon ed-tech game UIs, and enterprise-blue admin tables. They obscure evidence and make approval boundaries feel optional.
- **Token ownership/runtime mapping:** The existing runtime CSS in `frontend/app/globals.css` is canonical for this feature. `DESIGN.md` mirrors its semantic variables; components consume those variables through CSS classes and Tailwind `var(...)` adapters. Reconcile changes with `npx -p @google/design.md designmd lint DESIGN.md`.

## Colors

The palette uses ink and paper as the stable reading field. `primary` is the
safe action and focus family; `accent` marks the current learning step; `success`,
`warning`, and `danger` communicate semantic outcomes and are never the only
signal. Cards stay white on paper, with a warm border instead of a heavy shadow.
The current prototype is light-theme only. Forced-colors mode should defer to
the platform rather than hiding borders or focus rings.

## Typography

Georgia is a restrained display face for the practice title and question prompt;
the system sans stack carries controls, explanations, and tutor metadata. Body
copy remains at or above 16px with 1.5 line height. IDs and policy versions use
the mono stack. Sentence case and plain verbs are the product voice.

## Layout

Student practice uses a single-column reading measure capped at 42rem, with a
progress rail above the question and an answer/action region below it. The tutor
shell remains capped at 72rem. At 640px and below, cards become full-width with
comfortable side padding; action groups wrap without changing order. Document
scrolling remains the default; no shared shell receives a fixed viewport height
just to fit a panel. All async regions reserve stable space for loading and
feedback.

## Elevation & Depth

Hierarchy comes from paper/surface contrast and 1px borders. Use a very soft
shadow only for the student question card when it separates the reading surface
from the page; tutor evidence cards remain flat. No blur, glass, or floating
dashboard chrome.

## Shapes

Cards use the `lg` radius; controls use `md`; small tags use `sm`. Buttons are
large enough for touch and retain a visible focus ring. Dividers are hairline
warm borders. The coral accent is a line or small marker, never a large filled
background behind body text.

## Components

### Foundational visual states

Controls have quiet paper defaults, a primary ink/teal hover, a two-pixel coral
focus ring, and an explicit disabled/busy treatment that preserves geometry.
Loading uses a stable text-and-spinner region. Success, warning, and error use
an icon or text label in addition to color.

### Buttons and actions

The primary action is solid teal (`Start practice`, `Check answer`, `Continue`).
Secondary navigation is outline or text (`Back to assignments`). Tutor approval
uses success styling; reject/block actions are separated and use danger only
where the consequence is real. Busy buttons keep their width and announce state.

### Navigation and data display

Student routes use a simple breadcrumb-like back link and a page title. Progress
is a labeled list of question steps rather than an unlabeled bar. Tutor lists
retain semantic links and readable status badges; no important value is hover-only
or silently truncated.

### Forms and overlays

Answer entry is a labeled text input with app-owned validation and inline status.
There are no custom popups in the student flow. The existing tutor demo's native
select is accepted because platform-owned option geometry is not part of the
prototype contract. Errors remain inline with a retry path; no browser alerts.

### Iconography

The prototype uses text and simple CSS marks rather than a competing icon family.
When an icon is added, it must support a visible label or accessible name.

### Motion

Motion is sparse: a 200ms opacity/translate entrance for the question card and a
short progress-state change. `prefers-reduced-motion: reduce` removes transforms
and staggered delays.

### Content and data visualization

Copy names the action and consequence: “Check answer”, “Try the next question”,
and “This assignment is not available”. Avoid model language, hidden reasoning,
and unsupported claims. Mastery labels remain explicit and deterministic.

## Do's and Don'ts

- **Do:** Make the current question, answer action, feedback, and next step obvious on a phone.
- **Do:** Preserve source, approval, student scope, and policy metadata at the API boundary.
- **Don't:** Make a student wait for a model to mark an objective answer.
- **Don't:** use colour, animation, or chat-like copy to hide an approval or permission boundary.
