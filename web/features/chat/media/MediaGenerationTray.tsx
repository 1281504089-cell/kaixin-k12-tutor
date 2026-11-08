"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Check, Clapperboard, List, LoaderCircle, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { activeWorkspaceId, scopedUrl } from "@/lib/workspace-scope";
import type { MediaJob } from "./media-jobs";

const MathPlayer = dynamic(() => import("@/components/math-animator/MathAnimatorViewer"), { ssr: false });
const LessonPlayer = dynamic(() => import("@/components/video-lesson/VideoLessonViewer"), { ssr: false });

export default function MediaGenerationTray() {
  const { mediaJobs, state, newSession } = useChatStateAdapter();
  if (!mediaJobs.length) return null;
  const foregroundGeneration = mediaJobs.some(job => job.status === "running" && job.sessionKey === state.sessionKey);
  return <MediaTray jobs={mediaJobs} foregroundGeneration={foregroundGeneration}
    startChat={() => newSession({ workspaceId: activeWorkspaceId() || null })} />;
}

function MediaTray({ jobs, foregroundGeneration, startChat }: {
  jobs: MediaJob[];
  foregroundGeneration: boolean;
  startChat: () => void;
}) {
  const { t } = useTranslation();
  const [view, setView] = useState<string | null>(null);
  const [dismissedId, setDismissedId] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const latestReady = jobs.find(job => job.status === "ready");
  const autoOpen = latestReady && latestReady.id !== dismissedId ? latestReady : undefined;
  const openJob = view && view !== "list" ? jobs.find(job => job.id === view) : autoOpen;
  const expanded = Boolean(openJob || view === "list");
  const runningCount = jobs.filter(job => job.status === "running").length;

  const changeView = (next: typeof view) => {
    setDismissedId(latestReady?.id ?? null);
    setView(next);
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
      trigger.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [expanded, latestReady?.id]);

  const label = (job: MediaJob) => job.kind === "math_animator" ? t("Math Animator") : t("Video Lesson");

  return (
    <aside aria-label={t("student.media.jobs")} className="pointer-events-none fixed right-3 top-14 z-30 flex w-[min(28rem,calc(100vw-1.5rem))] flex-col items-end gap-2 sm:right-5">
      <div className="pointer-events-auto flex items-center gap-2">
        {foregroundGeneration ? (
          <Link href={scopedUrl("/chat")} onNavigate={startChat} className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs font-medium shadow-sm hover:bg-[var(--muted)]">
            {t("student.media.newChat")}
          </Link>
        ) : null}
        <button ref={trigger} type="button" aria-label={t("student.media.jobs")} aria-expanded={expanded} aria-controls={expanded ? "student-media-panel" : undefined}
          onClick={() => changeView(expanded ? null : latestReady?.id ?? "list")}
          className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs font-medium shadow-sm hover:bg-[var(--muted)]">
          {runningCount ? <LoaderCircle size={15} aria-hidden className="motion-safe:animate-spin" /> : <Clapperboard size={15} aria-hidden />}
          <span role="status">{runningCount ? t("student.media.running", { count: runningCount }) : t("student.media.jobs")}</span>
        </button>
      </div>

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
                  <span className="min-w-0 truncate">{job.output?.kind === "video_lesson" && job.output.result.title || label(job)}</span>
                  {job.status === "ready" ? (
                    <button type="button" onClick={() => changeView(job.id)} className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1.5 text-xs text-[var(--primary)] hover:bg-[var(--muted)]">
                      <Check size={14} aria-hidden />{t("student.media.watch")}
                    </button>
                  ) : (
                    <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
                      {t(job.status === "running" ? "student.media.inProgress" : "student.media.unavailable")}
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
