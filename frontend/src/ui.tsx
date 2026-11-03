import { ReactNode } from "react";

export function Card({ title, children, right }: { title?: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

const tone: Record<string, string> = {
  ALLOW: "bg-green-100 text-green-800", DENY: "bg-red-100 text-red-800", REQUIRE_APPROVAL: "bg-amber-100 text-amber-800",
  EXECUTED: "bg-green-100 text-green-800", DENIED: "bg-red-100 text-red-800", FAILED: "bg-red-100 text-red-800",
  UNKNOWN: "bg-slate-200 text-slate-700", DISCREPANCY: "bg-amber-100 text-amber-800", CANCELLED: "bg-blue-100 text-blue-800",
  ACTIVE: "bg-green-100 text-green-800", REVOKED: "bg-red-100 text-red-800", EXPIRED: "bg-slate-200 text-slate-700",
  PENDING_APPROVAL: "bg-amber-100 text-amber-800", SUPERSEDED: "bg-slate-200 text-slate-600", OPEN: "bg-amber-100 text-amber-800",
  CLOSED: "bg-slate-200 text-slate-700", SELF_REPORTED: "bg-amber-100 text-amber-800", GATEWAY_VERIFIED: "bg-indigo-100 text-indigo-800",
  MERCHANT_CONFIRMED: "bg-teal-100 text-teal-800", AUTHORIZED: "bg-indigo-100 text-indigo-800", REJECTED: "bg-red-100 text-red-800",
};

export function Badge({ children }: { children: string }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone[children] ?? "bg-slate-100 text-slate-700"}`}>{children}</span>;
}

export function Json({ data }: { data: unknown }) {
  return <pre className="max-h-96 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(data, null, 2)}</pre>;
}

export function Btn(props: React.ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "danger" | "plain" }) {
  const { kind = "plain", className = "", ...rest } = props;
  const k = { primary: "bg-indigo-600 text-white hover:bg-indigo-700", danger: "bg-red-600 text-white hover:bg-red-700",
              plain: "border border-slate-300 bg-white hover:bg-slate-50" }[kind];
  return <button {...rest} className={`rounded px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${k} ${className}`} />;
}

export function ErrorNote({ error }: { error: string | null }) {
  return error ? <p role="alert" className="mt-2 rounded bg-red-50 p-2 text-sm text-red-700">{error}</p> : null;
}
