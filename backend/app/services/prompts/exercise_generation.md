Generate {{ count }} exercises based on this learning content:

{{ content }}

Exercise types to include: {{ types }}

For each exercise return:
- type: "mcq" | "code" | "open"
- question: the question text
- options: array of 4 strings (only for mcq, null otherwise)
- answer: the correct answer
- explanation: why this is correct
- difficulty: 1-5
- concepts: array of concept names tested

Return ONLY a JSON array.
