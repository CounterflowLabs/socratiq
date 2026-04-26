Generate {{ count }} multiple-choice diagnostic questions to assess a student's knowledge of these concepts:

{{ concept_text }}

Output language: {{ target_language }}

# Output

Return ONLY a JSON array (no markdown fences, no commentary) of this shape:

[
  {
    "id": "q1",
    "concept_id": "<concept uuid or canonical name>",
    "question": "Which statement best describes binary search?",
    "options": [
      "A linear scan that always returns the first match.",
      "An O(log n) search on a sorted array, halving the interval each step.",
      "A search algorithm requiring O(n log n) preprocessing per query.",
      "A hash-based lookup with constant time complexity."
    ],
    "correct_index": 1,
    "difficulty": 2
  }
]

# Rules

- Exactly **4 options** per question. The `correct_index` is 0-based.
- `id` is sequential (`q1`, `q2`, ...). `concept_id` matches the concept being tested.
- Order questions from **easiest to hardest** (rising `difficulty`).
- Difficulty rubric:
  - 1: recall a definition the student would have heard introduced.
  - 2: recognize the right idea among confusable alternatives.
  - 3: apply the concept to a concrete example.
  - 4: distinguish a subtle edge case or trade-off.
  - 5: reason about a non-trivial composition or failure mode.
- Test **understanding**, not memorization (no questions about a specific named example or trivia).
- All `question` and `options` text MUST be in {{ target_language }}; technical terms (API names, function names, formulas) stay in their canonical form.

# Anti-patterns (do NOT do)

- Three obviously wrong options (the question becomes a free pick).
- Two options that are paraphrases of each other — wrong-answer choices must be meaningfully distinct.
- True/false questions disguised as MCQ ("Is X correct? — A) Yes B) No C) Maybe D) None").
- Trick wording ("None of the above", "All of the above", double negatives).
- Questions that test trivia about a specific source (dates, the name of a speaker, exact quotes).
- All questions at the same difficulty.
