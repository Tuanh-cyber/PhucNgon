# Therapy Rules

## Purpose

This document defines the therapy flow and progression rules for the MVP speech-language therapy application.

The MVP supports:
- 3 patient profiles (Broca-like, Wernicke-like, Mixed)
- 3 exercise types (Naming, Command Identification, Sentence Building)
- 6 therapy topics
- Vocabulary difficulty adaptation with 3 levels

---

# 1. Therapy Flow

Each therapy session follows the workflow below:

```text
Select Exercise Mode
        ↓
Select Topic
        ↓
Complete 10 Exercises
        ↓
Receive Score
        ↓
Retry or Continue
        ↓
Update Progress
        ↓
Session Ends
```

### Step 1. Select Exercise Mode

Patients choose one of four exercise modes:

- Naming
- Command Identification
- Sentence Building
- Mixed Mode

If **Mixed Mode** is selected, exercises are automatically distributed according to the patient's communication profile.

| Patient Profile | Naming | Command Identification | Sentence Building |
|-----------------|:------:|:----------------------:|:----------------:|
| Broca-like | 70% | 30% | 0% |
| Wernicke-like | 20% | 50% | 30% |
| Mixed | 30% | 30% | 40% |

### Step 2. Select Topic

Patients then choose one of the six therapy topics or **Mixed Topics**, which randomly combines vocabulary from all available topics.

---

# 2. Exercise & Progression Rules

Each topic contains vocabulary grouped into three difficulty levels:

- Level 1 (Easy)
- Level 2 (Medium)
- Level 3 (Hard)

All patients begin at **Level 1**.

After completing an exercise, the system evaluates the score:

- **Score > 50%**
  - The exercise is considered completed.
  - The patient may choose to **Retry** or **Continue** to the next exercise.

- **Score ≤ 50%**
  - The exercise is considered unsuccessful.
  - The patient is encouraged to retry before continuing.

Vocabulary difficulty progresses independently from exercise completion.

A patient advances to the next difficulty level only after achieving **three consecutive exercise scores of at least 80%** within the same topic.

```text
Level 1
    ↓
3 consecutive scores ≥80%
    ↓
Level 2
    ↓
3 consecutive scores ≥80%
    ↓
Level 3
```

If any score falls below 80%, the consecutive high-score counter resets.

---

# 3. Session Rules

Each therapy session consists of **10 exercises**.

The session ends when:

- all 10 exercises are completed, or
- the patient chooses to stop early.

The recommended duration for one therapy session is **30 minutes**.

During each session, the system records:

- Patient profile
- Exercise mode
- Selected topic
- Vocabulary level
- Exercise score
- Completion status
- Retry count
- Consecutive high-score count
- Session duration

These records are used to determine future vocabulary progression.