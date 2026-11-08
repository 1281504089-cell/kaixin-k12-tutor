type SendOrigin = { x: number; y: number };

let pending: { kind: string; point: SendOrigin; expires: number } | undefined;

export function recordMediaSend(kind: string, point: SendOrigin | undefined) {
  pending = (kind === "math_animator" || kind === "video_lesson") && point
    ? { kind, point, expires: performance.now() + 1200 }
    : undefined;
}

export function takeMediaSendOrigin(kind: string): SendOrigin | undefined {
  const origin = pending;
  pending = undefined;
  if (origin?.kind === kind && performance.now() <= origin.expires) return origin.point;
}
