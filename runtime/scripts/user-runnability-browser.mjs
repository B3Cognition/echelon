#!/usr/bin/env node

import fs from "node:fs/promises";
import { chromium } from "@playwright/test";

const planPath = process.argv[2];
if (!planPath) {
  console.error("usage: user-runnability-browser.mjs <plan.json>");
  process.exit(2);
}

const supportedActions = new Set(["goto", "click", "fill", "press", "expect"]);

function requireString(value, field) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${field} must be a non-empty string`);
  }
  return value;
}

async function executeStep(page, baseUrl, step) {
  const action = requireString(step.action, "step.action");
  if (!supportedActions.has(action)) {
    throw new Error(`unsupported browser action: ${action}`);
  }
  if (action === "goto") {
    const path = requireString(step.path, "step.path");
    await page.goto(new URL(path, baseUrl).toString());
    return;
  }
  const locator = page.locator(requireString(step.selector ?? "body", "step.selector"));
  if (action === "click") {
    await locator.click();
    return;
  }
  if (action === "fill") {
    await locator.fill(requireString(step.value, "step.value"));
    return;
  }
  if (action === "press") {
    const key = requireString(step.key, "step.key");
    const repeat = Number.isInteger(step.repeat) ? step.repeat : 1;
    if (repeat < 1 || repeat > 1000) throw new Error("step.repeat is out of range");
    for (let index = 0; index < repeat; index += 1) await locator.press(key);
    return;
  }
  const state = requireString(step.state, "step.state");
  if (state === "visible") {
    await locator.waitFor({ state: "visible" });
    return;
  }
  if (state === "hidden") {
    await locator.waitFor({ state: "hidden" });
    return;
  }
  throw new Error(`unsupported expect state: ${state}`);
}

async function observeDom(page, observation) {
  const locator = page.locator(requireString(observation.selector, "observation.selector"));
  const expectation = requireString(observation.expectation, "observation.expectation");
  if (expectation === "present") {
    try {
      await locator.waitFor({ state: "attached" });
      return { passed: true, actual: "present" };
    } catch {
      return { passed: false, actual: "absent" };
    }
  }
  if (expectation === "absent") {
    try {
      await locator.waitFor({ state: "detached" });
      return { passed: true, actual: "absent" };
    } catch {
      return { passed: false, actual: "present" };
    }
  }
  if (expectation === "visible") {
    try {
      await locator.waitFor({ state: "visible" });
      return { passed: true, actual: "visible" };
    } catch {
      return { passed: false, actual: "hidden" };
    }
  }
  if (expectation === "hidden") {
    try {
      await locator.waitFor({ state: "hidden" });
      return { passed: true, actual: "hidden" };
    } catch {
      return { passed: false, actual: "visible" };
    }
  }
  if (expectation.startsWith("text:")) {
    const expected = expectation.slice("text:".length);
    try {
      await locator.waitFor({ state: "attached" });
    } catch {
      return { passed: false, actual: "" };
    }
    const actual = (await locator.textContent()) ?? "";
    return { passed: actual === expected, actual };
  }
  throw new Error(`unsupported browser observation expectation: ${expectation}`);
}

let browser;
let context;
let page;
const diagnostics = [];
function recordDiagnostic(value) {
  const text = String(value).replace(/\s+/g, " ").trim().slice(0, 700);
  if (text) diagnostics.push(text);
  if (diagnostics.length > 40) diagnostics.shift();
}
try {
  const plan = JSON.parse(await fs.readFile(planPath, "utf8"));
  if (plan.kind !== "browser") throw new Error("browser helper requires kind=browser");
  const baseUrl = requireString(plan.url, "plan.url");
  const selected = new Set(Array.isArray(plan.observation_ids) ? plan.observation_ids : []);
  for (const step of plan.steps ?? []) {
    if (!supportedActions.has(step.action)) {
      throw new Error(`unsupported browser action: ${step.action}`);
    }
  }

  browser = await chromium.launch({ headless: true });
  context = await browser.newContext({ serviceWorkers: "block" });
  const storage = Object.fromEntries(plan.session_storage ?? []);
  if (Object.keys(storage).length > 0) {
    await context.addInitScript((values) => {
      for (const [key, value] of Object.entries(values)) sessionStorage.setItem(key, value);
    }, storage);
  }
  page = await context.newPage();
  page.on("console", message => recordDiagnostic(`console.${message.type()}: ${message.text()}`));
  page.on("pageerror", error => recordDiagnostic(`page error: ${error.message}`));
  page.on("requestfailed", request => recordDiagnostic(
    `request failed: ${request.method()} ${request.url()} ${request.failure()?.errorText ?? ""}`,
  ));
  page.on("response", response => {
    if (response.status() >= 400) {
      recordDiagnostic(
        `HTTP ${response.status()} ${response.request().method()} ${response.url()}`,
      );
    }
  });
  for (const step of plan.steps ?? []) await executeStep(page, baseUrl, step);

  const observations = {};
  for (const observation of plan.observations ?? []) {
    if (!selected.has(observation.id) || observation.kind !== "browser_dom") continue;
    observations[observation.id] = await observeDom(page, observation);
  }
  const passed = [...selected].every(
    (observationId) => observations[observationId]?.passed === true,
  );
  process.stdout.write(`${JSON.stringify({ status: passed ? "passed" : "failed", observations })}\n`);
  if (!passed) {
    try {
      recordDiagnostic(`visible page text: ${await page.locator("body").innerText()}`);
    } catch {
      // Retain any earlier browser diagnostics.
    }
    if (diagnostics.length > 0) {
      console.error(`Browser diagnostics:\n${diagnostics.map(item => `- ${item}`).join("\n")}`);
    }
    process.exitCode = 1;
  }
} catch (error) {
  if (page) {
    try {
      recordDiagnostic(`visible page text: ${await page.locator("body").innerText()}`);
    } catch {
      // The browser or page may already have closed; retain earlier diagnostics.
    }
  }
  const message = error instanceof Error ? error.message : String(error);
  const detail = diagnostics.length > 0
    ? `\nBrowser diagnostics:\n${diagnostics.map(item => `- ${item}`).join("\n")}`
    : "";
  console.error(`${message}${detail}`);
  process.exitCode = 1;
} finally {
  if (context) await context.close();
  if (browser) await browser.close();
}
