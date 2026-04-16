// Playwright network-layer stubs for the alert-feed E2E suite.
//
// Stubs intercept both REST (via `page.route`) and WebSocket (via
// `page.routeWebSocket`). No Python backend runs in the frontend-e2e job.
// See frontend/e2e/README.md for the stubbing contract.

import type { Page, WebSocketRoute } from "@playwright/test";
import {
  detailFor,
  listEnvelope,
  warmUpAlerts,
  type FixtureAlert,
} from "./alerts";

/**
 * Stub `GET /api/v1/alerts` (list) and `GET /api/v1/alerts/{id}` (detail).
 * Feedback POSTs are routed separately via `stubFeedback` so per-test
 * success/500 behaviour can be scripted independently.
 */
export async function stubRestAlerts(
  page: Page,
  alerts: FixtureAlert[] = warmUpAlerts,
): Promise<void> {
  await page.route("**/api/v1/alerts*", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (url.pathname.endsWith("/feedback")) {
      // Handled by stubFeedback if registered; otherwise pass through.
      await route.fallback();
      return;
    }

    if (method === "GET" && url.pathname.endsWith("/api/v1/alerts")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(listEnvelope(alerts)),
      });
      return;
    }

    const detailMatch = url.pathname.match(/\/api\/v1\/alerts\/([^/]+)$/);
    if (method === "GET" && detailMatch) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(detailFor(detailMatch[1])),
      });
      return;
    }

    await route.fallback();
  });
}

/**
 * Stub `POST /api/v1/alerts/{id}/feedback`. Register before `stubRestAlerts`
 * or alongside it; the route matcher falls back to the list/detail handler
 * when the path does not end in `/feedback`.
 */
export async function stubFeedback(
  page: Page,
  response: { status: number; body?: unknown } = { status: 204 },
): Promise<void> {
  await page.route("**/api/v1/alerts/*/feedback", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    const body =
      response.body === undefined ? "" : JSON.stringify(response.body);
    await route.fulfill({
      status: response.status,
      contentType: response.body === undefined ? "text/plain" : "application/json",
      body,
    });
  });
}

/**
 * Handle returned by `stubWebSocket`. The `sent` array buffers every frame
 * the browser sends toward the stubbed server; specs can assert on it after
 * fast-forwarding the debounce clock. `send` pushes frames back to the
 * browser. `close` terminates the current connection so the reconnect
 * backoff fires; `reopen` resolves the next time the page opens a new WS.
 */
export type WsHandle = {
  readonly sent: string[];
  send: (msg: unknown) => void;
  close: () => void;
  reopen: () => Promise<void>;
};

export async function stubWebSocket(page: Page): Promise<WsHandle> {
  const sent: string[] = [];
  let route: WebSocketRoute | null = null;
  const openers: Array<() => void> = [];

  await page.routeWebSocket("**/api/v1/ws", (ws) => {
    route = ws;
    ws.onMessage((data) => {
      sent.push(typeof data === "string" ? data : data.toString());
    });
    ws.onClose(() => {
      route = null;
    });
    const next = openers.shift();
    if (next) next();
  });

  return {
    sent,
    send: (msg: unknown) => {
      if (!route) throw new Error("ws not connected");
      route.send(JSON.stringify(msg));
    },
    close: () => {
      if (route) route.close();
    },
    reopen: () =>
      new Promise<void>((resolve) => {
        if (route) {
          resolve();
          return;
        }
        openers.push(resolve);
      }),
  };
}
