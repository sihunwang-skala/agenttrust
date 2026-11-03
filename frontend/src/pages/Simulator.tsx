import { useEffect, useState } from "react";
import { api, krw, post } from "../api";
import type { Shared } from "../App";
import { Badge, Btn, Card, ErrorNote } from "../ui";

export default function Simulator({ delegationId, refresh, setTxFocus, goto }: Shared) {
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [catalog, setCatalog] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/simulator/scenarios").then(setScenarios).catch((e) => setErr(e.message)); api("/mock-merchant/catalog").then(setCatalog).catch(() => {}); }, []);

  const run = async (name: string) => {
    setErr(null); setBusy(true);
    try { setResult(await post(`/simulator/scenarios/${name}/run?delegation_id=${encodeURIComponent(delegationId)}`)); refresh(); }
    catch (e: any) { setErr(e.message); setResult(null); } finally { setBusy(false); }
  };
  const decide = async (txId: string, what: "approve" | "reject") => {
    try { const r = await post(`/transactions/${txId}/${what}`, what === "reject" ? { reason: "rejected in simulator" } : undefined);
      setResult({ scenario: "manual", steps: [{ step: what, result: r }], final: r }); refresh(); } catch (e: any) { setErr(e.message); }
  };

  return (
    <div className="space-y-4">
      <Card title="Mock Agent scenarios">
        <p className="mb-3 text-sm text-slate-600">
          {delegationId ? <>Acting under delegation <code>{delegationId}</code>. The mock agent calls the same Gateway API a real agent would.</>
            : "Create and approve a delegation first (Delegation tab), then select it."}
        </p>
        <div className="grid gap-2 md:grid-cols-3">
          {scenarios.map((s) => (
            <div key={s.name} className="rounded border border-slate-200 p-3">
              <div className="font-medium">{s.title}</div>
              <p className="mb-2 text-xs text-slate-500">{s.description}</p>
              <Btn kind="primary" disabled={!delegationId || busy} onClick={() => run(s.name)}>Run</Btn>
            </div>
          ))}
        </div>
        <ErrorNote error={err} />
      </Card>
      {result && (
        <Card title={`Result: ${result.scenario}`}>
          {result.steps.map((st: any, i: number) => (
            <div key={i} className="mb-3 rounded border border-slate-200 p-3 text-sm">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs">{st.step}</span><Badge>{st.result.decision}</Badge><Badge>{st.result.status}</Badge>
                {st.result.replayed && <span className="rounded bg-slate-200 px-2 text-xs">idempotent replay: no second execution</span>}
                {st.result.cancellation_outcome && <Badge>{st.result.cancellation_outcome}</Badge>}
              </div>
              <div>{st.result.product_id} · authorized {krw(st.result.amount_krw)} · merchant charged {krw(st.result.charged_krw)}</div>
              {st.result.policy_reason?.violations?.length > 0 && (
                <ul className="mt-1 list-disc pl-5 text-red-700">{st.result.policy_reason.violations.map((v: any, j: number) => <li key={j}><b>{v.code}</b>: {v.message}</li>)}</ul>
              )}
              {st.result.discrepancies?.length > 0 && (
                <ul className="mt-1 list-disc pl-5 text-amber-700">{st.result.discrepancies.map((d: any, j: number) => <li key={j}>{d.field}: expected {String(d.expected)}, merchant reported {String(d.observed)}</li>)}</ul>
              )}
              {st.result.status === "PENDING_APPROVAL" && (
                <div className="mt-2 flex gap-2"><Btn kind="primary" onClick={() => decide(st.result.transaction_id, "approve")}>Approve this action</Btn><Btn onClick={() => decide(st.result.transaction_id, "reject")}>Reject</Btn></div>
              )}
              <button className="mt-2 text-xs text-indigo-700 underline" onClick={() => { setTxFocus(st.result.transaction_id); goto("Receipt Explorer"); }}>View receipts for {st.result.transaction_id}</button>
            </div>
          ))}
        </Card>
      )}
      {catalog && (
        <Card title="Mock merchant catalog (synthetic, simulated)">
          <table className="w-full text-xs"><thead><tr className="text-left text-slate-500"><th>Product</th><th>Merchant</th><th>Category</th><th>Price</th><th>Free returns</th><th>Delivery</th><th>Cancellable</th></tr></thead>
            <tbody>{catalog.products.map((p: any) => (
              <tr key={p.product_id} className="border-t border-slate-100"><td>{p.product_id}: {p.name}</td><td>{p.merchant_id}</td><td>{p.category}</td><td>{krw(p.unit_price_krw)}</td><td>{String(p.free_returns)}</td><td>{p.delivery_days}d</td><td>{String(p.cancellable)}</td></tr>))}</tbody></table>
        </Card>
      )}
    </div>
  );
}
