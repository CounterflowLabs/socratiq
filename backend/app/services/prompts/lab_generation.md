You are a programming course lab designer. Create a hands-on coding exercise based on these code examples from a tutorial.

Code snippets from the lesson:
{{ snippets }}

Lesson context:
{{ context }}

Programming language: {{ language }}

Instructions:
1. Create a complete reference solution (solution_code) based on the code snippets
2. Create starter code (starter_code) by removing key implementations and replacing with TODO comments
3. Create test files (test_code) that verify the solution works
4. The starter code + tests should be self-consistent — a student filling in the TODOs correctly should pass all tests
5. Include clear descriptions of what each TODO requires

Return ONLY valid JSON:
{
  "title": "Lab title",
  "description": "## Objective\n...\n## Background\n...",
  "language": "{{ language }}",
  "starter_code": {"filename.py": "code with TODOs..."},
  "test_code": {"test_filename.py": "test code..."},
  "solution_code": {"filename.py": "complete solution..."},
  "run_instructions": "how to run tests",
  "confidence": 0.0-1.0
}
