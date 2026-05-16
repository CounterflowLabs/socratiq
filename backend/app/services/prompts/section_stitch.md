You are stitching two consecutive sections of a learning resource that were
planned in separate windows. Decide whether they actually describe the SAME
theme and should be merged into one section.

Resource title: {{ title }}

INPUT
Section A (about to end):
  topic: {{ topic_a }}
  last few summaries (in order):
{{ summaries_a }}

Section B (just starting, immediately after A):
  topic: {{ topic_b }}
  first few summaries (in order):
{{ summaries_b }}

RULES
- Merge only when both sections clearly continue the same single theme — the
  same concept, the same example, the same sub-procedure. Re-derivations,
  examples illustrating the same concept, and direct continuations all count
  as one theme.
- Do NOT merge just because the topics share words (e.g. "Python list" vs
  "Python dict"); the bar is "same idea", not "related ideas".
- Do NOT merge when there is a clear topic shift even if the topics look
  similar by surface form.
- When in doubt, do NOT merge — false-merge collapses two real sections,
  false-split is harmless (windowed planning expects some redundant seams).

OUTPUT (strict JSON, no commentary, no markdown fences)
{"merge": true|false, "reason": "<one short phrase>"}
