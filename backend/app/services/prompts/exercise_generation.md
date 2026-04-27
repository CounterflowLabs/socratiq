Generate {{ count }} exercises that help a student practice the ideas in this learning content:

{{ content }}

Exercise types to include: {{ types }}
Output language: {{ target_language }}

# Output

Return ONLY a JSON array (no markdown fences, no commentary). Example:

[
  {
    "type": "mcq",
    "question": "When does binary search run in O(log n)?",
    "options": [
      "On any array.",
      "Only on sorted arrays.",
      "Only when the target is the median element.",
      "Only when n is a power of two."
    ],
    "answer": "Only on sorted arrays.",
    "explanation": "Binary search depends on being able to discard half the search space each step, which requires the array to be sorted.",
    "difficulty": 2,
    "concepts": ["binary_search", "sorted_array"]
  },
  {
    "type": "code",
    "question": "Write an iterative `binary_search(arr, target)` that returns the index of `target` in the sorted array `arr`, or -1 if absent.",
    "options": null,
    "answer": "def binary_search(arr, target):\n    lo, hi = 0, len(arr) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1",
    "explanation": "Maintain a half-open range [lo, hi]; halve it each iteration based on the comparison.",
    "difficulty": 3,
    "concepts": ["binary_search", "loop_invariant"]
  }
]

# Field rules

- `type`: `"mcq"`, `"code"`, or `"open"`. Match the requested types.
- `question`: in {{ target_language }}. Self-contained; doesn't require reading the source again.
- `options`: an array of exactly 4 strings for MCQ; **null** for `code` and `open`.
- `answer`: for MCQ, the exact text of the correct option (not the index). For `code`, a working reference solution. For `open`, the canonical correct answer or rubric.
- `explanation`: 1-3 sentences in {{ target_language }} describing **why** the answer is correct.
- `difficulty`: 1–5 (see rubric below).
- `concepts`: 1–4 canonical English concept names (`lower_snake_case`) that match the upstream knowledge graph.

# Difficulty rubric

1. Recall a definition just covered.
2. Recognize the right idea among confusable alternatives.
3. Apply to a concrete example.
4. Reason about an edge case, trade-off, or composition.
5. Multi-step reasoning across two or more concepts.

# Anti-patterns (do NOT do)

- MCQ where 3 options are nonsense — wrong options must be plausible mistakes.
- Open questions with only one defensible answer (use MCQ instead).
- Code questions whose `answer` doesn't actually compile or run.
- Translating code identifiers, API names, or function names to {{ target_language }} — those stay in their canonical form.
- Repeating the same question in different words to hit the count.
- Difficulty all clustered at one level.
