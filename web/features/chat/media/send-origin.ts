export type MediaSendOrigin = { x: number; y: number };

const pending = new Map<string, { point?: MediaSendOrigin; expires: number }>();
let audio: AudioContext | undefined;
let audioReady: Promise<void> | undefined;

export function recordMediaSend(kind: string, point?: MediaSendOrigin) {
  if (kind !== "math_animator" && kind !== "video_lesson") return;
  pending.set(kind, { point, expires: performance.now() + 5000 });

  // Unlock audio in the submit gesture. Playback waits until the job is added.
  if (typeof window.AudioContext !== "function") return;
  try {
    audio ??= new AudioContext();
    audioReady = audio.state === "running" ? Promise.resolve() : audio.resume().catch(() => {});
  } catch {
    // Some clients block audio; the visual feedback is still available.
  }
}

export function takeMediaSend(kind: string) {
  const submission = pending.get(kind);
  pending.delete(kind);
  return submission && performance.now() <= submission.expires ? submission : undefined;
}

export function playMediaDeliverySound() {
  const context = audio;
  if (!context || !audioReady) return;
  const requestedAt = performance.now();
  void audioReady.then(() => {
    if (context.state !== "running" || performance.now() - requestedAt > 300) return;
    const start = context.currentTime;
    const end = start + 0.23;
    const volume = context.createGain();
    volume.gain.setValueAtTime(0, start);
    volume.gain.linearRampToValueAtTime(0.12, start + 0.045);
    volume.gain.exponentialRampToValueAtTime(0.001, end);
    volume.connect(context.destination);

    const whistle = context.createOscillator();
    whistle.frequency.setValueAtTime(860, start);
    whistle.frequency.exponentialRampToValueAtTime(1740, start + 0.06);
    whistle.frequency.exponentialRampToValueAtTime(490, end);
    whistle.connect(volume);

    const air = context.createBuffer(1, Math.ceil(0.23 * context.sampleRate), context.sampleRate);
    const samples = air.getChannelData(0);
    for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1;
    const noise = context.createBufferSource();
    noise.buffer = air;
    const filter = context.createBiquadFilter();
    filter.type = "bandpass";
    filter.frequency.setValueAtTime(2400, start);
    filter.frequency.exponentialRampToValueAtTime(700, end);
    noise.connect(filter).connect(volume);

    whistle.onended = () => volume.disconnect();
    whistle.start(start);
    whistle.stop(end);
    noise.start(start);
    noise.stop(end);
  }).catch(() => {});
}
