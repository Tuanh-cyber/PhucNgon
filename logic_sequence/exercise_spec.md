# Exercise Type: Logic Sequence

### Exercise ID prefix

SEQ

Ex:

SEQ001

SEQ002

...

---

## Objective

Assess the patient's ability to recognize and arrange images into the correct logical order of a daily activity.

Target Profiles

Primary

• Mixed

Secondary

• Wernicke-like

---

## Input Stimulus

### Audio Stimulus

"Hãy sắp xếp các hình sau theo đúng trình tự hành động."

### Visual Stimulus

A shuffled set of 3–5 images representing one daily activity.

Example

plant1.jpg
plant2.jpg
plant3.jpg

---

## User Task

The patient listens to the instruction.

The patient drags and drops the images into the correct order.

---

## Interaction Mode

Touch (Drag & Drop)

---

## Required Assets

### Sequence Asset

Example

sequence_id
title
level
step_order
image_file

---

## Exercise Metadata

exercise_id
exercise_type
target_sequence_id
suitable_profiles

---

## System Flow

1. Backend selects a Logic Sequence exercise.
2. Retrieve the corresponding Sequence Asset.
3. Play the instruction audio.
4. Shuffle the image order.
5. Display the images.
6. Patient arranges the images.
7. Patient submits the answer.
8. Backend compares the submitted order with the correct step_order.
9. Score and feedback are returned.