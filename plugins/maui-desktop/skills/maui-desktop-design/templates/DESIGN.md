---
name: <App name>
description: <One line: what the app is and the character of its interface.>
platforms: [macos, windows, linux]
fidelity: adaptive
accent: brand
tokens: design/tokens.json
icons: design/icons.json
---

# Design System: <App name>

<!-- Written from maui-desktop-design's template. Replace every <placeholder>; delete guidance comments. -->

## Overview

<The character in a sentence or two: who uses it, in what mode (operate, read, create), and what the interface
should feel like.>

**Key characteristics:**
- <e.g. Pure-neutral surfaces separated by 1px hairlines; no nested cards.>
- <e.g. Accent only on primary actions, selection and focus.>
- <e.g. Platform-adaptive: each platform's type, radii and density; one component structure.>

## Colours

All colours are roles in `design/tokens.json`; pages and components use `var(--role)` and never literals.

### Surfaces

| Role | Use |
|---|---|
| `bg` | the canvas (transparent over the native window on macOS) |
| `surface-card` | grouped lists, settings sections, cards |
| `surface-well` | recessed regions inside a card: expanded rows, code paths |
| `surface-control` | inputs, secondary buttons, select triggers |
| `surface-popover` | menus, popovers, toasts |
| `surface-console` | logs and terminals, framed in both themes |

### Inks, accent and status

<Rules: which ink on which surface; where the accent appears; the four status colours and their tint, border, ink
and dot.>

<!-- generated:palette-light:start -->
<!-- generated:palette-light:end -->

<!-- generated:palette-dark:start -->
<!-- generated:palette-dark:end -->

## Typography

| Platform | Interface font | Mono | Base size |
|---|---|---|---|
| macOS | system-ui (SF Pro) | SF Mono | 13px |
| Windows | Segoe UI Variable | Cascadia Code | 14px |
| Linux | system-ui (Adwaita Sans) | Adwaita Mono | 14px |

<The hierarchy: page title, section title, row title, body, label, mono; where tabular numbers apply.>

## Layout

<The spacing scale; section rhythm; list row anatomy; how forms collapse on narrow widths.>

## Elevation and depth

<Flat or layered at rest; what gets a shadow; the focus ring.>

## Shapes

<The radius scale and the nesting rule: inner radius = outer radius − padding.>

## Platform matrix

<!-- generated:platform-matrix:start -->
<!-- generated:platform-matrix:end -->

## Seams

| Surface | macOS | Windows | Linux | Must match across the boundary |
|---|---|---|---|---|
| Window and title bar | native | native | native | window colour = `--bg` |
| Sidebar | native | native | <native or web> | selection accent, row height |
| Toolbar | native | native | <native or web> | content clears its height |
| Dialog frame | native sheet | native dialog | native dialog | frame surface = body surface; button heights and radii |
| Content | web | web | web | |

## Components

<One short section per primitive the app uses, each with its rule. See maui-desktop-design's primitives
reference for the list.>

## Do and don't

### Do
- <…>

### Don't
- <…>

## Surface inventory

<Every page, dialog and window, grouped. Update when one is added, renamed or removed; check every group on a
design or theme change.>

### Pages

### Dialogs

### Windows
