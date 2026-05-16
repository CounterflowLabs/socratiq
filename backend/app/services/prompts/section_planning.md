You group consecutive transcript chunks of a learning resource into
coherent "sections" — like chapters or topic shifts. Output the bucket
id each chunk belongs to.

Resource title: {{ title }}

INPUT FORMAT
You receive a JSON array of chunks. Each chunk has:
  - idx: chunk index (0-based)
  - summary: a 1-2 sentence summary of the chunk's content
  - boundary_hint: 0.0–1.0, higher means stronger signal that a topic
    shift starts AT this chunk (use as a soft signal, not a hard rule)
  - size: ONE of the following, indicating chunk "weight":
      * duration_sec: chunk length in seconds (video/audio)
      * word_count: number of words (text-only resources)
    The field name tells you which unit applies to this batch.

RULES
1. Each bucket id is a non-negative integer.
2. Adjacent chunks under the same theme MUST share the same id.
3. A new theme MUST get id +1 (don't skip or reuse).
4. bucket_ids MUST be monotonically non-decreasing across chunks.
   When a topic briefly recurs (e.g. "concept → example → back to
   concept"), prefer keeping it in the SAME bucket as the original
   concept rather than opening a new one and returning. Linearity
   over precision.
5. TARGET: 4–12 buckets total.
   - If size unit is duration_sec: each bucket ≈ 5–15 minutes
     (sum of duration_sec across its chunks, i.e. 300–900 sec).
   - If size unit is word_count: each bucket ≈ 1500–4000 words
     (sum of word_count across its chunks).
   - For short resources (total duration < 480 sec OR total
     word_count < 2000), 1–3 buckets is fine.
   - For very long resources, up to 12 buckets — NOT proportional
     to length, coarser granularity is correct.
6. Bucket topic: a concise phrase, ≤8 words, in the chunk's predominant
   language. Should name the SPECIFIC subject, not generic labels like
   "introduction" or "discussion".

OUTPUT (strict JSON, no markdown fences, no commentary)
{
  "buckets": [
    {"id": 0, "topic": "Why we need binary search"},
    {"id": 1, "topic": "Python implementation"}
  ],
  "assignments": [
    {"chunk_index": 0, "bucket_id": 0},
    {"chunk_index": 1, "bucket_id": 0},
    {"chunk_index": 2, "bucket_id": 1}
  ]
}

CONSTRAINTS (validator will reject otherwise)
- assignments.length === input chunks.length, same order
- bucket_ids monotonically non-decreasing
- every bucket_id in assignments has a corresponding entry in buckets
- number of distinct buckets in [1, 12]
