import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

type Handler = (body: any) => unknown;
function mockApi(routes: Record<string, Handler>) {
  const calls: { url: string; method: string; body: any }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace("/api/v1", "");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url: path, method, body });
    const h = routes[`${method} ${path}`];
    if (!h) return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `no mock for ${method} ${path}` } }), { status: 404 });
    const out = h(body) as any;
    if (out?.__status) return new Response(JSON.stringify(out.body), { status: out.__status });
    return new Response(JSON.stringify(out), { status: 200 });
  }));
  return calls;
}

const delegation = { delegation_id: "dlg_1", version: 1, status: "PENDING_APPROVAL", agent_id: "agent_demo", total_budget_krw: 300000,
  per_item_max_krw: 200000, spent_krw: 0, remaining_krw: 300000, allowed_categories: ["Electronics"], allowed_merchants: ["m_techmart"],
  require_free_returns: true, auto_purchase_allowed: true, valid_for_minutes: 60, expires_at: null };

const empty = { "GET /health": () => ({ status: "ok", demo_reset_enabled: false }),
  "GET /dashboard/summary": () => ({ total_actions: 0, approved_actions: 0, blocked_actions: 0, pending_approval: 0, open_disputes: 0, recent_receipts: [] }) };

test("shows demo/mock banner and dashboard counters", async () => {
  mockApi(empty);
  render(<App />);
  expect(screen.getByRole("note")).toHaveTextContent(/DEMO \/ MOCK DATA ONLY/);
  expect(await screen.findByText("Open disputes")).toBeInTheDocument();
});

test("delegation workflow: create then approve calls the API explicitly", async () => {
  let status = "PENDING_APPROVAL";
  const calls = mockApi({ ...empty,
    "GET /delegations": () => (calls.some((c) => c.method === "POST") ? [{ ...delegation, status }] : []),
    "POST /delegations": () => delegation,
    "POST /delegations/dlg_1/approve": () => { status = "ACTIVE"; return { ...delegation, status }; } });
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole("button", { name: "Delegation" }));
  await user.click(screen.getByRole("button", { name: /Create delegation/ }));
  const approve = await screen.findByRole("button", { name: /Approve \(demo surface\)/ });
  expect(calls.find((c) => c.method === "POST" && c.url === "/delegations")!.body.allowed_categories).toEqual(["Electronics"]);
  expect(calls.some((c) => c.url.endsWith("/approve"))).toBe(false); // creation alone does not approve
  await user.click(approve);
  await waitFor(() => expect(calls.some((c) => c.url === "/delegations/dlg_1/approve")).toBe(true));
});

test("simulator shows policy violations and surfaces API errors", async () => {
  const denied = { transaction_id: "tx_1", decision: "DENY", status: "DENIED", product_id: "p_monitor", amount_krw: 380000, charged_krw: null,
    policy_reason: { violations: [{ code: "BUDGET_EXCEEDED", message: "Amount exceeds remaining budget" }] }, discrepancies: [] };
  mockApi({ ...empty,
    "GET /delegations": () => [{ ...delegation, status: "ACTIVE" }],
    "GET /simulator/scenarios": () => [{ name: "over_budget", title: "Over-budget attempt", description: "d" }],
    "GET /mock-merchant/catalog": () => ({ products: [] }),
    "POST /simulator/scenarios/over_budget/run?delegation_id=dlg_1": () => ({ scenario: "over_budget", steps: [{ step: "agent_submit", result: denied }], final: denied }) });
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole("button", { name: "Delegation" }));
  await user.click(await screen.findByRole("button", { name: "Select for simulator" }));
  await user.click(screen.getByRole("button", { name: "Agent Simulator" }));
  await user.click(await screen.findByRole("button", { name: "Run" }));
  expect(await screen.findByText(/BUDGET_EXCEEDED/)).toBeInTheDocument();
});

test("dispute analysis never shows a responsibility verdict and disables cancel when impossible", async () => {
  const analysis = { dispute_id: "dsp_1", transaction_id: "tx_1", dispute_status: "OPEN", transaction_status: "UNKNOWN", failed_stage: "MERCHANT_EXECUTION",
    responsibility: { determination: "NOT_DETERMINED", note: "AgentTrust records and compares evidence only." }, violated_conditions: [], discrepancies: [],
    evidence_by_party: { user: [], agent: [], gateway: [], merchant: [] }, unknown_facts: ["The merchant outcome is unknown"],
    cancellation: { possible: false, reason: "No merchant response" } };
  mockApi({ ...empty,
    "GET /transactions": () => [{ transaction_id: "tx_1", product_id: "p_timeout", status: "UNKNOWN", charged_krw: null }],
    "GET /disputes": () => [],
    "POST /disputes": () => ({ dispute_id: "dsp_1", transaction_id: "tx_1", status: "OPEN" }),
    "GET /disputes/dsp_1/analysis": () => analysis });
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole("button", { name: "Dispute & Recovery" }));
  await user.selectOptions(await screen.findByLabelText("Transaction"), "tx_1");
  await user.click(screen.getByRole("button", { name: "Open dispute" }));
  expect(await screen.findByText(/Responsibility: NOT_DETERMINED/)).toBeInTheDocument();
  expect(screen.getByText("The merchant outcome is unknown")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Request cancellation/ })).toBeDisabled();
});
