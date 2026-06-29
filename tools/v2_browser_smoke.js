"use strict";

const fs = require("fs");
const http = require("http");
const {spawn} = require("child_process");
const WebSocket = require("ws");

const baseUrl = process.env.V2_BROWSER_BASE_URL || "http://127.0.0.1:8765";
const chromePort = Number(process.env.V2_CHROME_PORT || 9223);
const profile = `/tmp/flairlab-v2-chrome-${process.pid}`;
const browser = spawn("google-chrome", [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  "--disable-dev-shm-usage",
  `--remote-debugging-port=${chromePort}`,
  `--user-data-dir=${profile}`,
  "about:blank",
], {stdio: ["ignore", "ignore", "pipe"]});

const browserErrors = [];
browser.stderr.on("data", chunk => {
  const text = chunk.toString();
  if (/ERROR|FATAL/i.test(text) && !/dbus|ssl_client_socket/i.test(text)) {
    browserErrors.push(text.trim());
  }
});

function requestJson(path, method = "GET") {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {host: "127.0.0.1", port: chromePort, path, method},
      response => {
        let body = "";
        response.on("data", chunk => { body += chunk; });
        response.on("end", () => {
          try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
        });
      }
    );
    request.on("error", reject);
    request.end();
  });
}

async function retry(fn, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  let error;
  while (Date.now() < deadline) {
    try { return await fn(); } catch (caught) { error = caught; }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw error || new Error("Timed out");
}

async function main() {
  const targets = await retry(() => requestJson("/json/list"));
  const page = targets.find(item => item.type === "page");
  if (!page) throw new Error("Chrome page target was not created.");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.once("open", resolve);
    socket.once("error", reject);
  });

  let sequence = 0;
  const pending = new Map();
  const consoleErrors = [];
  const failedRequests = [];
  socket.on("message", raw => {
    const message = JSON.parse(raw.toString());
    if (message.id && pending.has(message.id)) {
      const {resolve, reject} = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
      return;
    }
    if (message.method === "Runtime.exceptionThrown") {
      consoleErrors.push(message.params.exceptionDetails.text);
    }
    if (
      message.method === "Runtime.consoleAPICalled"
      && message.params.type === "error"
    ) {
      consoleErrors.push(
        message.params.args.map(item => item.value || item.description || "").join(" ")
      );
    }
    if (message.method === "Network.loadingFailed") {
      failedRequests.push(message.params.errorText);
    }
  });

  function command(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, {resolve, reject});
      socket.send(JSON.stringify({id, method, params}));
    });
  }

  async function evaluate(expression, awaitPromise = true) {
    const result = await command("Runtime.evaluate", {
      expression,
      awaitPromise,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(JSON.stringify(result.exceptionDetails, null, 2));
    }
    return result.result.value;
  }

  async function waitFor(expression, timeoutMs = 15000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await evaluate(`Boolean(${expression})`)) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error(`Timed out waiting for: ${expression}`);
  }

  await command("Runtime.enable");
  await command("Page.enable");
  await command("Network.enable");
  await command("Page.navigate", {url: baseUrl});
  await waitFor(`location.href.startsWith(${JSON.stringify(baseUrl)}) && document.readyState === 'complete'`);
  await evaluate(`
    sessionStorage.clear();
    sessionStorage.setItem("flairlab_api_key", "browser-smoke-key");
  `);
  await command("Page.reload", {ignoreCache: true});
  await waitFor(
    "document.readyState === 'complete' && document.getElementById('sessionSummary').textContent.includes('Session:')",
    20000
  );
  await evaluate(`
    document.getElementById("transcript").value =
      "Am 24.06.2026 fand ein Firmen-Sommerfest für 120 Gäste in der Musterlocation Berlin statt. Leistung: Cocktailcatering.";
    document.getElementById("transcript").dispatchEvent(new Event("input", {bubbles:true}));
  `);
  await evaluate("run(saveTranscript)");
  await waitFor("document.getElementById('statusRailContent').textContent.includes('Transkript in V2 gespeichert')");
  await evaluate("run(generateDraft)");
  await waitFor("document.getElementById('v2FactConfirmation').style.display === 'block'", 20000);
  await evaluate(`
    const facts = JSON.parse(document.getElementById("v2ConfirmedFacts").value || "{}");
    facts.venue = "Musterlocation Berlin";
    document.getElementById("v2ConfirmedFacts").value = JSON.stringify(facts, null, 2);
  `);
  await evaluate("run(confirmV2Facts)");
  await waitFor("document.getElementById('statusRailContent').textContent.includes('Fakten bestätigt')", 20000);
  await evaluate("run(generateDraft)");
  await waitFor("document.getElementById('draftTable').querySelectorAll('textarea').length > 5", 20000);
  await evaluate(`
    (() => {
      const first = document.getElementById("draftTable").querySelector("textarea");
      first.value = first.value + " geprüft";
      first.dispatchEvent(new Event("input", {bubbles:true}));
    })()
  `);
  await evaluate("run(saveDraft)");
  await waitFor("document.getElementById('statusRailContent').textContent.includes('Bearbeitete Felder')", 20000);

  const result = await evaluate(`({
    session: document.getElementById("sessionSummary").textContent,
    status: document.getElementById("statusRailContent").textContent,
    draftFields: document.getElementById("draftTable").querySelectorAll("textarea").length,
    acfSection: Array.from(document.getElementById("draftTable").querySelectorAll("summary"))
      .map(node => node.textContent)
      .find(text => text.startsWith("ACF Felder")) || "",
    factPanelHidden: document.getElementById("v2FactConfirmation").style.display === "none",
    publishDisabled: document.getElementById("createPostButton").disabled
  })`);
  if (consoleErrors.length || failedRequests.length || browserErrors.length) {
    throw new Error(JSON.stringify({consoleErrors, failedRequests, browserErrors}, null, 2));
  }
  if (result.draftFields < 5 || !result.factPanelHidden || result.acfSection.includes("(0)")) {
    throw new Error(`Unexpected browser result: ${JSON.stringify(result)}`);
  }
  process.stdout.write(JSON.stringify({passed: true, ...result}, null, 2) + "\n");
  socket.close();
}

main()
  .catch(error => {
    console.error(error.stack || error);
    process.exitCode = 1;
  })
  .finally(() => {
    browser.kill("SIGTERM");
    setTimeout(() => {
      try {
        fs.rmSync(profile, {recursive: true, force: true});
      } catch {
        // Chrome can still be flushing profile data for a moment after SIGTERM.
      }
    }, 250);
  });
