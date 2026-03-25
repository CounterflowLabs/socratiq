# Sub-project B: Content Ingestion Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the content ingestion pipeline — users submit a Bilibili URL or upload a PDF, the system asynchronously extracts, analyzes, embeds, and generates a structured course.

**Architecture:** Extractors → LLM ContentAnalyzer → EmbeddingService → CourseGenerator, orchestrated by a Celery task (`ingest_source`). API routes expose sources + courses endpoints. All LLM calls go through `services/llm/` abstraction layer.

**Tech Stack:** Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy (async) · Celery · bilibili-api-python · pymupdf · pgvector

**Design Spec:** `docs/superpowers/specs/2026-03-24-subproject-b-content-ingestion-design.md`

**Project Conventions:** `CLAUDE.md`

---

## Pre-requisites

Before starting, verify Sub-project A is in place:

```bash
cd backend && .venv/bin/python -m pytest -v  # All existing tests pass
.venv/bin/python -c "from app.main import app; print('FastAPI OK')"
.venv/bin/python -c "from app.services.llm.router import ModelRouter, TaskType; print('LLM OK')"
.venv/bin/python -c "from app.worker.celery_app import celery_app; print('Celery OK')"
```

---

## Task 1: Directory Structure + Base Extractor Types

**Files:**
- Create: `backend/app/tools/__init__.py`
- Create: `backend/app/tools/extractors/__init__.py` (empty initially)
- Create: `backend/app/tools/extractors/base.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p backend/app/tools/extractors
touch backend/app/tools/__init__.py
touch backend/app/tools/extractors/__init__.py
```

- [ ] **Step 2: Implement base extractor types**

Create `backend/app/tools/extractors/base.py` with:
- `RawContentChunk(BaseModel)` — source_type, raw_text, metadata, media_url
- `ExtractionResult(BaseModel)` — title, chunks, metadata
- `ContentExtractor(ABC)` — abstract `extract()` and `supported_source_type()`
- `ExtractionError(Exception)` — with source_type and details

Copy the exact implementation from design spec Section 2.1.

- [ ] **Step 3: Verify imports**

```bash
cd backend
.venv/bin/python -c "from app.tools.extractors.base import ContentExtractor, RawContentChunk, ExtractionResult, ExtractionError; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/tools/
git commit -m "feat(content): add base extractor types — RawContentChunk, ExtractionResult, ContentExtractor ABC"
```

---

## Task 2: BilibiliExtractor Implementation

**Files:**
- Create: `backend/app/tools/extractors/bilibili.py`

- [ ] **Step 1: Implement BilibiliExtractor**

Create `backend/app/tools/extractors/bilibili.py` from design spec Section 2.2. Key methods:
- `_parse_bvid(url)` — extract BV号 from URL
- `_pick_best_subtitle(subtitles)` — priority: CC zh-CN > CC zh > AI zh > fallback
- `_group_subtitle_segments(segments, ...)` — group into ~60s windows
- `extract(source, **kwargs)` — async, fetch video info + subtitles

- [ ] **Step 2: Verify import**

```bash
cd backend
.venv/bin/python -c "from app.tools.extractors.bilibili import BilibiliExtractor; print(BilibiliExtractor().supported_source_type())"
```
Expected: `bilibili`

---

## Task 3: BilibiliExtractor Tests

**Files:**
- Create: `backend/tests/tools/__init__.py`
- Create: `backend/tests/tools/extractors/__init__.py`
- Create: `backend/tests/tools/extractors/fixtures/bilibili_subtitle.json`
- Create: `backend/tests/tools/extractors/test_bilibili.py`

- [ ] **Step 1: Create test directories and fixture**

```bash
mkdir -p backend/tests/tools/extractors/fixtures
touch backend/tests/tools/__init__.py
touch backend/tests/tools/extractors/__init__.py
```

Create fixture file `backend/tests/tools/extractors/fixtures/bilibili_subtitle.json` with the sample data from design spec Section 11 (Bilibili response fixture).

- [ ] **Step 2: Write BilibiliExtractor tests**

Create `backend/tests/tools/extractors/test_bilibili.py`. Test cases:
1. `test_parse_bvid_full_url` — `https://www.bilibili.com/video/BV1xx411c7XW` → `BV1xx411c7XW`
2. `test_parse_bvid_short_url` — `https://b23.tv/BV1xx411c7XW` → `BV1xx411c7XW`
3. `test_parse_bvid_raw` — `BV1xx411c7XW` → `BV1xx411c7XW`
4. `test_parse_bvid_with_params` — URL with `?p=2` → correct BV号
5. `test_parse_bvid_invalid` — raises `ExtractionError`
6. `test_pick_best_subtitle_cc_zhcn` — CC zh-CN preferred
7. `test_pick_best_subtitle_ai_fallback` — AI subtitle when no CC
8. `test_group_subtitle_segments` — groups into ~60s windows
9. `test_group_subtitle_segments_empty` — returns `[]`
10. `test_extract_success` — mock `video.Video`, verify full pipeline (mock all httpx/bilibili_api calls)

All tests must mock external dependencies. No real API calls.

- [ ] **Step 3: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/tools/extractors/test_bilibili.py -v
```
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/tools/extractors/bilibili.py backend/tests/tools/
git commit -m "feat(content): implement BilibiliExtractor with subtitle extraction and tests"
```

---

## Task 4: PDFExtractor Implementation + Tests

**Files:**
- Create: `backend/app/tools/extractors/pdf.py`
- Create: `backend/tests/tools/extractors/fixtures/sample.pdf`
- Create: `backend/tests/tools/extractors/test_pdf.py`

- [ ] **Step 1: Implement PDFExtractor**

Create `backend/app/tools/extractors/pdf.py` from design spec Section 2.3. Key methods:
- `_extract_page(page, page_num)` — text + font info from single page
- `_detect_heading_threshold(raw_pages)` — body_size + 2pt heuristic
- `_build_sections(raw_pages, heading_threshold)` — group by headings
- `extract(source, **kwargs)` — async, open PDF, extract structured content

- [ ] **Step 2: Create test PDF fixture**

Create a minimal sample PDF at `backend/tests/tools/extractors/fixtures/sample.pdf` using Python:

```python
import fitz
doc = fitz.open()
page = doc.new_page()
# Insert heading (larger font)
page.insert_text((72, 72), "Chapter 1: Introduction", fontsize=18)
# Insert body text
page.insert_text((72, 120), "This is body text about machine learning.", fontsize=12)
page.insert_text((72, 140), "Supervised learning uses labeled data.", fontsize=12)
# Page 2
page2 = doc.new_page()
page2.insert_text((72, 72), "Chapter 2: Methods", fontsize=18)
page2.insert_text((72, 120), "Neural networks are a popular approach.", fontsize=12)
doc.save("backend/tests/tools/extractors/fixtures/sample.pdf")
doc.close()
```

- [ ] **Step 3: Write PDFExtractor tests**

Create `backend/tests/tools/extractors/test_pdf.py`. Test cases:
1. `test_supported_source_type` — returns `"pdf"`
2. `test_extract_sample_pdf` — extracts correct title and chunks from fixture
3. `test_extract_heading_detection` — verifies heading/body split
4. `test_extract_file_not_found` — raises `ExtractionError`
5. `test_extract_max_pages` — respects `max_pages` parameter

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/tools/extractors/test_pdf.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/extractors/pdf.py backend/tests/tools/extractors/test_pdf.py backend/tests/tools/extractors/fixtures/sample.pdf
git commit -m "feat(content): implement PDFExtractor with heading detection and tests"
```

---

## Task 5: Extractor Registry

**Files:**
- Modify: `backend/app/tools/extractors/__init__.py`

- [ ] **Step 1: Implement extractor registry**

Replace `backend/app/tools/extractors/__init__.py` with the full registry from design spec Section 2.4:
- `EXTRACTORS` dict mapping source_type → class
- `get_extractor(source_type, **kwargs)` factory function
- `__all__` exports

- [ ] **Step 2: Verify**

```bash
cd backend
.venv/bin/python -c "from app.tools.extractors import get_extractor; print(type(get_extractor('bilibili')))"
.venv/bin/python -c "from app.tools.extractors import get_extractor; print(type(get_extractor('pdf')))"
```
Expected: Correct class types printed.

- [ ] **Step 3: Commit**

```bash
git add backend/app/tools/extractors/__init__.py
git commit -m "feat(content): wire up extractor registry with get_extractor() factory"
```

---

## Task 6: ContentAnalyzer Service

**Files:**
- Create: `backend/app/services/content_analyzer.py`
- Create: `backend/tests/services/test_content_analyzer.py`

- [ ] **Step 1: Write ContentAnalyzer test (TDD)**

Create `backend/tests/services/test_content_analyzer.py`. Test cases:
1. `test_analyze_single_chunk` — mock LLM returns valid JSON, verify `AnalysisResult`
2. `test_analyze_multiple_chunks` — verify batch processing
3. `test_analyze_llm_json_parsing` — verify JSON extraction from LLM response
4. `test_analysis_result_validation` — verify Pydantic models instantiate correctly

Mock the `ModelRouter.get_provider()` to return a mock `LLMProvider`.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_content_analyzer.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Implement ContentAnalyzer**

Create `backend/app/services/content_analyzer.py` from design spec Section 3. Include:
- Pydantic models: `ExtractedConcept`, `AnalyzedChunk`, `AnalysisResult`
- `ContentAnalyzer` class with `analyze(chunks, source_title)` method
- LLM prompt that instructs JSON-only output
- Batch splitting at ~6000 chars
- JSON extraction fallback parser

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_content_analyzer.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/content_analyzer.py backend/tests/services/test_content_analyzer.py
git commit -m "feat(content): implement ContentAnalyzer with LLM-powered analysis and tests"
```

---

## Task 7: EmbeddingService

**Files:**
- Create: `backend/app/services/embedding.py`
- Create: `backend/tests/services/test_embedding.py`

- [ ] **Step 1: Write EmbeddingService test (TDD)**

Create `backend/tests/services/test_embedding.py`. Test cases:
1. `test_embed_chunks` — mock embedding provider, verify vectors written to DB
2. `test_embed_concepts` — verify concept embedding
3. `test_batch_embedding` — verify batching for large input

Mock `ModelRouter.get_provider(TaskType.EMBEDDING)`.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_embedding.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement EmbeddingService**

Create `backend/app/services/embedding.py` from design spec Section 4. Include:
- `EmbeddingService` class with `embed_chunks()` and `embed_concepts()`
- Calls `ModelRouter.get_provider(TaskType.EMBEDDING)`
- Batch processing for efficiency
- Writes vectors to `content_chunks.embedding` and `concepts.embedding`

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_embedding.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/embedding.py backend/tests/services/test_embedding.py
git commit -m "feat(content): implement EmbeddingService for content chunk and concept embedding"
```

---

## Task 8: CourseGenerator Service

**Files:**
- Create: `backend/app/services/course_generator.py`
- Create: `backend/tests/services/test_course_generator.py`

- [ ] **Step 1: Write CourseGenerator test (TDD)**

Create `backend/tests/services/test_course_generator.py`. Test cases:
1. `test_generate_course_from_single_source` — verify Course + Sections created
2. `test_generate_course_from_multiple_sources` — merged content
3. `test_section_ordering` — verify sections are ordered by difficulty/sequence

Mock LLM calls.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_course_generator.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement CourseGenerator**

Create `backend/app/services/course_generator.py` from design spec Section 5. Include:
- `CourseGenerator` class with `generate(source_ids, user_id)`
- Creates `Course`, `CourseSource`, and `Section` ORM records
- LLM call for structuring sections from analyzed content
- Concept-to-section mapping

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_course_generator.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/course_generator.py backend/tests/services/test_course_generator.py
git commit -m "feat(content): implement CourseGenerator for automatic course creation"
```

---

## Task 9: Celery Ingestion Task

**Files:**
- Create: `backend/app/worker/tasks/content_ingestion.py`
- Create: `backend/tests/worker/__init__.py`
- Create: `backend/tests/worker/test_content_ingestion.py`

- [ ] **Step 1: Write ingestion task test (TDD)**

Create `backend/tests/worker/test_content_ingestion.py`. Test cases:
1. `test_ingest_source_bilibili_success` — mock all services, verify status transitions: pending → extracting → analyzing → storing → embedding → ready
2. `test_ingest_source_pdf_success` — same flow for PDF
3. `test_ingest_source_extraction_failure` — verify status → error with error details
4. `test_ingest_source_analysis_failure` — verify error handling at analysis step

Mock all external dependencies (extractors, analyzer, embedding service).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/worker/test_content_ingestion.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement ingest_source task**

Create `backend/app/worker/tasks/content_ingestion.py` from design spec Section 6. Include:
- `ingest_source(source_id)` Celery task
- Status transitions on the Source record
- Pipeline: extract → analyze → store → embed → ready
- Error handling with status=error and error details in metadata_

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/worker/test_content_ingestion.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker/tasks/ backend/tests/worker/
git commit -m "feat(content): implement ingest_source Celery task with full pipeline"
```

---

## Task 10: Pydantic API Schemas

**Files:**
- Create: `backend/app/models/source.py`
- Create: `backend/app/models/course.py`

- [ ] **Step 1: Create source schemas**

Create `backend/app/models/source.py` from design spec Section 7. Include:
- `SourceCreate(BaseModel)` — url, source_type
- `SourceResponse(BaseModel)` — id, url, source_type, title, status, metadata_, created_at
- `SourceUploadResponse(BaseModel)` — source + task_id

- [ ] **Step 2: Create course schemas**

Create `backend/app/models/course.py` from design spec Section 7. Include:
- `SectionResponse(BaseModel)` — id, title, order, difficulty, summary, metadata_
- `CourseResponse(BaseModel)` — id, title, description, sections, source_count, created_at
- `CourseGenerateRequest(BaseModel)` — source_ids, title (optional)

- [ ] **Step 3: Verify**

```bash
cd backend
.venv/bin/python -c "from app.models.source import SourceCreate, SourceResponse; print('OK')"
.venv/bin/python -c "from app.models.course import CourseResponse, CourseGenerateRequest; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/source.py backend/app/models/course.py
git commit -m "feat(content): add Pydantic schemas for sources and courses API"
```

---

## Task 11: Sources API Routes

**Files:**
- Create: `backend/app/api/routes/sources.py`
- Create: `backend/tests/api/test_sources_api.py`

- [ ] **Step 1: Write sources API tests (TDD)**

Create `backend/tests/api/test_sources_api.py`. Test cases:
1. `test_create_source_bilibili` — POST with URL, verify 201 + Source returned
2. `test_create_source_pdf_upload` — POST multipart with PDF file, verify 201
3. `test_get_source` — GET by ID, verify response format
4. `test_list_sources` — GET all, verify list response
5. `test_create_source_invalid_url` — verify 422 validation error

Use FastAPI `TestClient` with mocked DB and mocked Celery task.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/api/test_sources_api.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement sources routes**

Create `backend/app/api/routes/sources.py` from design spec Section 8. Endpoints:
- `POST /api/sources` — create source from URL
- `POST /api/sources/upload` — upload PDF
- `GET /api/sources/{source_id}` — get source by ID
- `GET /api/sources` — list all sources

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/api/test_sources_api.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/sources.py backend/tests/api/test_sources_api.py
git commit -m "feat(content): implement Sources API routes (POST/GET)"
```

---

## Task 12: Courses API Routes

**Files:**
- Create: `backend/app/api/routes/courses.py`
- Create: `backend/tests/api/test_courses_api.py`

- [ ] **Step 1: Write courses API tests (TDD)**

Create `backend/tests/api/test_courses_api.py`. Test cases:
1. `test_generate_course` — POST with source_ids, verify 201 + Course returned
2. `test_get_course` — GET by ID, verify course with sections
3. `test_list_courses` — GET all, verify list response
4. `test_generate_course_no_ready_sources` — verify 400 error for unready sources

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/api/test_courses_api.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement courses routes**

Create `backend/app/api/routes/courses.py` from design spec Section 8. Endpoints:
- `POST /api/courses/generate` — generate course from sources
- `GET /api/courses/{course_id}` — get course with sections
- `GET /api/courses` — list all courses

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/api/test_courses_api.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/courses.py backend/tests/api/test_courses_api.py
git commit -m "feat(content): implement Courses API routes (generate/list/get)"
```

---

## Task 13: Wire Up Routers + Config + Dependencies

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Modify: `backend/pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Register routers in main.py**

Add to `backend/app/main.py`:
```python
from app.api.routes import sources, courses
app.include_router(sources.router, prefix="/api")
app.include_router(courses.router, prefix="/api")
```

- [ ] **Step 2: Add Bilibili config to Settings**

Add to `backend/app/config.py`:
```python
bilibili_sessdata: str = ""
bilibili_bili_jct: str = ""
bilibili_buvid3: str = ""
upload_dir: str = "uploads"
```

- [ ] **Step 3: Add new dependencies to pyproject.toml**

Add to `backend/pyproject.toml` dependencies:
```
"bilibili-api-python>=16.0",
"pymupdf>=1.24",
"python-multipart",
```

- [ ] **Step 4: Update .env.example**

Add variables: `BILIBILI_SESSDATA`, `BILIBILI_BILI_JCT`, `BILIBILI_BUVID3`, `UPLOAD_DIR`

- [ ] **Step 5: Install and verify**

```bash
cd backend
uv pip install -e .
.venv/bin/python -c "from app.main import app; print('FastAPI OK')"
```
Expected: No import errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/config.py backend/pyproject.toml .env.example
git commit -m "feat(content): wire up routers, add Bilibili config and new dependencies"
```

---

## Task 14: Full Test Suite Verification

- [ ] **Step 1: Run all tests**

```bash
cd backend
.venv/bin/python -m pytest -v --tb=short
```
Expected: All tests pass (including Sub-project A's existing tests).

- [ ] **Step 2: Verify FastAPI starts**

```bash
cd backend
.venv/bin/python -c "from app.main import app; print('OK')"
```

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(content): final test suite fixes for Sub-project B"
```
