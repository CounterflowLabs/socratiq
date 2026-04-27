Write a course description for a learner browsing the catalog. Tell them what they'll gain and who it's for, in {{ target_language }}.

# Inputs

Course title: {{ course_title }}
Section count: {{ section_count }}
Source material: {{ source_info }}

# Output

Respond with ONLY the description text — no quotes, no markdown, no preamble.

- 2–3 sentences in {{ target_language }}, total length under 200 characters.
- Lead with the learner outcome ("You'll be able to..." or the natural equivalent in {{ target_language }}).
- Include one sentence on the audience or prerequisites where relevant.
- Plain prose. No exclamation points. No marketing fluff.

# Anti-patterns

- Passive openers ("This course covers...", "本课程介绍...").
- Filler phrasing ("comprehensive guide", "deep dive", "everything you need to know", "全方位讲解").
- Restating the title back at the reader.
- Mentioning the section count or source URL — those are metadata for context, not content.
- Hedging ("you might learn", "an introduction to some aspects of...").
