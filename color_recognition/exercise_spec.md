# Color Recognition Exercise Specification

## Exercise Overview

Patients listen to an audio instruction requesting a specific color and select the corresponding color tile from four displayed options.

---

# Input

## Audio

Example:

> "Hãy chọn màu đỏ."

## Visual

Four colored tiles displayed simultaneously.

Example

🟥 🟨 🟩 🟦

---

# Interaction

- Tap one color tile.
- Only one answer is allowed.

---

# Output

The system returns:

- Correct
- Incorrect

along with visual feedback.

---

# Exercise Metadata

| Field | Description |
|--------|-------------|
| exercise_id | Unique exercise ID |
| exercise_type | color_recognition |
| target_color_id | Correct color asset |
| instruction_audio | Audio instruction |
| level | Exercise level |
| suitable_profiles | Broca, Wernicke, Mixed |

---

# Sample Metadata

| exercise_id | exercise_type | target_color_id | instruction_audio | level |
|--------------|--------------|----------------|------------------|--------|
| CLR001 | color_recognition | COL001 | red.wav | 1 |
| CLR002 | color_recognition | COL002 | blue.wav | 1 |
| CLR003 | color_recognition | COL003 | yellow.wav | 1 |

---

# Audio Examples

- Hãy chọn màu đỏ.
- Hãy tìm màu xanh dương.
- Hãy chạm vào màu vàng.
- Hãy chọn màu xanh lá.

---

# Success Criteria

The patient's selection matches the target_color_id.