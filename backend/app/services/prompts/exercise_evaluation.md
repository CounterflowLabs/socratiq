Evaluate the student's answer to an open-ended exercise.

Question: {{ question }}
Reference answer: {{ correct_answer }}
Student's answer: {{ answer }}

Feedback language: {{ target_language }}

# Output

Return ONLY valid JSON of this shape (no markdown fences, no commentary):

{"score": 75, "feedback": "..."}

- `score`: integer 0–100 (see rubric).
- `feedback`: 1–3 sentences in {{ target_language }} that point out what the student got right, what's missing or wrong, and the single highest-impact next step.

# Score rubric

- 100 — Equivalent to the reference answer in correctness and completeness.
- 80 — Correct in substance with a minor omission or imprecise phrasing.
- 60 — Captures the main idea but misses an important component or applies it inaccurately.
- 30 — Touches the topic but contains a significant misunderstanding.
- 0 — Off-topic, blank, or fundamentally wrong.

Use the full range; don't anchor everything at 60–80.

# Anti-patterns (do NOT do)

- Empty praise ("Good job!", "做得不错") with no specific observation.
- Quoting the reference answer back at the student verbatim.
- Multi-paragraph feedback — keep it tight, 1–3 sentences.
- Penalizing the student for phrasing differences when the substance is right.
- Awarding partial credit (≥50) for answers that are off-topic or missing the core concept.
