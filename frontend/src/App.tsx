import { useEffect, useState } from "react";
import { api } from "./api";
import Dashboard from "./pages/Dashboard";
import Delegation from "./pages/Delegation";
import Simulator from "./pages/Simulator";
import Receipts from "./pages/Receipts";
import Disputes from "./pages/Disputes";
import { Btn } from "./ui";

const TABS = ["Dashboard", "Delegation", "Agent Simulator", "Receipt Explorer", "Dispute & Recovery"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const [tab, setTab] = useState<Tab>("Dashboard");
  const [delegationId, setDelegationId] = useState<string>("");
  const [txFocus, setTxFocus] = useState<string>("");
  const [tick, setTick] = useState(0);
  const [health, setHealth] = useState<{ demo_reset_enabled?: boolean } | null>(null);
  const refresh = () => setTick((t) => t + 1);

  useEffect(() => { api("/health").then(setHealth).catch(() => setHealth(null)); }, []);

  const shared = { delegationId, setDelegationId, tick, refresh, txFocus, setTxFocus, goto: (t: Tab) => setTab(t) };
  return (
    <div className="min-h-screen">
      <div className="bg-amber-100 px-4 py-2 text-center text-xs font-medium text-amber-900" role="note">
        DEMO / MOCK DATA ONLY: simulated merchant, no real payments or personal data. Approvals happen on a Demo Trusted Surface and are not
        cryptographically signed by the user. AgentTrust does not determine legal responsibility.
      </div>
      <header className="flex flex-wrap items-center gap-4 border-b border-slate-200 bg-white px-6 py-3">
        <h1 className="text-lg font-bold">AgentTrust</h1>
        <nav className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)} aria-current={tab === t}
              className={`rounded px-3 py-1.5 text-sm ${tab === t ? "bg-indigo-600 text-white" : "hover:bg-slate-100"}`}>{t}</button>
          ))}
        </nav>
        {health?.demo_reset_enabled && (
          <Btn className="ml-auto" kind="danger" onClick={async () => {
            if (confirm("Delete ALL demo data (delegations, receipts, disputes)?")) { await api("/demo/reset", { method: "POST" }); setDelegationId(""); refresh(); }
          }}>Reset demo data</Btn>
        )}
      </header>
      <main className="mx-auto max-w-6xl space-y-4 p-6">
        {tab === "Dashboard" && <Dashboard {...shared} />}
        {tab === "Delegation" && <Delegation {...shared} />}
        {tab === "Agent Simulator" && <Simulator {...shared} />}
        {tab === "Receipt Explorer" && <Receipts {...shared} />}
        {tab === "Dispute & Recovery" && <Disputes {...shared} />}
      </main>
    </div>
  );
}

export type Shared = {
  delegationId: string; setDelegationId: (s: string) => void; tick: number; refresh: () => void;
  txFocus: string; setTxFocus: (s: string) => void; goto: (t: Tab) => void;
};
