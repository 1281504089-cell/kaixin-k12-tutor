import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatStateAdapterProvider, useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { trackMediaJobs, type MediaJob } from "@/features/chat/media/media-jobs";
import MediaGenerationTray from "@/features/chat/media/MediaGenerationTray";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { initI18n } from "@/i18n/init";
import { updateRecoveryPrincipal } from "@/lib/recovery-principal";

initI18n("en");
const navigation = vi.hoisted(() => ({ push: vi.fn(), session: vi.fn() }));
vi.mock("next/navigation", async (load) => ({
  ...await load<typeof import("next/navigation")>(),
  useRouter: () => ({ push: navigation.push }),
}));
vi.mock("@/lib/session-api", async (load) => ({
  ...await load<typeof import("@/lib/session-api")>(),
  getSessionOrganization: navigation.session,
}));
beforeEach(() => {
  localStorage.clear();
  updateRecoveryPrincipal({ enabled: false, authenticated: false });
  navigation.push.mockClear();
  navigation.session.mockReset().mockImplementation(async (sessionId: string) => ({
    session_id: sessionId,
    content_workspace_id: "",
    preferences: {},
  }));
});
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
  it("hides the handoff hint while generation is still running", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
      await act(async () => { fireEvent.click(screen.getByText("Generate lesson")); });
      const hint = /Keep studying while it generates/;
      expect(screen.getByText(hint)).toBeInTheDocument();
      act(() => { vi.advanceTimersByTime(2400); });
      expect(screen.queryByText(hint)).not.toBeInTheDocument();
      expect(screen.getByText("1 generating")).toBeInTheDocument();

      await act(async () => transport.emit?.(event("video_lesson", "session")));
      expect(screen.queryByText(hint)).not.toBeInTheDocument();
      fireEvent.click(screen.getByText("Switch to another chat"));
      await act(async () => { fireEvent.click(screen.getByText("Generate animation")); });
      expect(screen.getByText(hint)).toBeInTheDocument();
      expect(screen.getByText("2 generating")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

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
    expect(screen.getByText("Fractions")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    expect(await screen.findByTitle("Fractions")).toBeInTheDocument();
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/chat/session-1?dt_workspace="));
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
    expect(screen.getByRole("heading", { name: "Generated lessons" })).toBeInTheDocument();
    expect(screen.getByText(/New result ready/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    expect(await screen.findByRole("heading", { name: "Math Animator" })).toBeInTheDocument();
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

  it("restores viewed results, opens the reading conversation, and remembers a removal", async () => {
    navigation.session.mockResolvedValue({
      session_id: "session-1",
      content_workspace_id: "",
      preferences: { workspace_mode: "immersive_reading", reading_workspace_id: "my-reading" },
    });
    const first = render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    fireEvent.click(screen.getByText("Generate lesson"));
    await screen.findByText("1 generating");
    await act(async () => {
      transport.emit?.(event("video_lesson", "session"));
      transport.emit?.(lesson);
      transport.emit?.(event("video_lesson", "done", { status: "completed", user_message_id: 1, assistant_message_id: 2 }));
    });
    await screen.findByTitle("Fractions");
    fireEvent.click(screen.getByRole("button", { name: "Collapse player" }));
    first.unmount();

    const reopened = render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    const tray = await screen.findByRole("button", { name: "Generated lessons" });
    expect(tray).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(tray);
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    expect(await screen.findByTitle("Fractions")).toBeInTheDocument();
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith(expect.stringContaining("/my-reading/sessions/session-1")));
    fireEvent.click(tray);
    fireEvent.click(screen.getByRole("button", { name: "Remove from list" }));
    expect(screen.queryByText("Fractions")).not.toBeInTheDocument();
    reopened.unmount();

    render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
    expect(screen.queryByRole("button", { name: "Generated lessons" })).not.toBeInTheDocument();
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
