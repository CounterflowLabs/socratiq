# Observability — OpenTelemetry traces + metrics

> Status: implemented in `app/services/observability/`
> Linear: [SOC-16](https://linear.app/socratiq-study/issue/SOC-16/wire-agentruntime-trace-events-to-opentelemetry-apm)

`AgentRuntime` (`app/services/llm/runtime.py`) and `MentorAgent`
(`app/agent/mentor.py`) emit structured trace events at every phase
boundary, provider call, validation failure, and agent-loop iteration. The
default `LoggingTracer` ships them as one JSON line per event under the
`agent.trace` logger — good for `grep`, useless for production APM.

`OtelTracer` (`app/services/observability/otel_tracer.py`) translates the same
event stream into:

- An OpenTelemetry **span tree** that mirrors the agent / generation pipeline
- A set of **metrics** covering latency, token spend, fallback / validation
  failure rates, and course-generation outcome counts
- A **plan_finalized** / **course_finalized** rollup that closes the blind
  spot in SectionPlanner Layer 3/4 and CourseGenerator end-to-end stats

Plus auto-instrumentation for FastAPI / asyncpg / Celery / httpx so the
full HTTP → Celery → DB → external LLM HTTP chain is visible.

## When OTel is active

`init_otel()` (`app/services/observability/bootstrap.py`) checks the
`OTEL_EXPORTER_OTLP_ENDPOINT` env var. If unset, the call is a no-op and the
runtime keeps `LoggingTracer` — dev, tests, and CI all behave as before.

When the env var is set (e.g. `http://otel-lgtm:4317` from docker-compose),
bootstrap installs the OTel SDK, registers auto-instrumentations, and swaps
the runtime's default tracer for `OtelTracer`. Wiring lives at the top of
`app/main.py` and `app/worker/celery_app.py` so the swap happens before any
service constructs an `AgentRuntime`.

## Span tree

Events → spans/events mapping:

| Event (`emit()`)                          | OTel mapping |
|---|---|
| `phase_start` / `phase_end`               | one span, name = phase |
| `provider_call`                           | child span `provider_call`, retroactively timed |
| `provider_fallback`                       | `span.add_event("provider_fallback", …)` on phase span |
| `provider_resolve_failed`                 | `span.add_event(…)` |
| `validation_failed` / `validation_retry`  | `span.add_event(…)` |
| `agent_turn_start` / `agent_turn_end`     | one span `mentor.turn` |
| `agent_loop_iter`                         | child span `mentor.loop.iter[N]` |
| `agent_tool_result`                       | child span `mentor.tool.<name>` (under loop iter) |
| `section_planner.plan_finalized`          | one span `section_planner.plan` |
| `course_generation.course_finalized`      | one span `course_generation.finalize` |
| Unknown events                            | fall-through `span.add_event(name, …)` on current span |

Auto-instrumented spans the OtelTracer doesn't have to emit:

| Source | Span name examples |
|---|---|
| `opentelemetry-instrumentation-fastapi`   | `POST /api/v1/chat`, `POST /api/v1/courses/generate` |
| `opentelemetry-instrumentation-asyncpg`   | `SELECT chunks WHERE …` |
| `opentelemetry-instrumentation-celery`    | `celery.task content_ingestion.ingest_source` |
| `opentelemetry-instrumentation-httpx`     | `POST api.anthropic.com/v1/messages` |

Sample trace tree for a full course-generation pipeline:

```
celery.task content_ingestion.ingest_source           [auto]
├─ content_analyzer.batch[1/N]                        [phase]
│  └─ provider_call (claude-sonnet-4-6)               [phase child]
└─ section_planner.plan                               [plan_finalized]
   ├─ section_planner.layer2.window[1/3]              [phase, parallel sibling]
   ├─ section_planner.layer2.window[2/3]
   ├─ section_planner.layer2.window[3/3]
   └─ section_planner.stitch_seam (xN)                [phase]

celery.task course_generation.generate_course         [auto]
├─ lesson_generator.generate (xN)                     [phase, Semaphore-gated parallelism]
├─ lab_generator.generate (xM)                        [phase]
└─ course_generation.finalize                         [course_finalized rollup]

http POST /api/v1/chat                                [auto]
└─ mentor.turn                                        [agent_turn_*]
   ├─ mentor.loop.iter[1]                             [agent_loop_iter]
   │  ├─ POST api.anthropic.com/v1/messages           [auto httpx]
   │  └─ mentor.tool.search_knowledge                 [agent_tool_result]
   │     └─ SELECT chunks WHERE …                     [auto asyncpg]
   └─ mentor.loop.iter[2]
```

## Metrics

Twelve explicit instruments declared in `_AgentMetrics`. Auto-instrumentation
adds `http.server.duration`, `db.client.duration`, `messaging.celery.duration`
on top.

| Instrument | Type | Labels | Source event |
|---|---|---|---|
| `socratiq.agent.phase.duration_ms`                  | Histogram | phase, status, provider_used      | phase_end |
| `socratiq.agent.provider.tokens`                    | Counter   | provider, phase, direction (in/out) | provider_call |
| `socratiq.agent.provider.fallback_total`            | Counter   | from_provider, phase              | provider_fallback / resolve_failed |
| `socratiq.agent.validation.failed_total`            | Counter   | phase, reason                     | validation_failed |
| `socratiq.agent.turn.duration_ms`                   | Histogram | status                            | agent_turn_end |
| `socratiq.agent.turn.loop_iterations`               | Histogram | status                            | agent_turn_end |
| `socratiq.agent.tool.duration_ms`                   | Histogram | tool_name, status                 | agent_tool_result |
| `socratiq.section_planner.plan_total`               | Counter   | tier_used, short_circuit, has_error | plan_finalized |
| `socratiq.section_planner.bucket_count`             | Histogram | tier_used                         | plan_finalized |
| `socratiq.course_generation.duration_ms`            | Histogram | status (ok / partial / failed)    | course_finalized |
| `socratiq.course_generation.lesson.outcome_total`   | Counter   | status (ok / failed)              | course_finalized |
| `socratiq.course_generation.lab.outcome_total`      | Counter   | status (ok / skipped / failed)    | course_finalized |

**High cardinality** — `course_id`, `user_id`, `tool_use_id` never enter
metric labels (would explode Prometheus series count). They land on span
attributes instead, queryable via Tempo span search.

**Semantic conventions** — token counts and model id follow OTel GenAI
SemConv (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.request.model`). Project-specific fields use the `socratiq.*`
namespace.

## Grafana query cheat sheet

Connect to `http://localhost:3001` after `docker compose --profile apm up`.

**Course generation p95 latency (Celery task)**
```promql
histogram_quantile(0.95,
  sum by (le) (
    rate(messaging_celery_duration_bucket{
      messaging_celery_task_name="course_generation.generate_course"
    }[5m])
  )
)
```

**SectionPlanner fallback rate (Layer 4 escapes)**
```promql
sum(rate(socratiq_section_planner_plan_total{tier_used="fallback"}[5m]))
/
sum(rate(socratiq_section_planner_plan_total[5m]))
```

**LessonGenerator validation-failure rate**
```promql
rate(socratiq_agent_validation_failed_total{phase="lesson_generator.generate"}[5m])
/
rate(socratiq_agent_phase_duration_ms_count{phase="lesson_generator.generate"}[5m])
```

**Per-phase token spend (output direction, last hour, top 5)**
```promql
topk(5,
  sum by (phase) (
    rate(socratiq_agent_provider_tokens{direction="out"}[1h])
  )
)
```

**Course lesson failure rate**
```promql
sum(rate(socratiq_course_generation_lesson_outcome_total{status="failed"}[10m]))
/
sum(rate(socratiq_course_generation_lesson_outcome_total[10m]))
```

**Single-course audit in Tempo**
```
{service.name="socratiq-worker" name="course_generation.finalize" socratiq.course_id="<uuid>"}
```
Click the span — attributes include `lesson_ok`, `lesson_failed`, `lab_ok`,
`lab_skipped`, `lab_failed`, and total LLM token spend (from the
`section_planner.plan` child span's `llm_input_tokens`/`llm_output_tokens`).

## Running locally

```bash
# Bring up the LGTM stack alongside the app
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-lgtm:4317
docker compose --profile apm up

# Drive some load
curl -X POST localhost:8000/api/v1/sources -d '{"url":"…"}'   # ingest
curl -X POST localhost:8000/api/v1/courses/generate -d '{…}'  # generate
curl -X POST localhost:8000/api/v1/chat -d '{"message":"…"}'  # chat

# Inspect at localhost:3001 → Explore → Tempo (traces) / Prometheus (metrics)
```

Without `--profile apm` or with `OTEL_EXPORTER_OTLP_ENDPOINT` unset, OTel
stays disabled and the runtime keeps logging to `agent.trace`.

## Adding a new event

`OtelTracer._HANDLERS` maps event names to handlers. Unknown events fall
through to `span.add_event(name, attrs)` on the current span — so a fresh
runtime event becomes immediately observable in Tempo without an OtelTracer
release. Add an explicit handler when:

- the event has a duration field (`elapsed_ms`) you want as a metric
- the event should appear as a span of its own
- the event has high-cardinality fields you want kept off metric labels

Handler signature: `_on_<event>(self, fields: dict) -> None`. Register in
the `_HANDLERS` dict at the bottom of the module.

## Testing

`tests/services/observability/test_otel_tracer.py` uses
`InMemorySpanExporter` + `InMemoryMetricReader` to assert span tree shape,
parent/child relationships, and metric label/value correctness for every
event type. Async-context propagation is covered by a `asyncio.gather`
test that mimics SectionPlanner Layer 2.

`tests/services/observability/test_bootstrap.py` covers env-gating,
idempotency, graceful failure on SDK init errors, and the `instrument_fastapi`
no-op path.
