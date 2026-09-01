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
  if (state === "visible" && !(await locator.isVisible())) {
    throw new Error(`expected visible selector: ${step.selector}`);
  }
  if (state === "hidden" && (await locator.isVisible())) {
    throw new Error(`expected hidden selector: ${step.selector}`);
  }
  if (!new Set(["visible", "hidden"]).has(state)) {
    throw new Error(`unsupported expect state: ${state}`);
  }
}

async function observeDom(page, observation) {
  const locator = page.locator(requireString(observation.selector, "observation.selector"));
  const expectation = requireString(observation.expectation, "observation.expectation");
  const count = await locator.count();
  if (expectation === "present") {
    return { passed: count > 0, actual: count > 0 ? "present" : "absent" };
  }
  if (expectation === "absent") {
    return { passed: count === 0, actual: count === 0 ? "absent" : "present" };
  }
  if (expectation === "visible") {
    const visible = count > 0 && (await locator.isVisible());
    return { passed: visible, actual: visible ? "visible" : "hidden" };
  }
  if (expectation === "hidden") {
    const hidden = count === 0 || !(await locator.isVisible());
    return { passed: hidden, actual: hidden ? "hidden" : "visible" };
  }
  if (expectation.startsWith("text:")) {
    const expected = expectation.slice("text:".length);
    const actual = count > 0 ? (await locator.textContent()) ?? "" : "";
    return { passed: actual === expected, actual };
  }
  throw new Error(`unsupported browser observation expectation: ${expectation}`);
}

let browser;
let context;
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
  const page = await context.newPage();
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
  if (!passed) process.exitCode = 1;
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
} finally {
  if (context) await context.close();
  if (browser) await browser.close();
}
