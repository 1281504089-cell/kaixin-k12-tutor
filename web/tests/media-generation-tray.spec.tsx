import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatStateAdapterProvider, useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { trackMediaJobs, type MediaJob } from "@/features/chat/media/media-jobs";
import MediaGenerationTray from "@/features/chat/media/MediaGenerationTray";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { initI18n } from "@/i18n/init";

initI18n("en");
const transport = vi.hoisted(() => ({
  emit: undefined as undefined | ((e: StreamEvent) => void),
  stop: vi.fn<(command: { type: string; turn_id: string }) => Promise<boolean>>(),
}));
vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    connected = true;
    constructor(emit: typeof transport.emit) { transport.emit = emit; }
    connect() {}
    disconnect() {}
    send() {}
    sendAwaitingAck(command: { type: string; turn_id: string }) { return transport.stop(command); }
    setResumeState() {}
  },
}));

const event = (source: string, type: StreamEvent["type"], metadata = {}, turnId = "turn-1", sessionId = "session-1"): StreamEvent => ({
  type, metadata, source, content: "", stage: "render_output", timestamp: 1,
  session_id: sessionId, turn_id: turnId,
});

function Harness() {
  const { sendMessage, newSession, state } = useChatStateAdapter();
  return <>
    <button onClick={() => sendMessage("Test lesson", undefined, undefined, undefined, undefined,
      { capability: "video_lesson" })}>Generate lesson</button>
    <button onClick={() => sendMessage("Test animation", undefined, undefined, undefined, undefined,
      { capability: "math_animator" })}>Generate animation</button>
    <button onClick={() => newSession()}>Switch to another chat</button>
    <output data-testid="session">{state.sessionId}</output>
    <input aria-label="Keep studying" />
    <MediaGenerationTray />
  </>;
}

const lesson = event("video_lesson", "result", {
  title: "Fractions",
  artifacts: [{ type: "html", url: "/files/demo.html", filename: "lesson.html" }],
});

describe("background generation", () => {
  it("keeps a lesson running after a session switch and opens a collapsible player without stealing focus", async () => {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Generate lesson"));
    await screen.findByText("1 generating");
    await act(async () => transport.emit?.(event("video_lesson", "session", { session_id: "session-1" })));
    expect(screen.getByTestId("session")).toHaveTextContent("session-1");
    fireEvent.click(screen.getByText("Switch to another chat"));
    expect(screen.getByTestId("session")).toBeEmptyDOMElement();
    const input = screen.getByRole("textbox", { name: "Keep studying" });
    input.focus();
    await act(async () => transport.emit?.(lesson));
    expect(screen.queryByTitle("Fractions")).not.toBeInTheDocument();
    await act(async () => transport.emit?.(event("video_lesson", "done", { status: "completed", user_message_id: 1, assistant_message_id: 2 })));
    expect(await screen.findByTitle("Fractions")).toHaveAttribute("sandbox", "allow-scripts");
    expect(screen.getByText(/New result ready/)).toBeInTheDocument();
    expect(input).toHaveFocus();
    expect(screen.getByTestId("session")).toBeEmptyDOMElement();
    fireEvent.click(screen.getByRole("button", { name: "Collapse player" }));
    expect(screen.queryByTitle("Fractions")).not.toBeInTheDocument();
    expect(screen.queryByText(/New result ready/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generated lessons" }));
    expect(await screen.findByTitle("Fractions")).toBeInTheDocument();
  });

  it("opens a real animation result and ignores old completion events", async () => {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Generate animation"));
    await screen.findByText("1 generating");
    await act(async () => {
      transport.emit?.(event("math_animator", "session", { session_id: "session-1" }));
      transport.emit?.(event("math_animator", "done", { status: "completed" }, "old-turn"));
    });
    expect(screen.getByText("1 generating")).toBeInTheDocument();
    await act(async () => {
      transport.emit?.(event("math_animator", "result", {
        output_mode: "video",
        artifacts: [{ type: "video", url: "/files/demo.mp4", filename: "demo.mp4" }],
      }));
      transport.emit?.(event("math_animator", "done", { status: "completed", user_message_id: 1, assistant_message_id: 2 }));
    });
    const heading = await screen.findByRole("heading", { name: "Math Animator" });
    await waitFor(() => expect(heading.closest("section")?.querySelector("video")).toHaveAttribute("src", expect.stringContaining("/files/demo.mp4")));
  });

  it("orders results by completion even when an earlier request finishes last", () => {
    let jobs: MediaJob[] = [];
    for (const key of ["first", "second"]) {
      jobs = trackMediaJobs(jobs, { type: "STREAM_START", key, startedAt: 1, capability: "video_lesson" });
    }
    for (const key of ["second", "first"]) {
      jobs = trackMediaJobs(jobs, { type: "STREAM_EVENT", key, event: lesson });
      jobs = trackMediaJobs(jobs, { type: "STREAM_END", key, status: "completed" });
    }
    expect(jobs.map(job => job.sessionKey)).toEqual(["first", "second"]);
    expect(trackMediaJobs(jobs, { type: "STREAM_START", key: "third", startedAt: 2, capability: "video_lesson" })[0].id).toBe("third:2");
  });

  it("cancels only the named background turn and leaves another conversation running", async () => {
    transport.stop.mockResolvedValue(true);
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Generate lesson"));
    await screen.findByText("1 generating");
    const lessonEvents = transport.emit;
    await act(async () => lessonEvents?.(event("video_lesson", "session", {}, "lesson-turn")));
    fireEvent.click(screen.getByText("Switch to another chat"));
    fireEvent.click(screen.getByText("Generate animation"));
    await screen.findByText("2 generating");
    const animationEvents = transport.emit;
    await act(async () => animationEvents?.(event("math_animator", "session", {}, "animation-turn", "session-2")));
    expect(transport.stop).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Generated lessons" }));
    const stopLesson = screen.getByRole("button", { name: "Stop generation: Test lesson" });
    await act(async () => fireEvent.click(stopLesson));
    expect(transport.stop).toHaveBeenCalledExactlyOnceWith({ type: "cancel_turn", turn_id: "lesson-turn" });
    expect(stopLesson).toBeDisabled();
    expect(stopLesson).toHaveTextContent("Stopping…");
    expect(screen.queryByText("Stopped")).not.toBeInTheDocument();

    await act(async () => lessonEvents?.(event("video_lesson", "done", {
      status: "cancelled", user_message_id: 1, assistant_message_id: 2,
    }, "lesson-turn")));
    expect(screen.getByText("Stopped")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop generation: Test animation" })).toBeEnabled();
    expect(screen.getByText("1 generating")).toBeInTheDocument();
    expect(screen.getByTestId("session")).toHaveTextContent("session-2");
    expect(screen.queryByText(/New result ready/)).not.toBeInTheDocument();

    await act(async () => {
      animationEvents?.(event("math_animator", "result", {
        output_mode: "video",
        artifacts: [{ type: "video", url: "/files/demo.mp4", filename: "demo.mp4" }],
      }, "animation-turn", "session-2"));
      animationEvents?.(event("math_animator", "done", {
        status: "completed", user_message_id: 3, assistant_message_id: 4,
      }, "animation-turn", "session-2"));
    });
    expect(await screen.findByRole("heading", { name: "Math Animator" })).toBeInTheDocument();
    expect(screen.getByText(/New result ready/)).toBeInTheDocument();
  });

  it("allows retrying a rejected stop without marking the task stopped", async () => {
    transport.stop.mockResolvedValue(false);
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Generate lesson"));
    await screen.findByText("1 generating");
    await act(async () => transport.emit?.(event("video_lesson", "session")));
    fireEvent.click(screen.getByRole("button", { name: "Generated lessons" }));
    const stop = screen.getByRole("button", { name: "Stop generation: Test lesson" });
    await act(async () => fireEvent.click(stop));
    expect(stop).toBeEnabled();
    expect(screen.queryByText("Stopped")).not.toBeInTheDocument();
  });

  it("shows failures in the tray without opening an empty player", async () => {
    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Generate lesson"));
    await screen.findByText("1 generating");
    await act(async () => {
      transport.emit?.(event("video_lesson", "session", { session_id: "session-1" }));
      transport.emit?.(event("video_lesson", "done", { status: "failed" }));
    });
    expect(screen.queryByRole("heading", { name: "Video Lesson" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Generated lessons" }));
    expect(screen.getByText("No playable result")).toBeInTheDocument();
  });
});
