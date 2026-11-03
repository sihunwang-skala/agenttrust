import { FormEvent, useEffect, useState } from "react";
import { api, krw, post } from "../api";
import type { Shared } from "../App";
import { Badge, Btn, Card, ErrorNote } from "../ui";

const DEFAULTS = {
  agent_id: "agent_demo", total_budget_krw: 300000, per_item_max_krw: 200000, allowed_categories: "Electronics",
  allowed_merchants: "m_techmart, m_gadgethub", require_free_returns: true, max_delivery_days: 7, valid_for_minutes: 60,
  auto_purchase_allowed: true,
};

export default function Delegation({ delegationId, setDelegationId, tick, refresh }: Shared) {
  const [list, setList] = useState<any[]>([]);
  const [form, setForm] = useState<any>(DEFAULTS);
  const [err, setErr] = useState<string | null>(null);
  const [reviseFor, setReviseFor] = useState<string | null>(null);
  useEffect(() => { api("/delegations").then(setList).catch((e) => setErr(e.message)); }, [tick]);

  const set = (k: string, v: unknown) => setForm((f: any) => ({ ...f, [k]: v }));
  const payload = () => ({
    ...form,
    total_budget_krw: Number(form.total_budget_krw), per_item_max_krw: Number(form.per_item_max_krw),
    max_delivery_days: Number(form.max_delivery_days), valid_for_minutes: Number(form.valid_for_minutes),
    allowed_categories: String(form.allowed_categories).split(",").map((s) => s.trim()).filter(Boolean),
    allowed_merchants: String(form.allowed_merchants).split(",").map((s) => s.trim()).filter(Boolean),
  });
  const run = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); refresh(); } catch (e: any) { setErr(e.message); } };

  const submit = (e: FormEvent) => { e.preventDefault(); run(async () => {
    if (reviseFor) { await post(`/delegations/${reviseFor}/revisions`, payload()); setReviseFor(null); }
    else { const d = await post("/delegations", payload()); setDelegationId(d.delegation_id); }
  }); };

  const field = (label: string, k: string, type = "text") => (
    <label className="block text-sm">{label}
      <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type={type} value={form[k]} onChange={(e) => set(k, e.target.value)} />
    </label>
  );
  const check = (label: string, k: string) => (
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form[k]} onChange={(e) => set(k, e.target.checked)} />{label}</label>
  );

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card title={reviseFor ? `New version of ${reviseFor}` : "Create delegation"}>
        <form onSubmit={submit} className="space-y-3">
          {field("Agent ID", "agent_id")}
          {field("Total budget (KRW)", "total_budget_krw", "number")}
          {field("Max per item (KRW)", "per_item_max_krw", "number")}
          {field("Allowed categories (comma separated)", "allowed_categories")}
          {field("Allowed merchant IDs (comma separated)", "allowed_merchants")}
          {field("Max delivery days", "max_delivery_days", "number")}
          {field("Valid for (minutes, counted from approval)", "valid_for_minutes", "number")}
          {check("Require free returns", "require_free_returns")}
          {check("Allow automatic purchase (otherwise each action needs your approval)", "auto_purchase_allowed")}
          <div className="flex gap-2">
            <Btn type="submit" kind="primary">{reviseFor ? "Create new version (pending)" : "Create delegation (pending)"}</Btn>
            {reviseFor && <Btn type="button" onClick={() => setReviseFor(null)}>Cancel</Btn>}
          </div>
          <p className="text-xs text-slate-500">A delegation has no effect until you explicitly approve it. Approval is recorded on the Demo Trusted Surface and is NOT a cryptographic signature by you.</p>
        </form>
        <ErrorNote error={err} />
      </Card>
      <div className="space-y-3">
        {list.length === 0 && <Card><p className="text-sm text-slate-500">No delegations yet.</p></Card>}
        {list.map((d) => (
          <Card key={d.delegation_id} title={`${d.delegation_id} · v${d.version}`} right={<Badge>{d.status}</Badge>}>
            <dl className="grid grid-cols-2 gap-1 text-sm">
              <dt className="text-slate-500">Agent</dt><dd>{d.agent_id}</dd>
              <dt className="text-slate-500">Budget</dt><dd>{krw(d.total_budget_krw)} (spent {krw(d.spent_krw)}, left {krw(d.remaining_krw)})</dd>
              <dt className="text-slate-500">Per item max</dt><dd>{krw(d.per_item_max_krw)}</dd>
              <dt className="text-slate-500">Categories</dt><dd>{d.allowed_categories.join(", ")}</dd>
              <dt className="text-slate-500">Merchants</dt><dd>{d.allowed_merchants.join(", ")}</dd>
              <dt className="text-slate-500">Free returns</dt><dd>{d.require_free_returns ? "required" : "not required"}</dd>
              <dt className="text-slate-500">Auto purchase</dt><dd>{d.auto_purchase_allowed ? "allowed" : "approval per action"}</dd>
              <dt className="text-slate-500">Expires</dt><dd>{d.expires_at ?? `${d.valid_for_minutes} min after approval`}</dd>
            </dl>
            <div className="mt-3 flex flex-wrap gap-2">
              {d.status === "PENDING_APPROVAL" && <Btn kind="primary" onClick={() => run(async () => { await post(`/delegations/${d.delegation_id}/approve`); setDelegationId(d.delegation_id); })}>Approve (demo surface)</Btn>}
              {["ACTIVE", "PENDING_APPROVAL"].includes(d.status) && <Btn kind="danger" onClick={() => run(() => post(`/delegations/${d.delegation_id}/revoke`))}>Revoke</Btn>}
              {d.status !== "REVOKED" && <Btn onClick={() => { setReviseFor(d.delegation_id); setForm({ ...d, allowed_categories: d.allowed_categories.join(", "), allowed_merchants: d.allowed_merchants.join(", ") }); }}>Revise (new version)</Btn>}
              <Btn onClick={() => setDelegationId(d.delegation_id)} disabled={d.delegation_id === delegationId}>{d.delegation_id === delegationId ? "Selected for simulator" : "Select for simulator"}</Btn>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
