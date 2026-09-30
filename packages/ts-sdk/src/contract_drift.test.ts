// SPDX-License-Identifier: Apache-2.0
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DecisionEngineClient } from "./client.js";
import { clearHostedDeviceBindingTokenCacheForTests } from "./client_device_binding.js";

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const FIXTURES_DIR = path.join(REPO_ROOT, "tests", "fixtures");

function loadFixture(name: string): unknown {
  const fixturePath = path.join(FIXTURES_DIR, name, `${name}.fixture.json`);
  return JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
}

describe("contract-drift fixture lane", () => {
  beforeEach(() => {
    process.env.ALGENTA_DEVICE_ID = "sdk-contract-drift-device-id";
    process.env.ALGENTA_RUNTIME_DIR = os.tmpdir();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    clearHostedDeviceBindingTokenCacheForTests();
    delete process.env.ALGENTA_DEVICE_ID;
    delete process.env.ALGENTA_RUNTIME_DIR;
  });

  it("parses the recorded contract payload through the client", async () => {
    const fixture = loadFixture("contract");
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(fixture), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DecisionEngineClient({
      apiKey: "de_test_contractdrift",
      baseUrl: "https://api.algenta.test",
      maxRetries: 0,
      timeout: 1_000,
    });

    const parsed = await client.getContract();
    expect(parsed).toEqual(fixture);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.algenta.test/v1/meta/contract");
  });

  it("parses the recorded execution receipt payload through the client", async () => {
    const fixture = loadFixture("receipt");
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(fixture), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new DecisionEngineClient({
      apiKey: "de_test_contractdrift",
      baseUrl: "https://api.algenta.test",
      maxRetries: 0,
      timeout: 1_000,
    });

    const parsed = await client.executeDecision("dec_123", {
      webhook_url: "https://hooks.example.test/algenta",
    });
    expect(parsed).toEqual(fixture);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.algenta.test/v1/decisions/dec_123/execute",
    );
  });
});
