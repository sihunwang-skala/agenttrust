import { useEffect, useState } from "react";
import { api } from "../api";
import type { Shared } from "../App";
import { Badge, Card, ErrorNote } from "../ui";

export default function Dashboard({ tick, goto }: Shared) {
  const [s, setS] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api("/dashboard/summary").then(setS).catch((e) => setErr(e.message)); }, [tick]);
  if (err) return <ErrorNote error={`Backend unreachable: ${err}`} />;
  if (!s) return <p>Loading…</p>;
  const stats = [["Total agent actions", s.total_actions], ["Approved actions", s.approved_actions], ["Blocked actions", s.blocked_actions],
                 ["Awaiting user approval", s.pending_approval], ["Open disputes", s.open_disputes]];
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {stats.map(([k, v]) => (
          <Card key={k as string}><div className="text-xs text-slate-500">{k}</div><div className="text-2xl font-bold">{v}</div></Card>
        ))}
      </div>
      <Card title="Recent receipts" right={<button className="text-sm text-indigo-700" onClick={() => goto("Receipt Explorer")}>Open explorer</button>}>
        {s.recent_receipts.length === 0 ? <p className="text-sm text-slate-500">No receipts yet. Create a delegation, then run the Agent Simulator.</p> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th className="pr-3">#</th><th className="pr-3">Time</th><th>Event</th><th>Decision</th><th>Status</th><th>Evidence level</th></tr></thead>
            <tbody>
              {s.recent_receipts.map((r: any) => (
                <tr key={r.receipt_id} className="border-t border-slate-100">
                  <td className="pr-3">{r.seq}</td><td className="whitespace-nowrap pr-3 text-xs">{r.timestamp}</td><td>{r.event_type}</td>
                  <td><Badge>{r.policy_decision}</Badge></td><td>{r.execution_status}</td><td><Badge>{r.verification_level}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
