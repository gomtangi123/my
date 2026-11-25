export function Card({ title, children, right }: { title?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-bold text-slate-700">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-bold tabular-nums">{value}</p>
      {sub && <p className="text-[11px] text-slate-400">{sub}</p>}
    </div>
  );
}

/** 탭처럼 보이는 링크 묶음 */
export function Pills({ items, active }: { items: { key: string; label: string; href: string }[]; active: string }) {
  return (
    <div className="flex flex-wrap gap-2" role="tablist">
      {items.map((t) => (
        <a
          key={t.key}
          href={t.href}
          role="tab"
          aria-selected={active === t.key}
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            active === t.key ? "bg-slate-900 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"
          }`}
        >
          {t.label}
        </a>
      ))}
    </div>
  );
}
