Generate {{ count }} multiple-choice diagnostic questions to assess a student's knowledge of these concepts:

{{ concept_text }}

Requirements:
- Order from easiest to hardest (difficulty 1-5)
- Each question has exactly 4 options
- Test understanding, not memorization

Return ONLY a JSON array:
[{"id": "q1", "concept_id": "<uuid>", "question": "...", "options": ["A","B","C","D"], "correct_index": 0, "difficulty": 1}]
