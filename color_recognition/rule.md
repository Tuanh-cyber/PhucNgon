# Color Recognition Rules

## General Rules

- Each exercise contains exactly **four color options**.
- Only **one correct answer** is displayed.
- Color positions must be randomized for every exercise.
- The correct color must not always appear in the same position.
- Patients may only select one answer.

---

# Front-end Rules

## Display

- Display four equally sized color tiles.
- All tiles must have identical dimensions.
- All tiles must have identical corner radius.
- Do not display text labels on color tiles.
- Do not display icons or symbols.
- Maintain consistent spacing between tiles.

---

# Image Asset Rules

## Image Format

- File format: PNG
- Resolution: 512 × 512 px
- Background: Solid color only
- Each image represents exactly one color.
- One image contains one solid color only.

---

## Image Design

- The entire canvas should be filled with the target color.
- Do not include rounded corners.
- Do not include borders.
- Do not include shadows.
- Do not include gradients.
- Do not include transparency.
- Do not include text, icons, or patterns.

---

## Front-end Rendering

The frontend is responsible for rendering the visual appearance of the color tiles.

Frontend should apply:

- Rounded corners
- Consistent tile size
- Consistent spacing
- Tap animation (optional)
- Selected-state highlight

## Feedback

Correct

- Green highlight

Incorrect

- Red highlight
- Display the correct answer

---

# Audio Rules

Each exercise plays one instruction before interaction.


Audio should

- be clear
- have moderate speaking speed
- use consistent volume
- avoid background noise

---

# Color Design Rules

Use predefined HEX values only.

Do not modify saturation or brightness.

Do not use gradients.

Do not use patterns.

One tile represents one solid color only.

---


# Accessibility

Use high-contrast colors.

Maintain consistent tile size.

Maintain consistent spacing.

Avoid flashing animations.

Avoid unnecessary visual effects.

---

# Randomization Rules

- Shuffle tile positions every exercise.
- Shuffle answer positions every attempt.
- Prevent consecutive exercises from using identical layouts.

---

# Asset Naming Convention

Color Assets

COL001.png

COL002.png

...

COL012.png

Audio Assets

red.wav

blue.wav

...

grey.wav

---

# Validation Rules

An exercise is considered valid only if:

- Exactly four color tiles are displayed.
- Exactly one correct answer exists.
- The target_color_id matches the audio instruction.
- All displayed colors are unique.
- Exercise order is randomized.
- No two consecutive exercises should have identical color layouts.

# Scoring Rules
Following the scoring rules for non-weight exercises.


## Session Completion

A session is completed when:

- All 10 exercises have been answered.

The system then displays:

- Total Score
- Accuracy
- Completion Time (optional)
- Session Summary

---

# Retry Rules

Patients may repeat the session.

Each new session must:

- Randomize exercise order.
- Randomize tile positions.
- Preserve the same target colors.

---

# Progress Tracking

The system records:

- Session ID
- Exercise ID
- Selected Answer
- Correct Answer
- Correct / Incorrect
- Response Time (optional)
- Timestamp

These records are stored for therapist review and progress monitoring.