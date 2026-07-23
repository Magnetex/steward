# UI/UX Audit Checklist

Walk a screen against each item. Mark ✅ pass / ⚠️ issue / ❌ fail.

## Hierarchy & layout
- [ ] One clear focal point; the primary action is the most prominent element.
- [ ] Type follows a defined scale (no arbitrary sizes).
- [ ] Spacing is on a 4/8pt grid; no random 5px/7px/13px gaps.
- [ ] Related items are grouped (proximity); unrelated items have more space.
- [ ] Content has a max width; lines are 45–75 characters.
- [ ] Alignment is consistent (shared left/right edges, grid columns).

## Typography
- [ ] ≤ 2 typefaces.
- [ ] Numbers in columns use tabular numerals and align on the decimal.
- [ ] Emphasis via weight/color before extra sizes.
- [ ] Body text left-aligned, not justified.

## Color & contrast
- [ ] Colors are semantic tokens, defined once (light + dark).
- [ ] Body text ≥ 4.5:1; large text / UI borders / icons ≥ 3:1.
- [ ] One color reserved for negative/destructive; meaning never color-only.
- [ ] 60/30/10 balance; accents used sparingly.
- [ ] Dark mode uses the same semantic tokens (not inverted hex).

## Consistency
- [ ] Same action = same control + label + position everywhere.
- [ ] One notification pattern, one modal pattern, one form-feedback pattern.
- [ ] Components reused, not re-invented per page.

## Feedback & states — for every interactive surface, is there a designed:
- [ ] Empty state (with a primary action)?
- [ ] Loading state (skeleton / spinner / progress)?
- [ ] Success state (toast / inline confirm)?
- [ ] Error state (what happened + what to do, near the field)?
- [ ] Busy/disabled state during async work?
- [ ] Undo or confirm for destructive actions?

## Navigation & IA
- [ ] Labels are concrete and self-evident.
- [ ] Top-level is shallow; related destinations grouped.
- [ ] Current location is shown (active state / breadcrumb).
- [ ] Search available when content is large.

## Affordances & interaction
- [ ] Interactive elements look interactive; static ones don't.
- [ ] Visible :focus-visible ring on every focusable element.
- [ ] Every hover-only action has a touch/keyboard equivalent.
- [ ] Touch targets ≥ 44×44px.
- [ ] Motion respects prefers-reduced-motion and clarifies rather than decorates.

## Accessibility
- [ ] Fully keyboard operable; logical tab order.
- [ ] Dropdowns/menus/dialogs are keyboard-navigable; focus managed.
- [ ] Icon-only buttons have aria-label.
- [ ] Progress bars: role="progressbar" + aria-valuenow/min/max.
- [ ] Charts have a text or data-table alternative.
- [ ] Form fields have associated <label>s and describe errors via aria.

## Responsive
- [ ] No horizontal page scroll at 375px.
- [ ] Tables collapse to cards on mobile.
- [ ] Primary action is thumb-reachable.
- [ ] Images/media are fluid (max-width:100%).

## Content & microcopy
- [ ] Buttons say what they do ("Add transaction", not "Submit").
- [ ] Empty states invite action.
- [ ] Errors are plain, specific, and non-blaming.
- [ ] Terminology matches the user's vocabulary and is consistent.
