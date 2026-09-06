# Accessibility test report

**Target:** WCAG 2.2 AA.  
**Current claim:** baseline implementation and automated structural checks only; no conformance or
certification claim.

## Automated checks implemented

- semantic `main`, `nav`, header/footer, sections, headings, lists, tables, captions, and scoped row
  and column headers;
- skip link and visible `:focus-visible` treatment;
- keyboard-operable tabs, scenario rows, dialogs/drawer, Escape close, and focus return/trapping;
- labels for market, initiation, persistence, tactic search, and denominator analysis controls;
- `aria-live` announcements for denominator and analytical-window changes;
- exact text summaries and n/N beside every chart; missingness cells include text labels;
- no information conveyed only by color; explicit state/status labels accompany styling;
- responsive two-column/tablet and single-column/mobile layouts;
- horizontally scrollable wide tables with sticky headers/row labels;
- `prefers-reduced-motion` behavior and print reflow;
- source-level regression checks for the synthetic warning, focus, reduced motion, deterministic
  presentation steps, export controls, and absence of patient-level export links.

## Manual checks required before external presentation

- [ ] axe-core or equivalent browser audit with zero serious/critical issues;
- [ ] keyboard-only complete demo, including focus order and no keyboard trap;
- [ ] NVDA + Chrome/Edge reading order, names, states, live announcements, dialog/drawer behavior;
- [ ] 200% and 400% zoom/reflow at 1280 CSS pixels;
- [ ] contrast verification for text, controls, focus, charts, and disabled states;
- [ ] Windows high-contrast/forced-colors inspection;
- [ ] mobile touch target and orientation review;
- [ ] PNG, print/PDF, accessible report, CSV, and SVG fallback review;
- [ ] plain-language and cognitive-load review with representative executive and specialist users.

The automated in-app browser connection was unavailable during implementation. HTTP, HTML/CSS/JS,
keyboard-contract, and generated-package tests were therefore run, while visual and assistive-
technology sign-off remains a named pre-presentation activity.

