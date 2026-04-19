"""Seed the database with demo data for UI testing."""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_factory, engine
from app.db.models import (
    Base, User, Source, Course, CourseSource, Section,
    Concept, Exercise, Lab, ReviewItem, SectionProgress,
)

LOCAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Fixed UUIDs for reproducibility
SOURCE_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
COURSE_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
SECTION_IDS = [uuid.UUID(f"cccccccc-0000-0000-0000-00000000000{i}") for i in range(1, 6)]
CONCEPT_IDS = [uuid.UUID(f"dddddddd-0000-0000-0000-00000000000{i}") for i in range(1, 6)]
EXERCISE_IDS = [uuid.UUID(f"eeeeeeee-0000-0000-0000-00000000000{i}") for i in range(1, 6)]
LAB_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        # Check if already seeded
        existing = await db.get(Course, COURSE_ID)
        if existing:
            print("Demo data already exists. Skipping.")
            return

        # 1. User
        user = await db.get(User, LOCAL_USER_ID)
        if not user:
            user = User(id=LOCAL_USER_ID, email="local@socratiq.local", name="Local User")
            db.add(user)

        await db.flush()

        # 2. Source (Bilibili video)
        source = Source(
            id=SOURCE_ID,
            type="bilibili",
            url="https://www.bilibili.com/video/BV1x411J7Qn",
            title="Python 从零开始教程合集",
            raw_content="",
            metadata_={},
            status="ready",
            created_by=LOCAL_USER_ID,
        )
        db.add(source)

        # 3. Concepts
        concepts_data = [
            ("变量与数据类型", "Python 中的基本数据类型：int, float, str, bool, list, dict", "基础"),
            ("条件与循环", "if/elif/else 条件判断和 for/while 循环结构", "基础"),
            ("函数定义", "使用 def 关键字定义函数，参数传递，返回值", "基础"),
            ("列表推导式", "Python 特有的简洁列表生成语法 [expr for x in iterable]", "进阶"),
            ("面向对象", "类的定义、实例化、继承、多态等 OOP 概念", "进阶"),
        ]
        for i, (name, desc, cat) in enumerate(concepts_data):
            db.add(Concept(id=CONCEPT_IDS[i], name=name, description=desc, category=cat, aliases=[], prerequisites=[]))

        # 4. Course
        course = Course(id=COURSE_ID, title="Python 从零到一", description="一个完整的 Python 入门课程，涵盖变量、流程控制、函数、列表推导式和面向对象编程。通过 B 站视频合集自动生成。", created_by=LOCAL_USER_ID)
        db.add(course)
        await db.flush()
        db.add(CourseSource(course_id=COURSE_ID, source_id=SOURCE_ID))

        # 5. Sections with LessonContent
        sections_data = [
            {
                "title": "Python 环境搭建与第一行代码",
                "difficulty": 1,
                "key_terms": ["Python", "解释器", "IDE", "print"],
                "has_code": True,
                "lesson": {
                    "title": "Python 环境搭建与第一行代码",
                    "summary": "学习如何安装 Python 环境并编写第一个 Hello World 程序。",
                    "sections": [
                        {
                            "heading": "安装 Python",
                            "content": "访问 python.org 下载最新版本的 Python 3.12+。安装时勾选 'Add Python to PATH' 选项。安装完成后打开终端输入 `python --version` 验证安装。",
                            "timestamp": 30,
                            "code_snippets": [{"language": "bash", "code": "python --version\n# Python 3.12.0", "context": "验证安装"}],
                            "key_concepts": ["Python 解释器", "PATH 环境变量"],
                            "diagrams": [],
                            "interactive_steps": None,
                        },
                        {
                            "heading": "Hello World",
                            "content": "打开编辑器，创建一个 `hello.py` 文件，输入以下代码并运行。`print()` 是 Python 内置的输出函数。",
                            "timestamp": 120,
                            "code_snippets": [{"language": "python", "code": "print('Hello, World!')\nprint('你好，Python！')", "context": "第一个程序"}],
                            "key_concepts": ["print 函数", "字符串"],
                            "diagrams": [],
                            "interactive_steps": None,
                        },
                    ],
                },
            },
            {
                "title": "变量与数据类型",
                "difficulty": 1,
                "key_terms": ["变量", "int", "float", "str", "bool", "type()"],
                "has_code": True,
                "lesson": {
                    "title": "变量与数据类型",
                    "summary": "了解 Python 中的基本数据类型和变量赋值规则。",
                    "sections": [
                        {
                            "heading": "变量赋值",
                            "content": "Python 是动态类型语言，变量不需要声明类型。使用 `=` 赋值，Python 会自动推断类型。",
                            "timestamp": 0,
                            "code_snippets": [{"language": "python", "code": "name = '小明'\nage = 18\nheight = 1.75\nis_student = True\n\nprint(type(name))   # <class 'str'>\nprint(type(age))    # <class 'int'>", "context": "变量赋值与类型"}],
                            "key_concepts": ["动态类型", "变量"],
                            "diagrams": [{"type": "mermaid", "title": "Python 数据类型", "content": "graph TD\n  A[Python 数据类型] --> B[数值型]\n  A --> C[序列型]\n  A --> D[映射型]\n  B --> E[int]\n  B --> F[float]\n  C --> G[str]\n  C --> H[list]\n  C --> I[tuple]\n  D --> J[dict]"}],
                            "interactive_steps": None,
                        },
                        {
                            "heading": "类型转换",
                            "content": "使用内置函数进行类型转换：`int()`, `float()`, `str()`, `bool()`。注意转换可能会丢失精度或抛出异常。",
                            "timestamp": 300,
                            "code_snippets": [{"language": "python", "code": "x = '42'\ny = int(x)      # 42\nz = float(x)    # 42.0\nw = str(42)     # '42'", "context": "类型转换"}],
                            "key_concepts": ["类型转换", "int()", "float()", "str()"],
                            "diagrams": [],
                            "interactive_steps": None,
                        },
                    ],
                },
            },
            {
                "title": "条件判断与循环",
                "difficulty": 2,
                "key_terms": ["if", "elif", "else", "for", "while", "range"],
                "has_code": True,
                "lesson": {
                    "title": "条件判断与循环",
                    "summary": "掌握 Python 的流程控制：条件分支和循环迭代。",
                    "sections": [
                        {
                            "heading": "if 条件判断",
                            "content": "Python 使用缩进（通常 4 个空格）来表示代码块，而不是花括号。",
                            "timestamp": 0,
                            "code_snippets": [{"language": "python", "code": "score = 85\n\nif score >= 90:\n    print('优秀')\nelif score >= 60:\n    print('及格')\nelse:\n    print('不及格')", "context": "条件判断"}],
                            "key_concepts": ["条件判断", "缩进"],
                            "diagrams": [{"type": "mermaid", "title": "条件判断流程", "content": "flowchart TD\n  A[开始] --> B{score >= 90?}\n  B -->|是| C[优秀]\n  B -->|否| D{score >= 60?}\n  D -->|是| E[及格]\n  D -->|否| F[不及格]"}],
                            "interactive_steps": {"title": "练习步骤", "steps": [{"label": "创建变量", "detail": "定义一个 temperature 变量", "code": "temperature = 28"}, {"label": "添加条件", "detail": "根据温度输出不同信息", "code": "if temperature > 30:\n    print('很热')\nelse:\n    print('舒适')"}]},
                        },
                        {
                            "heading": "for 循环",
                            "content": "for 循环用于遍历可迭代对象。`range()` 函数生成整数序列。",
                            "timestamp": 600,
                            "code_snippets": [{"language": "python", "code": "# 遍历列表\nfruits = ['苹果', '香蕉', '橙子']\nfor fruit in fruits:\n    print(fruit)\n\n# range\nfor i in range(5):\n    print(i)  # 0, 1, 2, 3, 4", "context": "for 循环"}],
                            "key_concepts": ["for 循环", "range()", "可迭代对象"],
                            "diagrams": [],
                            "interactive_steps": None,
                        },
                    ],
                },
            },
            {
                "title": "函数定义与调用",
                "difficulty": 2,
                "key_terms": ["def", "return", "参数", "默认参数", "作用域"],
                "has_code": True,
                "lesson": {
                    "title": "函数定义与调用",
                    "summary": "学习如何定义可复用的函数，理解参数传递和作用域。",
                    "sections": [
                        {
                            "heading": "定义函数",
                            "content": "使用 `def` 关键字定义函数。函数可以有参数和返回值。",
                            "timestamp": 0,
                            "code_snippets": [{"language": "python", "code": "def greet(name, greeting='你好'):\n    \"\"\"向某人打招呼。\"\"\"\n    return f'{greeting}, {name}!'\n\nprint(greet('小明'))         # 你好, 小明!\nprint(greet('Alice', 'Hi'))  # Hi, Alice!", "context": "函数定义"}],
                            "key_concepts": ["def", "参数", "返回值", "默认参数"],
                            "diagrams": [],
                            "interactive_steps": None,
                        },
                    ],
                },
            },
            {
                "title": "列表推导式与高级特性",
                "difficulty": 3,
                "key_terms": ["列表推导式", "字典推导式", "lambda", "map", "filter"],
                "has_code": True,
                "lesson": {
                    "title": "列表推导式与高级特性",
                    "summary": "掌握 Python 中优雅的数据处理方式。",
                    "sections": [
                        {
                            "heading": "列表推导式",
                            "content": "列表推导式是 Python 最具特色的语法之一，可以用一行代码替代多行循环。",
                            "timestamp": 0,
                            "code_snippets": [{"language": "python", "code": "# 传统写法\nsquares = []\nfor x in range(10):\n    squares.append(x ** 2)\n\n# 列表推导式\nsquares = [x ** 2 for x in range(10)]\n\n# 带条件\nevens = [x for x in range(20) if x % 2 == 0]", "context": "列表推导式"}],
                            "key_concepts": ["列表推导式", "简洁语法"],
                            "diagrams": [],
                            "interactive_steps": None,
                        },
                    ],
                },
            },
        ]

        for i, data in enumerate(sections_data):
            lesson = data.pop("lesson")
            key_terms = data.pop("key_terms")
            has_code = data.pop("has_code")
            section = Section(
                id=SECTION_IDS[i],
                course_id=COURSE_ID,
                title=data["title"],
                order_index=i,
                source_id=SOURCE_ID,
                source_start=f"https://www.bilibili.com/video/BV1x411J7Qn?p={i+1}",
                content={"summary": lesson["summary"], "key_terms": key_terms, "has_code": has_code, "lesson": lesson},
                difficulty=data["difficulty"],
            )
            db.add(section)

        await db.flush()

        # 6. Lab (for section 3 — 条件判断与循环)
        lab = Lab(
            id=LAB_ID,
            section_id=SECTION_IDS[2],
            title="流程控制练习",
            description="实现几个使用条件判断和循环的小函数。",
            language="python",
            starter_code={
                "flow_control.py": "def fizzbuzz(n: int) -> list[str]:\n    \"\"\"返回 1 到 n 的 FizzBuzz 结果列表。\n\n    规则:\n    - 能被 3 整除: 'Fizz'\n    - 能被 5 整除: 'Buzz'\n    - 能被 3 和 5 整除: 'FizzBuzz'\n    - 其他: 数字本身(字符串)\n    \"\"\"\n    # TODO: 实现此函数\n    pass\n\n\ndef count_vowels(text: str) -> int:\n    \"\"\"统计字符串中元音字母的数量 (a, e, i, o, u，不区分大小写)。\"\"\"\n    # TODO: 实现此函数\n    pass\n",
                "utils.py": "def is_palindrome(s: str) -> bool:\n    \"\"\"判断字符串是否为回文（忽略大小写和空格）。\"\"\"\n    # TODO: 实现此函数\n    pass\n",
            },
            test_code={
                "test_flow_control.py": "from flow_control import fizzbuzz, count_vowels\n\ndef test_fizzbuzz_basic():\n    result = fizzbuzz(15)\n    assert result[0] == '1'\n    assert result[2] == 'Fizz'\n    assert result[4] == 'Buzz'\n    assert result[14] == 'FizzBuzz'\n\ndef test_fizzbuzz_length():\n    assert len(fizzbuzz(20)) == 20\n\ndef test_count_vowels():\n    assert count_vowels('hello') == 2\n    assert count_vowels('AEIOU') == 5\n    assert count_vowels('xyz') == 0\n",
                "test_utils.py": "from utils import is_palindrome\n\ndef test_palindrome():\n    assert is_palindrome('racecar') == True\n    assert is_palindrome('hello') == False\n    assert is_palindrome('A man a plan a canal Panama') == True\n",
            },
            solution_code={
                "flow_control.py": "def fizzbuzz(n):\n    result = []\n    for i in range(1, n + 1):\n        if i % 15 == 0: result.append('FizzBuzz')\n        elif i % 3 == 0: result.append('Fizz')\n        elif i % 5 == 0: result.append('Buzz')\n        else: result.append(str(i))\n    return result\n\ndef count_vowels(text):\n    return sum(1 for c in text.lower() if c in 'aeiou')\n",
                "utils.py": "def is_palindrome(s):\n    cleaned = s.lower().replace(' ', '')\n    return cleaned == cleaned[::-1]\n",
            },
            run_instructions="pip install pytest\npytest -v",
            confidence=0.85,
        )
        db.add(lab)

        # 7. Exercises (for section 2 — 变量与数据类型)
        exercises_data = [
            {
                "id": EXERCISE_IDS[0],
                "section_id": SECTION_IDS[1],
                "type": "mcq",
                "question": "以下哪个是 Python 中正确的变量赋值方式？",
                "options": ["int x = 10", "x = 10", "var x = 10", "let x = 10"],
                "answer": "1",
                "explanation": "Python 使用动态类型，不需要声明变量类型。直接使用 `x = 10` 即可赋值，Python 会自动推断 x 的类型为 int。",
                "difficulty": 1,
            },
            {
                "id": EXERCISE_IDS[1],
                "section_id": SECTION_IDS[1],
                "type": "mcq",
                "question": "执行 `type(3.14)` 的结果是什么？",
                "options": ["<class 'int'>", "<class 'float'>", "<class 'str'>", "<class 'decimal'>"],
                "answer": "1",
                "explanation": "3.14 是一个浮点数字面量，Python 将其类型推断为 float。",
                "difficulty": 1,
            },
            {
                "id": EXERCISE_IDS[2],
                "section_id": SECTION_IDS[1],
                "type": "code",
                "question": "写一个函数 `celsius_to_fahrenheit(c)` 将摄氏度转换为华氏度。公式: F = C * 9/5 + 32",
                "options": None,
                "answer": "def celsius_to_fahrenheit(c):\n    return c * 9/5 + 32",
                "explanation": "华氏度 = 摄氏度 × 9/5 + 32。注意 Python 中 `/` 是浮点除法，`//` 是整除。这里应该用 `/`。",
                "difficulty": 2,
            },
            {
                "id": EXERCISE_IDS[3],
                "section_id": SECTION_IDS[2],
                "type": "mcq",
                "question": "`range(1, 10, 2)` 会生成哪些数字？",
                "options": ["1, 2, 3, ..., 10", "1, 3, 5, 7, 9", "0, 2, 4, 6, 8", "1, 3, 5, 7"],
                "answer": "1",
                "explanation": "range(start, stop, step) 从 start 开始，每次增加 step，在到达 stop 之前停止。所以 range(1, 10, 2) 生成 1, 3, 5, 7, 9。",
                "difficulty": 2,
            },
            {
                "id": EXERCISE_IDS[4],
                "section_id": SECTION_IDS[2],
                "type": "open",
                "question": "解释 Python 中 for 循环和 while 循环的区别，各举一个适用场景。",
                "options": None,
                "answer": "for 循环适合遍历已知集合，while 循环适合未知次数的重复。",
                "explanation": "for 循环遍历可迭代对象（如列表、range），循环次数在开始前已知。while 循环在条件为 True 时持续执行，适合等待用户输入、轮询等场景。",
                "difficulty": 2,
            },
        ]
        for ex_data in exercises_data:
            db.add(Exercise(**ex_data, concepts=[]))

        # 7b. Link concepts to source (for knowledge graph)
        from app.db.models.concept import ConceptSource
        for cid in CONCEPT_IDS:
            db.add(ConceptSource(concept_id=cid, source_id=SOURCE_ID, context="demo"))

        # 8. Review items (spaced repetition)
        now = datetime.utcnow()
        for i in range(3):
            db.add(ReviewItem(
                user_id=LOCAL_USER_ID,
                concept_id=CONCEPT_IDS[i],
                exercise_id=EXERCISE_IDS[i] if i < len(EXERCISE_IDS) else None,
                easiness=2.5,
                interval_days=1,
                repetitions=0,
                review_at=now - timedelta(hours=1),  # Due now
            ))

        # 9. Section progress (partial)
        db.add(SectionProgress(user_id=LOCAL_USER_ID, section_id=SECTION_IDS[0], lesson_read=True, lab_completed=False, exercise_best_score=None))
        db.add(SectionProgress(user_id=LOCAL_USER_ID, section_id=SECTION_IDS[1], lesson_read=True, lab_completed=False, exercise_best_score=85.0))

        await db.commit()
        print("Demo data seeded successfully!")
        print(f"  Course: {COURSE_ID}")
        print(f"  Sections: {len(SECTION_IDS)}")
        print(f"  Exercises: {len(exercises_data)}")
        print(f"  Lab: {LAB_ID}")
        print(f"  Review items: 3 (due now)")
        print(f"  Progress: section 1 (lesson read), section 2 (lesson read + 85%)")


if __name__ == "__main__":
    asyncio.run(seed())
