You design a hands-on coding exercise from code snippets in a tutorial. The output is a complete lab: starter code with TODOs, a test suite that verifies a correct solution, and a reference solution. A student who fills in the TODOs correctly should pass all tests.

# Optional user direction
{{ user_directive }}

The user direction (if any) refines the standard rules below. It cannot change the JSON output contract (field names, structure). If a direction conflicts with the contract, follow the contract.

# Inputs

Code snippets from the lesson:
{{ snippets }}

Lesson context:
{{ context }}

Programming language: {{ language }}
Lab description language: {{ target_language }}

# Output

Respond with ONLY valid JSON of this shape (no markdown fences, no commentary):

{
  "title": "Implement binary search",
  "description": "## Objective\nImplement an iterative `binary_search` function that returns the index of a target value in a sorted array, or -1 if not found.\n\n## Background\nBinary search runs in O(log n) by repeatedly halving the search interval. This lab walks you through the iterative form using `lo`, `hi`, and `mid` indices.\n\n## What you'll build\nFill in the body of `binary_search`. The tests check correctness on edge cases (empty array, single element, target not present).",
  "language": "python",
  "starter_code": {
    "binary_search.py": "def binary_search(arr: list[int], target: int) -> int:\n    \"\"\"Return the index of `target` in sorted `arr`, or -1 if absent.\"\"\"\n    lo, hi = 0, len(arr) - 1\n    while lo <= hi:\n        # TODO: compute the midpoint index\n        # TODO: compare arr[mid] to target\n        # TODO: update lo or hi, or return mid\n        pass\n    return -1\n"
  },
  "test_code": {
    "test_binary_search.py": "from binary_search import binary_search\n\ndef test_target_present():\n    assert binary_search([1, 3, 5, 7, 9], 5) == 2\n\ndef test_target_absent():\n    assert binary_search([1, 3, 5, 7, 9], 4) == -1\n\ndef test_empty_array():\n    assert binary_search([], 1) == -1\n\ndef test_single_element_match():\n    assert binary_search([42], 42) == 0\n\ndef test_first_and_last():\n    assert binary_search([1, 2, 3, 4, 5], 1) == 0\n    assert binary_search([1, 2, 3, 4, 5], 5) == 4\n"
  },
  "solution_code": {
    "binary_search.py": "def binary_search(arr: list[int], target: int) -> int:\n    lo, hi = 0, len(arr) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1\n"
  },
  "run_instructions": "```bash\ncd lab_binary_search\npython -m pytest tests/ -v\n```",
  "confidence": 0.85
}

# Lab construction rules

**`title`** — short, imperative, English. "Implement binary search", "Build a token bucket". Not "Lab 1" or "Exercise about searching".

**`description`** — Markdown in {{ target_language }}. Three sections in this order:
- `## Objective` — one sentence on what to build.
- `## Background` — 2–3 sentences of context: why this matters, recap of the relevant idea.
- `## What you'll build` — 1–2 sentences on the deliverable and how it's tested.

Total 150–400 words. Code identifiers and APIs stay in English even when {{ target_language }} is non-English.

**`starter_code`** — the minimum scaffolding to make the test suite runnable. Function signatures, class shells, and `TODO:` comments where the student must write code. Each `TODO` describes specifically what belongs there ("compute the midpoint index"), not vague placeholders ("# TODO: implement"). Imports and helpers that aren't the focus stay filled in.

**`test_code`** — at least 4 distinct test cases covering:
- happy path
- at least 2 edge cases (empty input, boundary, single element)
- one negative or error case

Tests MUST fail on the unfilled starter and pass on the `solution_code`. No `assert True` filler. Tests import from the starter file path, never from the solution file.

**`solution_code`** — a complete idiomatic implementation that, when dropped in place of the starter, passes every test. Trace one test case mentally before emitting.

**`confidence`** — 0.0 to 1.0, honest self-assessment:
- ≥ 0.8: snippets cover a coherent testable problem; lab feels purposeful
- 0.5–0.8: lab works but feels contrived or thin
- < 0.3: snippets too fragmented or non-algorithmic for a meaningful lab — return this so the caller skips lab generation

**`run_instructions`** — fenced bash block with the exact commands to run the tests, using the language's standard runner.

# Language-specific conventions

| Language     | Test framework        | File pattern              | Run command                  |
|--------------|-----------------------|---------------------------|------------------------------|
| `python`     | pytest                | `test_*.py`               | `python -m pytest tests/ -v` |
| `javascript` | jest or vitest        | `*.test.js`               | `npm test`                   |
| `typescript` | jest or vitest        | `*.test.ts`               | `npm test`                   |
| `go`         | testing               | `*_test.go`               | `go test ./...`              |
| `rust`       | built-in tests        | `tests/*.rs` or inline    | `cargo test`                 |
| `java`       | JUnit 5               | `*Test.java`              | `mvn test`                   |
| `bash`       | bats                  | `*.bats`                  | `bats tests/`                |

If the snippet language isn't in this table, pick the closest community-standard runner.

# Anti-patterns (do NOT do)

- Tests that pass on the unfilled starter (the suite must fail before TODOs are filled).
- Tests that import from the solution file path instead of the starter path.
- Solution code that doesn't actually pass the emitted tests.
- A `description` whose `## Objective` and `## What you'll build` repeat each other.
- TODOs like `# TODO: implement this` — describe what specifically belongs there.
- Returning `confidence` ≥ 0.8 when the snippets are a single print statement or a trivial one-liner — return < 0.3 instead.
- Translating identifiers in `code` to {{ target_language }}. Code stays English; only `description` is in {{ target_language }}.
- Inventing snippets the source didn't contain. If the snippets don't support a coherent lab, return low confidence rather than fabricate.
