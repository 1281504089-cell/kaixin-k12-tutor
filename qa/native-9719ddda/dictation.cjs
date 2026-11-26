const assert = require("node:assert/strict");
const { chromium } = require('playwright-core');
const path = require("node:path");
const fs = require("node:fs/promises");

(async () => {
  const browser = await chromium.connectOverCDP("http://127.0.0.1:"+process.env.QA_CDP);
  try {
    const page = browser.contexts()[0].pages().find(tab => tab.url().startsWith("http://127.0.0.1:"));
    assert(page);
    await page.bringToFront();
    const wave = await fs.readFile(path.join(__dirname, "测试口令.wav"));
    await page.addInitScript(base64 => {
      const fetch = window.fetch.bind(window);
      window.fetch = async (resource, init) => {
        if (String(resource).includes("/api/voice/stt?") && init?.body instanceof FormData) {
          const file = init.body.get("file");
          const view = new DataView(await file.arrayBuffer());
          window.__qaVoice = {name:file.name, type:file.type,
            channels:view.getUint16(22,true), sampleRate:view.getUint32(24,true)};
        }
        return fetch(resource, init);
      };
      navigator.mediaDevices.getUserMedia = async () => {
        window.__qaMicRequested = true;
        const audio = new AudioContext();
        const bytes = Uint8Array.from(atob(base64), char => char.charCodeAt(0)).buffer;
        const source = audio.createBufferSource();
        source.buffer = await audio.decodeAudioData(bytes);
        const capture = audio.createMediaStreamDestination();
        source.connect(capture);
        await audio.resume();
        source.start(audio.currentTime + .2);
        return capture.stream;
      };
    }, wave.toString("base64"));
    await page.goto(new URL("/chat?dt_workspace=", page.url()).href, { waitUntil: "domcontentloaded" });
    const input = page.locator("textarea:visible").last();
    await input.waitFor({timeout: 12000});
    await page.waitForLoadState("load");
    await page.getByRole("button", {name:"选老师",exact:true}).last().waitFor({timeout:30000});
    await input.fill("");
    const origin = page.getByRole("button", {name:"录制语音",exact:true}).last();
    await origin.waitFor({timeout:12000});
    await origin.click();
    const stop = page.getByRole("button", {name:/结束录音|停止录音/}).last();
    try {
      await stop.waitFor({timeout:20000});
    } catch (error) {
      const state = await page.evaluate(() => ({micRequested:!!window.__qaMicRequested, alerts:[...document.querySelectorAll('[role="alert"],[role="status"]')].map(el=>el.innerText), buttons:[...document.querySelectorAll('button[aria-label*=录]')].map(el=>el.getAttribute("aria-label"))}));
      throw Error("Recording did not start: "+JSON.stringify(state), {cause:error});
    }
    await page.waitForTimeout(3500);
    const response = page.waitForResponse(res => res.url().includes("/api/voice/stt?local=true") && res.request().method()==="POST", {timeout:30000});
    const started = performance.now();
    await stop.click();
    const upload = await response;
    assert(upload.ok(), await upload.text());
    const format = await page.evaluate(() => window.__qaVoice);
    assert.deepEqual(format, { name: "recording.wav", type: "audio/wav", channels: 1, sampleRate: 16000 });
    await page.waitForFunction(() => [...document.querySelectorAll("textarea")].some(el => el.value.includes("旋转")), {timeout:12000});
    const text = await input.inputValue();
    assert(/^请给我(?:三道|3道)旋转练习题[。.]?$/.test(text.trim()), text);
    const receipt = { desktopRecordingToInputMs: Math.round(performance.now() - started), format, offlineTranscript: text };
    await fs.writeFile(path.join(__dirname, "录音与逐题配图.桌面语音回执.json"), JSON.stringify(receipt, null, 2) + "\n");
    console.log(JSON.stringify(receipt));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
