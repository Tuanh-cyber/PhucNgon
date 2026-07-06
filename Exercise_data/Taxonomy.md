# Vocabulary 
Topic
├── Hoạt động hằng ngày
├── Ăn uống
├── Vật dụng quen thuộc
├── Gia đình
├── Bộ phận cơ thể
├── Chữ số

Word Type
├── Noun
├── Verb
└── Adjective

# Exercise 
Naming
Command Identification
Sentence Building

| Exercise Type                     | Interaction Mode | Requires ASR      | Requires Recognition UI |
|-----------------------------------|------------------|-------------------|-------------------------|
| Naming                            | Speech           | Yes               | No                      |
| Command Identification            | Speech + Touch   | Yes (Mode 2 only) | Yes (Mode 1 only)       |
| Sentence Building                 | Speech           | Yes               | No                      |

# Profile 
Broca-like
Wernicke-like
Mixed

## Profile => Exercise Weight

Example:
                Naming    Command   Sentence
Broca-like        0.7       0.3        0.0
Wernicke-like     0.2       0.5        0.3
Mixed             0.3       0.3        0.4

Weight = sampling frequency, not eligibility. Every profile can still get any exercise.

# Asset

Vocabulary Asset
Image Asset
Audio Asset
Command Asset 
Sentence Template Asset
Sentence Instance Asset

| Asset                   | Used by       | Purpose                                                                   |
|-------------------------|---------------|---------------------------------------------------------------------------|
| Vocabulary Asset        | NAM, CMD, SEN | Canonical word + accepted answer variants + media files                   |
| Image Asset             | NAM, CMD, SEN | Visual stimulus                                                           |
| Audio Asset             | CMD, SEN      | Spoken stimulus or fallback repeat-after-me audio                         |
| Command Asset           | CMD           | Fixed command with audio
| Sentence Template Asset | SEN only      | Fixed sentence frame with a typed blank                                   |
| Sentence Instance Asset | SEN only      | One resolved (template + vocab) pairing, with its own full-sentence audio |