import type { StreamEvent } from "@/features/chat/model/protocol";
import { extractMathAnimatorResult, type MathAnimatorResult } from "@/lib/math-animator-types";
import { extractVideoLessonResult, type VideoLessonResult } from "@/lib/video-lesson-types";

type MediaKind = "math_animator" | "video_lesson";
type MediaOutput =
  | { kind: "math_animator"; result: MathAnimatorResult }
  | { kind: "video_lesson"; result: VideoLessonResult };

export interface MediaJob {
  id: string;
  sessionKey: string;
  turnId?: string | null;
  kind: MediaKind;
  prompt?: string;
  stopRequested?: boolean;
  status: "running" | "ready" | "failed" | "cancelled";
  output?: MediaOutput;
}

export type MediaJobEvent =
  | { type: "MEDIA_STOP_REQUEST"; id: string; requested: boolean }
  | { type: "STREAM_START"; key: string; startedAt: number; capability?: string | null; prompt?: string }
  | { type: "BIND_SERVER_SESSION"; key: string; sessionId: string; turnId?: string | null }
  | { type: "STREAM_EVENT"; key: string; event: StreamEvent }
  | { type: "STREAM_END"; key: string; status?: string; turnId?: string | null };

export function trackMediaJobs(jobs: MediaJob[], action: MediaJobEvent): MediaJob[] {
  if (action.type === "MEDIA_STOP_REQUEST") {
    return jobs.map(job => job.id === action.id && job.status === "running"
      ? { ...job, stopRequested: action.requested } : job);
  }
  if (action.type === "STREAM_START") {
    const kind = action.capability;
    if (kind !== "math_animator" && kind !== "video_lesson") return jobs;
    const id = `${action.key}:${action.startedAt}`;
    return [{ id, kind, sessionKey: action.key, status: "running", prompt: action.prompt }, ...jobs];
  }

  // Only act on this session's live job. Replaying old messages must never
  // reopen the floating player or finish a newer generation in the same chat.
  const index = jobs.findIndex(job => job.status === "running" && job.sessionKey === action.key);
  const job = jobs[index];
  if (!job) return jobs;
  const replace = (update: MediaJob) => jobs.map((item, i) => i === index ? update : item);

  if (action.type === "BIND_SERVER_SESSION") {
    return replace({ ...job, sessionKey: action.sessionId, turnId: action.turnId ?? job.turnId });
  }

  const turnId = action.type === "STREAM_EVENT" ? action.event.turn_id : action.turnId;
  if (job.turnId && turnId && job.turnId !== turnId) return jobs;

  if (action.type === "STREAM_EVENT") {
    if (action.event.type !== "result" || action.event.source !== job.kind) return jobs;
    const metadata = action.event.metadata;
    if (job.kind === "math_animator") {
      const result = extractMathAnimatorResult(metadata);
      return result?.artifacts.some(file => (file.type === "video" || file.type === "image") && file.url)
        ? replace({ ...job, turnId, output: { kind: job.kind, result } })
        : jobs;
    }
    const result = extractVideoLessonResult(metadata);
    return result ? replace({ ...job, turnId, output: { kind: job.kind, result } }) : jobs;
  }

  if (action.status === "running") return jobs;
  const ready = (action.status === "completed" || !action.status) && Boolean(job.output);
  const status = ready ? "ready" : action.status === "cancelled" ? "cancelled" : "failed";
  const settled: MediaJob[] = [
    { ...job, status, stopRequested: false, output: ready ? job.output : undefined },
    ...jobs.filter(item => item.id !== job.id),
  ];
  let finished = 0;
  return settled.filter(item => item.status === "running" || ++finished <= 8);
}
