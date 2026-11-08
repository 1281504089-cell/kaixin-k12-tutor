import { activeWorkspaceId } from "@/lib/workspace-scope";
import { browserStorage } from "@/shared/storage";
import type { MediaJob } from "./media-jobs";

export function mediaHistoryScope(principal: string): string {
  return `deeptutor.media-history.${encodeURIComponent(principal)}:${encodeURIComponent(activeWorkspaceId())}:`;
}

const entryKey = (scope: string, id: string) => scope + encodeURIComponent(id);
const isMediaPath = (url: unknown): url is string => typeof url === "string" && url.startsWith("/files/");

function compactJob(job: MediaJob): MediaJob | null {
  if (job.status !== "ready" || !job.output || job.output.kind !== job.kind ||
      typeof job.id !== "string" || typeof job.sessionKey !== "string" || !job.sessionKey ||
      typeof job.completedAt !== "number" || !Number.isFinite(job.completedAt)) return null;
  const { id, sessionKey, kind, completedAt, output } = job;
  const entry = { id, sessionKey, kind, completedAt, status: "ready" as const,
    prompt: typeof job.prompt === "string" ? job.prompt.slice(0, 160) : undefined,
    restored: true, viewed: Boolean(job.viewed) };
  if (output.kind === "video_lesson") {
    const { title, page, durationSeconds, attempts } = output.result;
    if (!isMediaPath(page?.url) || typeof title !== "string") return null;
    return { ...entry, output: { kind: output.kind, result: {
      title, page, durationSeconds, attempts, response: "", code: "",
    } } };
  }
  const artifacts = output.result.artifacts.filter(file => isMediaPath(file?.url) &&
    (file.type === "video" || file.type === "image"));
  if (!artifacts.length) return null;
  return { ...entry, output: { kind: output.kind, result: {
    artifacts, output_mode: output.result.output_mode, response: "",
    code: { language: "python", content: "" }, timings: {}, render: {},
  } } };
}

export function readMediaHistory(scope: string): MediaJob[] {
  return browserStorage.listRaw("local", scope).flatMap(([key, raw]) => {
    try {
      const job = compactJob(JSON.parse(raw));
      return job && key === entryKey(scope, job.id) ? [job] : [];
    } catch {
      return [];
    }
  }).sort((a, b) => (b.completedAt ?? 0) - (a.completedAt ?? 0));
}

export function saveMediaHistoryJob(scope: string, job: MediaJob): void {
  const entry = compactJob(job);
  if (entry) browserStorage.writeRaw("local", entryKey(scope, entry.id), JSON.stringify(entry));
}

export function removeMediaHistoryJob(scope: string, id: string): void {
  browserStorage.removeRaw("local", entryKey(scope, id));
}
