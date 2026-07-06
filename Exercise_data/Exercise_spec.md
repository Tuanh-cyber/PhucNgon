# Exercise Type: Naming
### Exercise ID prefix: NAM
Ex: NAM001 / NAM002 / NAM003...

- Objective: Assess the patient's ability to retrieve and verbally produce the name of a visually presented object.
- Target Profiles
  * Primary: Broca-like
  * Secondary: Mixed / Wernicke-like

---

## Input Stimulus

### Visual Stimulus

A single image representing a word in a topic (a common object / action / family member / number / body parts / food)

Examples:

- cái kéo.jpg
- uống nước.jpg
- bụng.jpg

---

## User Task

The patient is asked to look at the image and say the name of the object aloud.
Example:
Displayed Image:
[Image of scissors]

Expected Response:
"Cái kéo"

---

## Interaction Mode
Speech

---

## Required Assets

### Vocabulary Asset
Example:
```json
{
  "vocab_id": "V001",
  "canonical_word": "cái kéo",
  "accepted_answers": [
    "cái kéo",
    "kéo",
    "cây kéo"
  ],
  "image_file": "cái kéo.jpg",
}
```

### Image Asset
Example:
```text
cái kéo.jpg
```

---
## Exercise metadata structure
Example: 
```json
{
  "exercise_id": "NAM001",
  "exercise_type": "naming",
  "target_vocab_id": "V001",
  "suitable_profiles": [
    "broca_like",
    "mixed",
    "wernicke_like"
  ]
}
```
---
## System flow
1. Backend selects a Naming exercise.
2. Frontend displays the corresponding image.
3. Patient speaks the object name.
4. Audio is recorded.
5. Audio is sent to ASR.
6. ASR returns transcript.
7. Scoring Engine compares transcript against accepted answers.
8. Score and feedback are returned.



# Exercise Type: Command Identification
### Exercise ID prefix: CMD
Ex: CMD001 / CMD002 / CMD003...

- Objective: Assess the patient's ability to comprehend a spoken Vietnamese descriptive command/question and identify the target vocabulary item it refers to, responding either by selecting the correct answer or verbally repeating the word.
- Target Profiles
  * Primary: Wernicke-like
  * Secondary: Mixed / Broca-like

---

## Input Stimulus

### Audio Stimulus

A spoken Vietnamese descriptive command/question that describes a target vocabulary item by its function or characteristics, not the word itself.

Examples:

"Đồ vật dùng để cắt giấy là gì.mp3" → target word: "cái kéo"
"Cô gái đang làm gì.mp3" → target word: "uống nước"
"Quả gì màu đỏ, ăn giòn ngọt.mp3" → target word: "quả táo"

### Visual Stimulus

What's shown depends on the mode, and differs between the command-playback moment and the response moment:

- Mode 1 - Recognition: While the command audio plays, no image is shown. After playback, four answer options appear, each option can be text only, or image + text.
- Mode 2 - Repetition: While the command audio plays, the target image is shown (no text). After playback, the patient records their spoken answer, no on-screen text is given.

Examples:

- Mode 1 answer options: cái kéo.jpg + "cái kéo" / cái bút.jpg + "cái bút" / cái bàn.jpg + "cái bàn" / cái ghế.jpg + "cái ghế"
- Mode 2 image shown during playback: cái kéo.jpg (no text)

---

## User Task

The patient listens to the descriptive command and infers which vocabulary item it refers to, then performs the task for the assigned mode:

- Mode 1 - Recognition: Command audio plays with no image. Four answer options then appear (text, or image+text); patient selects the correct one.
- Mode 2 - Repetition: Command audio plays together with the target image (no text). Patient then records themselves saying the word aloud.

Example — Mode 1:

Played Audio: ["Đồ vật dùng để cắt giấy là gì.mp3"] (no image shown)

Then displayed: 4 options (image+text or text only), one of which is "cái kéo"

Expected Response: Select the option "cái kéo"

Example — Mode 2:

Played Audio: ["Đồ vật dùng để cắt giấy là gì.mp3"] + 
Displayed Image: [cái kéo.jpg] (no text)

Expected Response: Patient records themselves saying "cái kéo"

---

## Interaction Mode
Speech + Touch

---

## Required Assets

### Vocabulary Asset
Example:
```json
{
  "vocab_id": "V001",
  "canonical_word": "cái kéo",
  "accepted_answers": [
    "cái kéo",
    "kéo",
    "cây kéo"
  ],
  "audio_file": "cái kéo.mp3",
  "image_file": "cái kéo.jpg",
  "topic": "household_items",
  "word_type": "noun"
}
```

### Command Asset
```json
{
  "command_id": "C001",
  "command_text": "Đồ vật dùng để cắt giấy là gì?",
  "target_vocab_id": "V001",
  "audio_file": "Đồ vật dùng để cắt giấy là gì.mp3"
}
```

### Audio Asset
Example:
```text
Đồ vật dùng để cắt giấy là gì.mp3
cái kéo.mp3
```

### Image Asset (optional)

Required for Mode 2 (shown during command playback) and used as the optional image half of each Mode 1 answer option.

Example:
```text
cái kéo.jpg
```

---
## Exercise metadata structure

Example Mode 1: 
```json
{
  "exercise_id": "CMD001",
  "exercise_type": "command_identification",
  "target_vocab_id": "C001",
  "mode": "recognition",
  "suitable_profiles": [
    "wernicke_like",
    "mixed",
    "broca_like"
  ]
}
```
Example Mode 2:
```json
{
  "exercise_id": "CMD002",
  "exercise_type": "command_identification",
  "target_command_id": "C001",
  "mode": "repetition",
  "suitable_profiles": [
    "wernicke_like",
    "mixed",
    "broca_like"
  ]
}
```
---
## System flow
1. Backend selects a Command Identification exercise (resolves its target_command_id and mode).
2. Frontend plays the command audio (the descriptive question, not the word itself).
- recognition: no image is shown during playback.
- repetition: the target vocab's image is shown during playback (no text).
3. Patient listens to the command and infers the target vocabulary item.
4. After playback, frontend displays based on mode:
- recognition: four answer options (text, or image+text) — the correct one plus the 3 distractor_vocab_ids.
- repetition: recording interface only (no text shown).
5. Patient selects the correct answer (recognition) or speaks the word aloud (repetition).
6. Audio (in repetition mode) is recorded.
7. Audio is sent to ASR.
8. ASR returns transcript.
9. Scoring engine compares the selected answer or transcript against the target vocabulary item's accepted_answers.
10. Score and feedback are returned.

# Exercise Type: Sentence Building
### Exercise ID prefix: SEN
Ex: SEN001 / SEN002 / SEN003...

- Objective: Assess the patient's ability to construct and verbally produce a complete sentence by filling in a missing lexical item using contextual and visual cues.
- Target Profiles
  * Primary: Mixed
  * Secondary: Wernicke-like

---

## Input Stimulus

### Visual Stimulus

A sentence containing a missing lexical item (which can be a single word or a complex word), accompanied by an image representing that missing element.

Examples:
- "Tôi đang _______ ." + (uống nước.jpg)
- "Cô ấy đang ______ ." + (ăn cơm.jpg)
- "Bé đang ăn _______ ." + (quả táo.jpg)

### Audio Stimulus (fallback only)

A pre-recorded audio of the full completed sentence (template + vocab merged), used only when the patient fails to produce the correct sentence --> so they can listen and repeat, not played on the first attempt.

Examples:
- Tôi đang uống nước.mp3
- Bé đang ăn quả táo.mp3
---

## User Task

The patient is asked to look at the sentence template and the image, infer the missing lexical item, and say the full sentence aloud.

If the spoken response does not match the accepted answers, the system plays the full-sentence audio so the patient can listen and repeat it.

Example:

Displayed Sentence: "Tôi đang _____ ."
Displayed Image: [uống nước.jpg]

Expected Response: "Tôi đang uống nước."

On incorrect attempt → Plays: [Tôi đang uống nước.mp3] → Patient repeats.

---

## Interaction Mode
Speech

---

## Required Assets

Sentence Building reuses the same flat Vocabulary Asset schema as Naming and Auditory exercises (no separate nested schema). It additionally requires a Sentence Template Asset and a Sentence Instance Asset that binds a template to a vocab item with its own audio and accepted answers for the full sentence.

### Sentence Template Asset

Defines the fixed sentence frame and what kind of vocab can fill the blank. Contains no audio of its own, audio belongs to the resolved Sentence Instance, since the same template produces a different sentence per vocab item.

Example:
```json
{
  "template_id": "T001",
  "template": "Tôi đang ___.",
  "blank_type": "verb",
  "topic_constraint": "daily_activity"
}
```

### Sentence Instance Asset

Represents one resolved (template + vocab) pairing — i.e. one specific full sentence. Generated/cached ahead of time since it needs its own recorded audio file.

Example:
```json
{
  "sentence_instance_id": "SI001",
  "template_id": "T001",
  "vocab_id": "V001",
  "full_sentence": "Tôi đang uống nước.",
  "accepted_answers": [
    "Tôi đang uống nước",
    "Tôi uống nước"
  ],
  "audio_file": "Tôi đang uống nước.mp3"
}
```

### Vocabulary Asset (shared schema)
Example:
```json
{
  "vocab_id": "V001",
  "canonical_word": "uống nước",
  "accepted_answers": [
    "uống nước",
    "uống"
  ],
  "audio_file": "uống nước.mp3",
  "image_file": "uống nước.jpg",
  "topic": "daily_activity",
  "word_type": "verb"
}
```

### Image Asset 
Example:
```text
uống nước.jpg
```

### Audio Asset 
Example:
```text
uống nước.mp3
Tôi đang uống nước.mp3
```
---
## Exercise metadata structure
Example: 
```json
{
  "exercise_id": "SEN001",
  "exercise_type": "sentence_building",
  "target_sentence_instance_id": "SI001",
  "suitable_profiles": [
    "mixed",
    "wernicke_like"
  ]
}
```
---
## System flow
1. Backend selects a Sentence Building exercise.
2. System retrieves:
- Sentence template
- Linked vocabulary item
3. Frontend displays:
- Incomplete sentence
- Image from vocabulary asset
4. Patient infers the missing lexical item.
5. Patient speaks the full sentence.
6. Audio is recorded
7. Audio is sent to ASR
8. ASR returns transcript
9. Scoring engine compares transcript against accepted answers.
10. If correct → Score and feedback are returned.
If incorrect → Frontend plays the Sentence Instance's audio_file (full sentence), patient listens and repeats, response is re-scored.
11. Final score and feedback are returned.
