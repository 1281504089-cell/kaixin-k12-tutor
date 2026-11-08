"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { Check, Clapperboard, List, LoaderCircle, Square, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import type { MediaJob } from "./media-jobs";
import { takeMediaSendOrigin } from "./send-origin";

const MathPlayer = dynamic(() => import("@/components/math-animator/MathAnimatorViewer"), { ssr: false });
const LessonPlayer = dynamic(() => import("@/components/video-lesson/VideoLessonViewer"), { ssr: false });

export default function MediaGenerationTray() {
  const { mediaJobs, stopMediaGeneration } = useChatStateAdapter();
  if (!mediaJobs.length) return null;
  return <MediaTray jobs={mediaJobs} stopJob={stopMediaGeneration} />;
}

function MediaTray({ jobs, stopJob }: {
  jobs: MediaJob[];
  stopJob: (jobId: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [view, setView] = useState<string | null>(null);
  const [dismissedId, setDismissedId] = useState<string | null>(null);
  const [seenReadyId, setSeenReadyId] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const deliveryIcon = useRef<HTMLSpanElement>(null);
  const delivery = useRef<Animation | null>(null);
  const knownJobs = useRef(new Set<string>());
  useEffect(() => {
    const started = jobs.find(job => job.status === "running" && !knownJobs.current.has(job.id));
    knownJobs.current = new Set(jobs.map(job => job.id));
    const destination = trigger.current;
    if (!started || !destination) return;
    const origin = takeMediaSendOrigin(started.kind);
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || typeof destination.animate !== "function") return;
    delivery.current?.cancel();
    if (!origin || !deliveryIcon.current) {
      delivery.current = destination.animate([{ opacity: 0.65 }, { opacity: 1 }], { duration: 180 });
      return;
    }
    const bounds = destination.getBoundingClientRect();
    const icon = deliveryIcon.current;
    const half = icon.offsetWidth / 2;
    const transform = (x: number, y: number, scale: number) =>
      `translate3d(${x - half}px, ${y - half}px, 0) scale(${scale})`;
    delivery.current = icon.animate([
      { transform: transform(origin.x, origin.y, 0.85), opacity: 0.9 },
      { transform: transform(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2, 0.3), opacity: 0 },
    ], { duration: 320, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
  }, [jobs]);
  useEffect(() => () => delivery.current?.cancel(), []);
  const latestReady = jobs.find(job => job.status === "ready");
  const hasNewResult = Boolean(latestReady && latestReady.id !== seenReadyId);
  const autoOpen = latestReady && latestReady.id !== dismissedId ? latestReady : undefined;
  const stopping = jobs.some(job => job.status === "running" && job.stopRequested);
  const openJob = view === "list" && stopping ? undefined : view && view !== "list" ? jobs.find(job => job.id === view) : autoOpen;
  const expanded = Boolean(openJob || view === "list");
  const runningCount = jobs.filter(job => job.status === "running").length;
  const showGenerationHint = runningCount > 0 && !openJob;

  const changeView = (next: typeof view) => {
    setDismissedId(latestReady?.id ?? null);
    setView(next);
    if (latestReady && (next === latestReady.id || (next === null && openJob?.id === latestReady.id))) {
      setSeenReadyId(latestReady.id);
    }
    if (next === null) trigger.current?.focus();
  };

  // Escape is local to the player and its controls so generation completing
  // never captures focus from a student's current typing or reading.
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !panel.current?.contains(document.activeElement)) return;
      setDismissedId(latestReady?.id ?? null);
      setView(null);
      if (openJob && openJob.id === latestReady?.id) setSeenReadyId(openJob.id);
      trigger.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [expanded, latestReady?.id, openJob]);

  const label = (job: MediaJob) => job.kind === "math_animator" ? t("Math Animator") : t("Video Lesson");

  return (
    <aside aria-label={t("student.media.jobs")} className="pointer-events-none fixed right-3 top-14 z-30 flex w-[min(28rem,calc(100vw-1.5rem))] flex-col items-end gap-2 sm:right-5">
      <span ref={deliveryIcon} aria-hidden
        className="pointer-events-none fixed left-0 top-0 z-10 grid size-7 place-items-center rounded-full bg-[var(--primary)] text-[var(--primary-foreground)] opacity-0">
        <Clapperboard size={14} />
      </span>
      <button ref={trigger} type="button" aria-label={t("student.media.jobs")} aria-expanded={expanded} aria-controls={expanded ? "student-media-panel" : undefined}
        aria-describedby={showGenerationHint ? "student-media-generation-hint" : undefined}
        onClick={() => changeView(expanded ? null : runningCount ? "list" : latestReady?.id ?? "list")}
        className="pointer-events-auto relative inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs font-medium shadow-sm hover:bg-[var(--muted)]">
        {runningCount ? <LoaderCircle size={15} aria-hidden className="motion-safe:animate-spin" /> : <Clapperboard size={15} aria-hidden />}
        <span role="status">
          {runningCount ? t("student.media.running", { count: runningCount }) : t("student.media.jobs")}
          {hasNewResult ? <span className="sr-only"> · {t("student.media.newResult")}</span> : null}
        </span>
        {hasNewResult ? <span aria-hidden className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full bg-emerald-500 ring-2 ring-[var(--background)]" /> : null}
      </button>

      {showGenerationHint ? (
        <p id="student-media-generation-hint"
          className="max-w-72 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs leading-5 text-[var(--muted-foreground)] shadow-sm">
          {t("student.media.generationHint")}
        </p>
      ) : null}

      {expanded ? (
        <section ref={panel} id="student-media-panel" aria-labelledby="student-media-heading"
          className="pointer-events-auto flex max-h-[calc(100dvh-7rem)] w-full min-w-0 flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--background)] shadow-xl motion-safe:animate-fade-in">
          <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <Clapperboard size={16} aria-hidden className="shrink-0 text-[var(--primary)]" />
              <h2 id="student-media-heading" className="truncate text-sm font-semibold">{openJob ? label(openJob) : t("student.media.jobs")}</h2>
            </div>
            <div className="flex shrink-0 gap-1">
              {openJob ? <button type="button" title={t("student.media.jobs")} aria-label={t("student.media.jobs")} onClick={() => changeView("list")}
                className="rounded-lg p-2 hover:bg-[var(--muted)]"><List size={16} /></button> : null}
              <button type="button" title={t("student.media.collapse")} aria-label={t("student.media.collapse")} onClick={() => changeView(null)}
                className="rounded-lg p-2 hover:bg-[var(--muted)]"><X size={16} /></button>
            </div>
          </div>
          {openJob ? (
            <div key={openJob.id} className="min-h-0 min-w-0 overflow-y-auto p-3">
              {openJob.output?.kind === "math_animator" && <MathPlayer result={openJob.output.result} />}
              {openJob.output?.kind === "video_lesson" && <LessonPlayer result={openJob.output.result} />}
            </div>
          ) : (
            <ul className="min-h-0 overflow-y-auto p-2">
              {jobs.map(job => (
                <li key={job.id} className="flex min-w-0 items-center justify-between gap-2 rounded-xl px-2 py-1.5 text-sm">
                  <div className="min-w-0">
                    <div className="truncate">{job.output?.kind === "video_lesson" && job.output.result.title || label(job)}</div>
                    {job.prompt ? <div title={job.prompt} className="truncate text-xs text-[var(--muted-foreground)]">{job.prompt}</div> : null}
                  </div>
                  {job.status === "ready" ? (
                    <button type="button" onClick={() => changeView(job.id)} className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1.5 text-xs text-[var(--primary)] hover:bg-[var(--muted)]">
                      <Check size={14} aria-hidden />{t("student.media.watch")}
                    </button>
                  ) : job.status === "running" ? (
                    <button type="button" disabled={!job.turnId || job.stopRequested}
                      aria-label={t("student.media.stopNamed", { title: job.prompt || label(job) })}
                      onClick={() => void stopJob(job.id)}
                      className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1.5 text-xs hover:bg-[var(--muted)] disabled:opacity-50">
                      <Square size={12} aria-hidden />
                      {t(job.stopRequested ? "student.media.stopping" : "student.media.stop")}
                    </button>
                  ) : (
                    <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
                      {t(job.status === "cancelled" ? "student.media.stopped" : "student.media.unavailable")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </aside>
  );
}
