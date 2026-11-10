"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Check, Clapperboard, LoaderCircle, Square, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { sessionRoute } from "@/lib/mastery-session";
import { notify } from "@/lib/notifications";
import { getSessionOrganization } from "@/lib/session-api";
import { navigateTask } from "@/lib/workspace-scope";
import type { MediaJob } from "./media-jobs";
import { playMediaDeliverySound, takeMediaSend } from "./send-origin";

const MathPlayer = dynamic(() => import("@/components/math-animator/MathAnimatorViewer"), { ssr: false });
const LessonPlayer = dynamic(() => import("@/components/video-lesson/VideoLessonViewer"), { ssr: false });
const GENERATION_HINT_MS = 2400;
const DELIVERY_MS = 680;

export default function MediaGenerationTray() {
  const { mediaJobs, selectedSessionId, stopMediaGeneration, markMediaViewed, removeMediaJob } = useChatStateAdapter();
  if (!mediaJobs.length) return null;
  return <MediaTray jobs={mediaJobs} selectedSessionId={selectedSessionId} stopJob={stopMediaGeneration}
    markViewed={markMediaViewed} removeJob={removeMediaJob} />;
}

function MediaTray({ jobs, selectedSessionId, stopJob, markViewed, removeJob }: {
  jobs: MediaJob[];
  selectedSessionId: string | null;
  stopJob: (jobId: string) => Promise<void>;
  markViewed: (jobId: string) => void;
  removeJob: (jobId: string) => void;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const sourceLookup = useRef<AbortController | null>(null);
  const [view, setView] = useState<string | null>(null);
  const [dismissedId, setDismissedId] = useState<string | null>(null);
  const [hintJobId, setHintJobId] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const deliveryIcon = useRef<HTMLSpanElement>(null);
  const delivery = useRef<Animation[]>([]);
  const knownJobs = useRef(new Set<string>());
  useEffect(() => {
    const started = jobs.find(job => job.status === "running" && !knownJobs.current.has(job.id));
    knownJobs.current = new Set(jobs.map(job => job.id));
    const destination = trigger.current;
    if (!started || !destination) return;

    setHintJobId(started.id);
    const submission = takeMediaSend(started.kind);
    if (submission) playMediaDeliverySound();
    delivery.current.forEach(animation => animation.cancel());
    delivery.current = [];
    if (typeof destination.animate !== "function") return;

    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const icon = deliveryIcon.current;
    const origin = submission?.point;
    const fly = origin && icon && !reducedMotion && typeof icon.animate === "function";
    const ring = "color-mix(in srgb, var(--primary) 48%, transparent)";
    delivery.current.push(destination.animate([
      { boxShadow: `0 0 0 0 ${ring}`, transform: "scale(1)" },
      { boxShadow: `0 0 0 6px ${ring}`, transform: reducedMotion ? "scale(1)" : "scale(1.08)", offset: 0.36 },
      { boxShadow: "0 0 0 10px transparent", transform: "scale(1)" },
    ], { duration: 390, delay: fly ? DELIVERY_MS - 95 : 0, easing: "ease-out" }));
    if (!fly) return;

    const bounds = destination.getBoundingClientRect();
    const half = icon.offsetWidth / 2;
    const dx = bounds.x + bounds.width / 2 - origin.x;
    const dy = bounds.y + bounds.height / 2 - origin.y;
    const lift = Math.min(90, Math.hypot(dx, dy) * 0.15);
    const point = (progress: number, scale: number) => {
      const x = origin.x + dx * progress - half;
      const y = Math.max(0, origin.y + dy * progress - 4 * lift * progress * (1 - progress) - half);
      return `translate3d(${x}px, ${y}px, 0) scale(${scale})`;
    };
    delivery.current.push(icon.animate([
      { transform: point(0, 0.78), opacity: 1 },
      { transform: point(0.07, 1.06), opacity: 1, offset: 0.2 },
      { transform: point(0.55, 1), opacity: 1, offset: 0.57 },
      { transform: point(0.96, 0.8), opacity: 1, offset: 0.91 },
      { transform: point(1, 0.54), opacity: 0 },
    ], { duration: DELIVERY_MS, easing: "ease-in-out" }));
  }, [jobs]);
  useEffect(() => {
    if (!hintJobId) return;
    const timeout = window.setTimeout(() => setHintJobId(null), GENERATION_HINT_MS);
    return () => window.clearTimeout(timeout);
  }, [hintJobId]);
  useEffect(() => () => {
    delivery.current.forEach(animation => animation.cancel());
    sourceLookup.current?.abort();
  }, []);
  const latestReady = jobs.find(job => job.status === "ready" && !job.restored);
  const hasNewResult = jobs.some(job => job.status === "ready" && !job.viewed);
  const autoOpen = latestReady && !latestReady.viewed && latestReady.id !== dismissedId ? latestReady : undefined;
  const showingList = view === "list";
  const openJob = showingList ? undefined : view ? jobs.find(job => job.id === view) : autoOpen;
  const expanded = Boolean(openJob || showingList);
  const runningCount = jobs.filter(job => job.status === "running").length;
  const showGenerationHint = !expanded && jobs.some(job => job.id === hintJobId && job.status === "running");

  const showList = () => {
    sourceLookup.current?.abort();
    setHintJobId(null);
    setView("list");
  };

  const closePanel = () => {
    sourceLookup.current?.abort();
    setDismissedId(latestReady?.id ?? null);
    if (openJob) markViewed(openJob.id);
    setHintJobId(null);
    setView(null);
    trigger.current?.focus();
  };

  const watchJob = async (job: MediaJob) => {
    sourceLookup.current?.abort();
    setView(job.id);
    markViewed(job.id);
    if (selectedSessionId === job.sessionKey) return;
    const controller = new AbortController();
    sourceLookup.current = controller;
    const currentPage = window.location.href;
    try {
      const session = await getSessionOrganization(job.sessionKey, undefined, controller.signal);
      if (!controller.signal.aborted && window.location.href === currentPage) {
        navigateTask(sessionRoute(session), router.push);
      }
    } catch {
      if (!controller.signal.aborted && window.location.href === currentPage) {
        notify(t("student.media.sourceUnavailable"), { tone: "error" });
      }
    }
  };

  // Escape is local to the player and its controls so automatic previews
  // never take focus away from the student's current work.
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !panel.current?.contains(document.activeElement)) return;
      sourceLookup.current?.abort();
      setDismissedId(latestReady?.id ?? null);
      if (openJob) markViewed(openJob.id);
      setHintJobId(null);
      setView(null);
      trigger.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [expanded, latestReady?.id, markViewed, openJob]);

  const label = (job: MediaJob) => job.kind === "math_animator" ? t("Math Animator") : t("Video Lesson");

  return (
    <aside aria-label={t("student.media.jobs")} className="pointer-events-none fixed right-3 top-14 z-30 flex w-[min(28rem,calc(100vw-1.5rem))] flex-col items-end gap-2 sm:right-5">
      <span ref={deliveryIcon} aria-hidden
        className="pointer-events-none fixed left-0 top-0 z-10 grid size-10 place-items-center rounded-full border-2 border-[var(--primary-foreground)] bg-[var(--primary)] text-[var(--primary-foreground)] opacity-0 shadow-[0_4px_16px_color-mix(in_srgb,var(--primary)_50%,transparent)]">
        <Clapperboard size={19} />
      </span>
      <button ref={trigger} type="button" aria-label={t("student.media.jobs")} aria-expanded={expanded} aria-controls={expanded ? "student-media-panel" : undefined}
        aria-describedby={showGenerationHint ? "student-media-generation-hint" : undefined}
        onClick={showingList ? closePanel : showList}
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
              {openJob && openJob.sessionKey !== selectedSessionId ? (
                <button type="button" onClick={() => void watchJob(openJob)}
                  className="rounded-lg px-2 text-xs text-[var(--primary)] hover:bg-[var(--muted)]">
                  {t("student.media.source")}
                </button>
              ) : null}
              <button type="button" title={t("student.media.collapse")} aria-label={t("student.media.collapse")} onClick={closePanel}
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
                  <div className="flex shrink-0 items-center gap-1">
                    {job.status === "ready" ? (
                      <button type="button" onClick={() => void watchJob(job)} className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1.5 text-xs text-[var(--primary)] hover:bg-[var(--muted)]">
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
                    {job.status !== "running" ? (
                      <button type="button" aria-label={t("student.media.remove")} title={t("student.media.remove")}
                        onClick={() => removeJob(job.id)}
                        className="rounded-md p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]">
                        <Trash2 size={14} aria-hidden />
                      </button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </aside>
  );
}
