"use client";

interface StudyAsideProps {
  courseTitle: string;
  currentSectionTitle: string;
  progressLabel: string;
  onOpenTutor: () => void;
  onClose?: () => void;
}

export default function StudyAside({
  courseTitle,
  currentSectionTitle,
  progressLabel,
  onOpenTutor,
  onClose,
}: StudyAsideProps) {
  return (
    <aside className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-slate-400">
            Study Support
          </p>
          <h2 className="mt-1 text-lg font-semibold text-slate-900">学习辅助区</h2>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-3 py-1 text-sm text-slate-500 transition hover:bg-slate-100 xl:hidden"
          >
            关闭
          </button>
        ) : null}
      </div>

      <div className="mt-5 space-y-4">
        <section className="rounded-2xl bg-slate-50 p-4">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">
            当前学习
          </p>
          <p className="mt-2 text-base font-semibold text-slate-900">{currentSectionTitle}</p>
          <p className="mt-1 text-sm text-slate-500">{courseTitle}</p>
          <p className="mt-3 inline-flex rounded-full bg-white px-3 py-1 text-sm font-medium text-slate-600 shadow-sm">
            {progressLabel}
          </p>
        </section>

        <section className="rounded-2xl border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-slate-900">下一步建议</h3>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            先看完当前章节内容，再把疑问抛给导师，最后用章节切换继续推进。
          </p>
        </section>

        <button
          type="button"
          onClick={onOpenTutor}
          className="inline-flex w-full items-center justify-center rounded-2xl bg-blue-600 px-4 py-3 text-sm font-medium text-white transition hover:bg-blue-700"
        >
          打开 AI 导师
        </button>
      </div>
    </aside>
  );
}
