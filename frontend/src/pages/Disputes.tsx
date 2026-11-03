import { useEffect, useState } from "react";
import { api, krw, post } from "../api";
import type { Shared } from "../App";
import { Badge, Btn, Card, ErrorNote } from "../ui";

export default function Disputes({ tick, refresh, txFocus }: Shared) {
  const [txs, setTxs] = useState<any[]>([]);
  const [disputes, setDisputes] = useState<any[]>([]);
  const [txId, setTxId] = useState(txFocus);
  const [reason, setReason] = useState("This purchase looks wrong");
  const [dispute, setDispute] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api("/transactions").then(setTxs).catch((e) => setErr(e.message)); api("/disputes").then(setDisputes).catch(() => {}); }, [tick]);
  useEffect(() => { if (dispute) api(`/disputes/${dispute.dispute_id}/analysis`).then(setAnalysis).catch((e) => setErr(e.message)); }, [dispute, tick]);

  const run = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); refresh(); } catch (e: any) { setErr(e.message); } };
  const open = () => run(async () => setDispute(await post("/disputes", { transaction_id: txId, reason })));
  const cancel = () => run(async () => { const r = await post(`/disputes/${dispute.dispute_id}/cancellations`, { reason }); setOutcome(r.cancellation_outcome ?? "n/a"); });
  const close = () => run(async () => setDispute(await post(`/disputes/${dispute.dispute_id}/close`, { resolution_note: "closed from dashboard" })));

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="space-y-3">
        <Card title="1. Select a transaction">
          <select aria-label="Transaction" className="w-full rounded border border-slate-300 p-1 text-sm" value={txId} onChange={(e) => setTxId(e.target.value)}>
            <option value="">Choose…</option>
            {txs.map((t) => <option key={t.transaction_id} value={t.transaction_id}>{t.transaction_id} · {t.product_id} · {t.status}</option>)}
          </select>
          <textarea aria-label="Dispute reason" className="mt-2 w-full rounded border border-slate-300 p-1 text-sm" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          <Btn kind="primary" className="mt-2" disabled={!txId || !reason} onClick={open}>Open dispute</Btn>
          <ErrorNote error={err} />
        </Card>
        <Card title="Disputes">
          {disputes.length === 0 && <p className="text-sm text-slate-500">None yet.</p>}
          {disputes.map((d) => (
            <button key={d.dispute_id} onClick={() => { setDispute(d); setOutcome(null); }} className="mb-1 block w-full rounded border border-slate-200 p-2 text-left text-xs">
              {d.dispute_id} <Badge>{d.status}</Badge><div className="text-slate-500">{d.transaction_id}</div>
            </button>
          ))}
        </Card>
      </div>
      <div className="space-y-3 md:col-span-2">
        {!analysis && <Card><p className="text-sm text-slate-500">Open or select a dispute to compare evidence.</p></Card>}
        {analysis && dispute && (
          <>
            <Card title={`Dispute ${analysis.dispute_id}`} right={<Badge>{analysis.dispute_status}</Badge>}>
              <p className="text-sm">Transaction <code>{analysis.transaction_id}</code> is <Badge>{analysis.transaction_status}</Badge>. Failed stage: <b>{analysis.failed_stage ?? "none detected"}</b></p>
              <p className="mt-2 rounded bg-slate-100 p-2 text-sm"><b>Responsibility: {analysis.responsibility.determination}.</b> {analysis.responsibility.note}</p>
            </Card>
            <Card title="Violated conditions">
              {analysis.violated_conditions.length === 0 ? <p className="text-sm text-slate-500">None recorded.</p> :
                <ul className="list-disc pl-5 text-sm text-red-700">{analysis.violated_conditions.map((v: any, i: number) => <li key={i}><b>{v.code}</b>: {v.message}</li>)}</ul>}
            </Card>
            <Card title="Discrepancies between sources">
              {analysis.discrepancies.length === 0 ? <p className="text-sm text-slate-500">None detected.</p> : (
                <table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500"><th>Stage</th><th>Field</th><th>Expected</th><th>Observed</th></tr></thead>
                  <tbody>{analysis.discrepancies.map((d: any, i: number) => (
                    <tr key={i} className="border-t border-slate-100"><td>{d.stage}</td><td>{d.field}</td><td>{String(d.expected)}<div className="text-xs text-slate-500">{d.expected_source}</div></td><td>{String(d.observed)}<div className="text-xs text-slate-500">{d.observed_source}</div></td></tr>))}</tbody></table>)}
            </Card>
            <Card title="Evidence by party">
              <div className="grid gap-2 md:grid-cols-2">
                {Object.entries(analysis.evidence_by_party).map(([party, items]: [string, any]) => (
                  <div key={party} className="rounded border border-slate-200 p-2"><div className="text-xs font-semibold uppercase text-slate-500">{party}</div>
                    {items.length === 0 ? <p className="text-xs text-slate-400">no evidence</p> : items.map((e: any, i: number) => <div key={i} className="text-xs"><Badge>{e.level}</Badge> {e.summary}</div>)}</div>
                ))}
              </div>
            </Card>
            <Card title="Not established (unknowns)"><ul className="list-disc pl-5 text-sm text-slate-700">{analysis.unknown_facts.map((u: string, i: number) => <li key={i}>{u}</li>)}</ul></Card>
            <Card title="Recovery (simulated)">
              <p className="text-sm">Cancellation possible: <b>{analysis.cancellation.possible ? "yes (merchant may still reject)" : "no"}</b>. {analysis.cancellation.reason}</p>
              <div className="mt-2 flex gap-2">
                <Btn kind="danger" disabled={!analysis.cancellation.possible || dispute.status !== "OPEN"} onClick={cancel}>Request cancellation from mock merchant</Btn>
                <Btn disabled={dispute.status !== "OPEN"} onClick={close}>Close dispute</Btn>
              </div>
              {outcome && <p className="mt-2 text-sm">Merchant result: <Badge>{outcome}</Badge> (no real refund, chargeback or insurance payout exists in this MVP)</p>}
              <p className="mt-1 text-xs text-slate-500">Charged: {krw(txs.find((t) => t.transaction_id === analysis.transaction_id)?.charged_krw)}</p>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
