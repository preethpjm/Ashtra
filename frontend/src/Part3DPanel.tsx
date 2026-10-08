import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "./api";

const ModelViewer = lazy(() => import("./ModelViewer"));

const PN_ATTRS = ["partNumberValue", "partNumber", "toolNumber", "supplyNumber", "pnr"];
const PN_ELEMS = new Set(["partNumber", "pnr", "toolnbr", "connbr", "partNumberValue"]);
const local = (e: Element) => e.localName;

function own(e: Element): string | null {
  for (const a of PN_ATTRS) { const v = e.getAttribute(a); if (v?.trim()) return v.trim(); }
  if (PN_ELEMS.has(local(e))) { const t = (e.textContent ?? "").trim(); if (t) return t; }
  return null;
}

/** The part number an element is about: its own, the first one inside it (an IPL line, a tool description),
 *  or the nearest one around it (an element inside an IPL line). Works for S1000D, ATA and S2000M markup. */
export function partNumberOf(el: Element | null): string | null {
  if (!el) return null;
  const mine = own(el);
  if (mine) return mine;
  const walker = el.ownerDocument.createTreeWalker(el, NodeFilter.SHOW_ELEMENT);
  for (let n = walker.nextNode() as Element | null, i = 0; n && i < 60; n = walker.nextNode() as Element | null, i++) {
    const v = own(n);
    if (v) return v;
  }
  for (let p = el.parentElement, d = 0; p && d < 4; p = p.parentElement, d++) {
    if (/^(itemdata|catalogSeqNumber|itemSeqNumber|supportEquipDescr|supplyDescr|spareDescr|part|ipdItem|ted|con)$/.test(local(p))) {
      return partNumberOf(p);
    }
  }
  return null;
}

type Hit = { model_id: number; model: string; nodes: string[] };
const cache = new Map<string, { at: number; p: Promise<Hit[]> }>();   // short-lived: the library can change

/** Inspector panel: the selected part in the library's 3D model, if one shows it. */
export function Part3DPanel({ el }: { el: Element | null }) {
  const pn = partNumberOf(el);
  const [hits, setHits] = useState<{ pn: string; list: Hit[] } | null>(null);
  useEffect(() => {
    if (!pn) return;
    let alive = true;
    const c = cache.get(pn);
    if (!c || Date.now() - c.at > 15000) {
      if (cache.size > 300) cache.clear();
      cache.set(pn, { at: Date.now(), p: api.kLocate(pn).catch(() => [] as Hit[]) });
    }
    cache.get(pn)!.p.then((list) => { if (alive) setHits({ pn, list }); });
    return () => { alive = false; };
  }, [pn]);
  if (!pn || !hits || hits.pn !== pn || !hits.list.length) return null;
  const m = hits.list[0];
  return (
    <div className="p3d">
      <h3>3D · <span className="mono">{pn}</span></h3>
      <Suspense fallback={<div className="mv-msg">Loading 3D viewer…</div>}>
        <ModelViewer url={`/api/knowledge/models/${m.model_id}/file`} highlight={m.nodes} height={240} />
      </Suspense>
      <p className="muted small">In {m.model}{hits.list.length > 1 ? ` and ${hits.list.length - 1} other model(s)` : ""} · from the knowledge library</p>
    </div>
  );
}
