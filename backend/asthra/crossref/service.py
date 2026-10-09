"""Cross-referencing as the application uses it: data models loaded from XMI, the vocabulary, what each standard
(or installed schema) calls each term, and every item's facts shown in the words of the standard you choose."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .facts import (SCHEMA, SOURCE_COLUMN, SUBJECT_LABEL, find_subjects, library_facts, read_document,
                    store_document_facts)
from .coverage import LABEL, S_SERIES, SOURCE_STANDARD, candidates, download_page, guess_standard, norm_standard, uncertain
from .names import SchemaIndex, family_of, schema_names
from .vocab import CORE, CROSSWALK, Vocabulary, model_label
from .xmi import read_xmi


class CrossrefError(ValueError):
    pass


class CrossrefService:
    def __init__(self, knowledge, registry):
        self.k, self.registry = knowledge, registry
        self.dir = Path(knowledge.models_dir).parent / "crossref"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.k.store.db.executescript(SCHEMA)
        self._vocab: Vocabulary | None = None
        self._models: list[dict] | None = None
        self._schema_cache: dict[tuple, dict] = {}
        self.lock = threading.Lock()

    @property
    def db(self):
        return self.k.store.db

    # ------------------------------------------------------------------ data models
    def models(self) -> list[dict]:
        with self.lock:                     # requests arrive in parallel: never publish a half-read list
            if self._models is None:
                models = []
                for f in sorted(self.dir.glob("model-*.json")):
                    try:
                        models.append(json.loads(f.read_text(encoding="utf-8")))
                    except (OSError, ValueError):
                        continue
                self._models = models
            return self._models

    @property
    def vocab(self) -> Vocabulary:
        models = self.models()
        with self.lock:
            if self._vocab is None or self._vocab.models is not models:
                self._vocab = Vocabulary(models)
            return self._vocab

    def add_model(self, filename: str, data: bytes) -> dict:
        try:
            m = read_xmi(data)
        except Exception as e:                                    # noqa: BLE001 - shown to the user
            raise CrossrefError(f"{filename} is not a readable XMI file: {e}") from e
        if not m["classes"]:
            raise CrossrefError(f"{filename} has no UML classes: is it an S-Series data model exported as XMI?")
        if not m["spec"]:
            m["spec"] = re.sub(r"[_\-]?data[_\-]?model.*", "", Path(filename).stem, flags=re.I).upper() or "MODEL"
        m["file"] = filename
        name = "model-" + re.sub(r"[^A-Za-z0-9.]+", "_", f"{m['spec']}-{m['issue']}") + ".json"
        (self.dir / name).write_text(json.dumps(m), encoding="utf-8")
        self._models = self._vocab = None
        self._schema_cache.clear()
        row = self._model_row(m)
        row["hints"] = self.hints(m["spec"])
        return row

    def delete_model(self, label: str) -> None:
        for f in self.dir.glob("model-*.json"):
            m = json.loads(f.read_text(encoding="utf-8"))
            if model_label(m) == label:
                f.unlink()
        self._models = self._vocab = None
        self._schema_cache.clear()

    @staticmethod
    def _model_row(m: dict) -> dict:
        cs = m["classes"].values()
        return {"label": model_label(m), "spec": m["spec"], "issue": m["issue"], "file": m.get("file", ""),
                "classes": len(m["classes"]), "common": sum(1 for c in cs if c["common"]),
                "attributes": sum(len(c["attrs"]) for c in cs)}

    # ------------------------------------------------------------------ views (columns)
    def views(self) -> list[dict]:
        """What data can be shown as: each loaded data model, each crosswalk family, each installed schema."""
        out = [{"id": model_label(m), "label": model_label(m), "kind": "data model"} for m in self.models()]
        out += [{"id": f, "label": f, "kind": "crosswalk"} for f in CROSSWALK]
        for p in self.registry.list():
            for d in p.manifest.doc_types:
                out.append({"id": f"pkg:{p.manifest.key}|{d.id}", "label": f"{p.manifest.standard} {p.manifest.issue} · {d.label}",
                            "kind": "installed schema", "standard": p.manifest.standard})
        return out

    def overview(self) -> dict:
        v = self.vocab
        return {"models": [self._model_row(m) for m in self.models()], "views": self.views(),
                "terms": len(v.terms), "classes": len(v.classes), "core": sum(1 for t in v.terms.values() if t.get("core")),
                "subjects": SUBJECT_LABEL}

    def _overrides(self, package_id: str, doc_type: str) -> dict:
        return {r["term"]: {"path": r["path"], "tag": r["tag"]} for r in self.db.execute(
            "SELECT term, path, tag FROM xr_name WHERE package_id=? AND doc_type=?", (package_id, doc_type))}

    def names_for(self, view: str, terms: list[str] | None = None) -> dict[str, dict]:
        """term -> {tag, path, from} in one view."""
        v = self.vocab
        if not view.startswith("pkg:"):
            return {tid: t["names"][view] for tid, t in v.terms.items() if view in t["names"] and (terms is None or tid in terms)}
        pid, _, dt = view[4:].partition("|")
        try:
            pkg = self.registry.get(pid)
            model = self.registry.schema_model(pid, dt)
        except Exception as e:                                    # noqa: BLE001
            raise CrossrefError(f"The schema {pid} / {dt} could not be read: {e}") from e
        ck = (pid, dt, pkg.checksum, len(self.models()), tuple(sorted(terms)) if terms else None,
              self.db.execute("SELECT COUNT(*), MAX(saved_at) FROM xr_name WHERE package_id=? AND doc_type=?", (pid, dt)).fetchone()[:])
        if ck not in self._schema_cache:
            self._schema_cache[ck] = schema_names(v, self.models(), pkg.manifest.standard, model,
                                                  self._overrides(pid, dt), terms)
        return self._schema_cache[ck]

    def confirm_name(self, package_id: str, doc_type: str, term: str, path: str) -> dict:
        if term not in self.vocab.terms:
            raise CrossrefError(f"unknown term {term}")
        if path:
            with self.k.lock:
                self.db.execute("INSERT OR REPLACE INTO xr_name(package_id, doc_type, term, path, tag, saved_at) VALUES (?,?,?,?,?,?)",
                                (package_id, doc_type, term, path, path.split("/")[-1],
                                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
                self.db.commit()
        else:
            with self.k.lock:
                self.db.execute("DELETE FROM xr_name WHERE package_id=? AND doc_type=? AND term=?", (package_id, doc_type, term))
                self.db.commit()
        self._schema_cache.clear()
        return self.term(term)

    def confirm_many(self, package_id: str, doc_type: str, items: list[dict], whole_standard: bool = True) -> dict:
        """Several confirmations at once: [{term, path}] (path "-" = the schema has no place for it). With
        whole_standard, each also applies to the other schemas of the same standard (every issue and document
        type) where that term is still uncertain or not found: a path where the same place exists there,
        "not here" as it is."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        items = [it for it in items if it.get("term") in self.vocab.terms and it.get("path")]
        targets = [(package_id, doc_type)]
        if whole_standard:
            std = norm_standard(self.registry.get(package_id).manifest.standard)
            targets += [(p.manifest.key, d.id) for p in self.registry.list() if norm_standard(p.manifest.standard) == std
                        for d in p.manifest.doc_types if (p.manifest.key, d.id) != (package_id, doc_type)]
        rows = []
        for i, (pid, dt) in enumerate(targets):
            if i == 0:
                rows += [(pid, dt, it["term"], it["path"]) for it in items]
                continue
            try:
                current = self.names_for(f"pkg:{pid}|{dt}", [it["term"] for it in items])
                idx = SchemaIndex(self.registry.schema_model(pid, dt))
            except Exception:                               # noqa: BLE001 - a schema that cannot be read is skipped
                continue
            over = self._overrides(pid, dt)
            for it in items:
                n = current.get(it["term"])
                if it["term"] in over or (n and not uncertain(n)):
                    continue                                # already decided there
                if it["path"] == "-" or idx.resolve(it["path"]):
                    rows.append((pid, dt, it["term"], it["path"]))
        with self.k.lock:
            for pid, dt, term, path in rows:
                self.db.execute("INSERT OR REPLACE INTO xr_name(package_id, doc_type, term, path, tag, saved_at) VALUES (?,?,?,?,?,?)",
                                (pid, dt, term, path, path.split("/")[-1], now))
            self.db.commit()
        self._schema_cache.clear()
        out = self.review(f"pkg:{package_id}|{doc_type}")
        out["applied_elsewhere"] = len({(p, d) for p, d, _, _ in rows} - {(package_id, doc_type)})
        return out

    # ------------------------------------------------------------------ review: placements a person should look at
    def review(self, view: str) -> dict:
        """The library's generic names in one installed schema: confirmed, sure, to review (found by name only or
        in several places) and not found — each with the places it could go."""
        if not view.startswith("pkg:"):
            raise CrossrefError("Only an installed schema can be reviewed.")
        pid, _, dt = view[4:].partition("|")
        core = [t for t, x in self.vocab.terms.items() if x.get("core")]
        names = self.names_for(view, core)
        over = self._overrides(pid, dt)
        idx = SchemaIndex(self.registry.schema_model(pid, dt))
        rows = []
        for tid in core:
            t = self.vocab.terms[tid]
            n = names.get(tid)
            if tid in over and over[tid]["path"] == "-":
                status = "none"
            elif n and n.get("from") == "confirmed":
                status = "confirmed"
            elif uncertain(n):
                status = "review"
            elif n:
                status = "ok"
            else:
                status = "missing"
            rows.append({"term": tid, "label": t["label"], "group": t.get("core", ""), "doc": t["doc"][:200],
                         "placement": n, "status": status,
                         "candidates": candidates(idx, t, strong_only=status == "missing") if status in ("review", "missing") else []})
        counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("confirmed", "ok", "review", "missing", "none")}
        label = next((v["label"] for v in self.views() if v["id"] == view), view)
        return {"view": view, "label": label, "rows": rows, "counts": counts}

    # ------------------------------------------------------------------ coverage: what each standard has and needs
    def _documents(self) -> list[dict]:
        out = []
        for p in self.k.projects.list():
            for d in self.k.documents.list(p["id"]):
                out.append({**d, "project": p["name"]})
        return out

    def _doc_standard(self, d: dict) -> str | None:
        if d.get("standard"):
            return norm_standard(d["standard"])
        tags = None
        if d.get("syntax") == "xml" and (d.get("size_bytes") or 0) < 20_000_000:
            try:
                from lxml import etree
                data, _ = self.k.documents.current_bytes(d["id"])
                root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, recover=True))
                tags = {etree.QName(e).localname for e in root.iter() if isinstance(e.tag, str)} if root is not None else None
            except Exception:                                    # noqa: BLE001 - a guess only
                tags = None
        g = guess_standard(d.get("identification") or {}, tags, self.models())
        return norm_standard(g) if g else None

    def doc_hint(self, d: dict) -> dict | None:
        """What to install so a document can be validated and cross-referenced."""
        std = self._doc_standard(d)
        if not d.get("package_id"):
            opt = self._suggest_schema(d)
            if opt:
                lab = f"{opt['standard']} {opt['issue']} · {opt['label']}"
                return {"standard": std or norm_standard(opt["standard"]), "label": LABEL.get(std, std) if std else opt["standard"],
                        "needs": ["choose"], "choose": {**opt, "text": lab},
                        "message": self._choose_message(d, opt, lab, "choose it in the panel on the right")}
        if not std:
            return None
        have_schema = bool(d.get("package_id"))
        have_model = any(norm_standard(m["spec"]) == std for m in self.models())
        needs = []
        if not have_schema and std != "ENGINEERING BOM":
            needs.append("schema")
        if std in S_SERIES and not have_model:
            needs.append("model")
        if not needs:
            return None
        where = download_page(std)
        lab = LABEL.get(std, std)
        what = " and ".join({"schema": "its XML schema (XSD)" if std != "ATA2200" else "its DTD",
                             "model": "its data model (XMI)"}[n] for n in needs)
        msg = (f"This looks like an {lab} document. Install {what}"
               + (" so it can be validated" if "schema" in needs else "")
               + (" and its data read and cross-referenced" if "model" in needs else "")
               + (f" — download page: {where[0]}" if where else "") + ".")
        return {"standard": std, "label": lab, "needs": needs, "message": msg, "url": where[0] if where else None}

    def coverage(self) -> dict:
        core = [t for t, x in self.vocab.terms.items() if x.get("core")]
        stds: dict[str, dict] = {}

        def row(std: str) -> dict:
            s = norm_standard(std)
            return stds.setdefault(s, {"standard": s, "label": LABEL.get(s, s), "schemas": [], "model": None, "documents": 0,
                                       "unidentified": [], "unchosen": [], "library": 0, "crosswalk": s in ("S1000D", "ATA2200", "ENGINEERING BOM"),
                                       "s_series": s in S_SERIES})
        for p in self.registry.list():
            r = row(p.manifest.standard)
            for d in p.manifest.doc_types:
                view = f"pkg:{p.manifest.key}|{d.id}"
                try:
                    names = self.names_for(view, core)
                    rv = {k: 0 for k in ("confirmed", "review")}
                    for tid, n in names.items():
                        if n.get("from") == "confirmed":
                            rv["confirmed"] += 1
                        elif uncertain(n):
                            rv["review"] += 1
                            r.setdefault("_review_terms", set()).add(tid)
                    r["schemas"].append({"view": view, "label": f"{p.manifest.issue} · {d.label}", "placed": len(names),
                                         "of": len(core), **rv})
                except CrossrefError as e:
                    r["schemas"].append({"view": view, "label": f"{p.manifest.issue} · {d.label}", "error": str(e)})
        for m in self.models():
            row(m["spec"])["model"] = self._model_row(m)
        for kind, n in self.db.execute("SELECT kind, COUNT(*) FROM source GROUP BY kind").fetchall():
            st = next((v for k, v in SOURCE_STANDARD.items() if kind.upper().startswith(k)), None)
            if st:
                row(st)["library"] += n
        waiting: dict[str, dict] = {}                    # one entry per file (same content in several projects)
        for d in self._documents():
            std = self._doc_standard(d)
            if d.get("package_id"):
                if std:
                    row(std)["documents"] += 1
                continue
            opt = self._suggest_schema(d)
            key = d.get("sha256") or d["id"]
            w = waiting.get(key)
            if w:
                w["ids"].append(d["id"])
                if d["project"] not in w["projects"]:
                    w["projects"].append(d["project"])
                continue
            if opt:
                std = std or norm_standard(opt["standard"])
                lab = f"{opt['standard']} {opt['issue']} · {opt['label']}"
                msg = self._choose_message(d, opt, lab, "choose it as its schema")
                h = {"standard": std, "label": LABEL.get(std, std), "message": msg,
                     "choose": {**opt, "text": lab, "names_schema": self._names_schema(d)}}
            elif std:
                h = self.doc_hint(d) or {"standard": std, "label": LABEL.get(std, std), "message": "Install its schema."}
            else:
                root = ((d.get("identification") or {}).get("root") or {}).get("local_name") or "?"
                h = {"standard": None, "message": f"Not recognised (root element <{root}>): install the schema it is written to."}
            waiting[key] = {"id": d["id"], "ids": [d["id"]], "name": d["original_name"], "projects": [d["project"]], **h}
            if std:
                r = row(std)
                r["documents"] += 1
                r["unchosen" if opt else "unidentified"].append(d["original_name"])
                if opt:
                    r.setdefault("_choose", {}).setdefault((opt["package_id"], opt["doc_type"], lab, opt["declared"]), [])
                else:
                    r["_needs_install"] = True
        for w in waiting.values():                        # the files each "choose" action covers (all copies)
            c = w.get("choose")
            if c and w.get("standard"):
                r = row(w["standard"])
                r["_choose"][(c["package_id"], c["doc_type"], c["text"], c["declared"])] += w["ids"]
                if not c["declared"] and not c.get("names_schema"):
                    r.setdefault("_unnamed", set()).update(w["ids"])
        waiting_list = sorted(waiting.values(), key=lambda w: (w.get("choose") is None, w["name"]))
        out = []
        for r in stds.values():
            actions = []
            where = download_page(r["standard"])
            unnamed = r.pop("_unnamed", None) or set()
            for (pid, dt, text, declared), ids in (r.pop("_choose", None) or {}).items():
                why = ("installed and fits" if declared else
                       "fits their root element; they do not name a schema" if set(ids) <= unnamed else
                       "closest installed issue; the declared one is not installed")
                actions.append({"do": "choose_schema", "label": f"Use {text} for {len(ids)} document(s)", "package_id": pid,
                                "doc_type": dt, "ids": ids, "certain": declared, "why": why})
            needs_install = r.pop("_needs_install", False)
            hub = self.vocab.hub
            r["hub"] = bool(hub and r["model"] and norm_standard(hub["spec"]) == r["standard"])
            if r["hub"] and not r["schemas"] and not needs_install:
                pass                                         # the reference model: its XSD only matters to exchange its own data
            elif (not r["schemas"] or needs_install) and r["standard"] != "ENGINEERING BOM":
                n_wait = sum(1 for w in waiting_list if w.get("standard") == r["standard"] and not w.get("choose"))
                actions.append({"do": "install_schema", "label": "Install schema…",
                                "why": f"{n_wait} document(s) cannot be validated" if n_wait
                                else "documents of this standard cannot be validated or placed"})
            if r["s_series"] and not r["model"]:
                actions.append({"do": "add_model", "label": "Add data model (XMI)…",
                                "why": "its documents cannot be read field by field, and its names are guessed"})
            rev = len(r.pop("_review_terms", None) or ())
            if rev:
                n = sum(1 for x in r["schemas"] if x.get("review"))
                actions.append({"do": "review", "label": f"Review {rev} placement(s)", "view": next(x["view"] for x in r["schemas"] if x.get("review")),
                                "why": f"confirmed once for all {n} {r['label']} schemas where the place exists" if n > 1 else ""})
            out.append({**r, "actions": actions, "where": {"url": where[0], "what": where[1]} if where else None,
                        "status": "ok" if not actions else ("review" if all(a["do"] in ("review", "choose_schema") for a in actions) else "missing")})
        out.sort(key=lambda r: ({"missing": 0, "review": 1, "ok": 2}[r["status"]], r["label"]))
        return {"standards": out, "waiting": waiting_list}

    @staticmethod
    def _names_schema(d: dict) -> bool:
        """Whether the document says which schema (and issue) it is written to: a public identifier or a schema
        location. A bare system file name or a DTD inside the document does not."""
        root = (d.get("identification") or {}).get("root") or {}
        return bool((root.get("public_id") or "").strip() or (root.get("schema_location") or "").strip())

    def _choose_message(self, d: dict, opt: dict, lab: str, verb: str) -> str:
        if opt["declared"]:
            return f"{lab} is installed and fits this document: {verb}."
        if not self._names_schema(d):
            return (f"This document does not name its schema (no public identifier or schema location; its DTD may be "
                    f"inside the file). {lab} is installed and fits its root element: {verb}.")
        return (f"The issue this document declares is not installed. The closest installed schema is {lab}; "
                f"{verb}, or install the declared issue.")

    def _suggest_schema(self, d: dict) -> dict | None:
        """The installed schema to use for a document that was not identified: one it declares, else the
        closest (same standard, latest issue) whose root element fits."""
        try:
            opts = self.k.documents.schema_options(d["id"])
        except Exception:                                   # noqa: BLE001 - only a suggestion
            return None
        if not opts:
            return None
        declared = [o for o in opts if o.get("declared")]
        if declared:
            return declared[0]
        key = lambda o: [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", str(o.get("issue") or "0"))]
        best = max(opts, key=key)
        return {**best, "declared": False}

    def assign_schemas(self, items: list[dict]) -> dict:
        """Choose the schema of several documents at once: [{doc_id, package_id, doc_type}]."""
        done, failed = [], []
        for it in items:
            try:
                self.k.documents.choose_schema(it["doc_id"], it["package_id"], it["doc_type"])
                done.append(it["doc_id"])
            except Exception as e:                          # noqa: BLE001 - reported per document
                failed.append({"doc_id": it.get("doc_id"), "error": str(e)})
        return {"assigned": len(done), "failed": failed}

    def hints(self, standard: str = "") -> list[str]:
        """Short prompts after something was installed: what is still missing for that standard."""
        cov = self.coverage()
        out = []
        for r in cov["standards"]:
            if standard and r["standard"] != norm_standard(standard):
                continue
            for a in r["actions"]:
                if a["do"] == "add_model":
                    out.append(f"{r['label']}: add its data model (XMI) so its documents are read field by field"
                               + (f" — {r['where']['url']}" if r.get("where") else "") + ".")
                elif a["do"] == "install_schema":
                    out.append(f"{r['label']}: install its {'DTD' if r['standard'] == 'ATA2200' else 'XML schema'} so its documents "
                               "can be validated and data placed" + (f" — {r['where']['url']}" if r.get("where") else "") + ".")
                elif a["do"] == "choose_schema":
                    out.append(f"{r['label']}: {a['label'].lower()} under Knowledge → Cross-reference → Coverage.")
                elif a["do"] == "review":
                    out.append(f"{r['label']}: {a['label'].lower()} under Knowledge → Cross-reference → Coverage.")
        return out

    # ------------------------------------------------------------------ terms
    def terms(self, q: str = "", core: bool = False, common: bool = False, limit: int = 300) -> list[dict]:
        cols = [model_label(m) for m in self.models()] + list(CROSSWALK)
        return [{"id": t["id"], "label": t["label"], "class": t["class"], "doc": t["doc"][:240], "key": t["key"],
                 "common": t["common"], "core": t.get("core", ""), "origin": t["origin"],
                 "names": {c: t["names"][c]["tag"] for c in cols if c in t["names"]}}
                for t in self.vocab.search(q, core, common, limit)]

    def term(self, tid: str) -> dict:
        t = self.vocab.terms.get(tid)
        if not t:
            raise CrossrefError(f"unknown term {tid}")
        schemas = []
        for vw in self.views():
            if vw["kind"] != "installed schema":
                continue
            try:
                n = self.names_for(vw["id"], [tid]).get(tid)
            except CrossrefError:
                n = None
            schemas.append({"view": vw["id"], "label": vw["label"], **(n or {})})
        cls = self.vocab.classes.get(t["class"], {})
        return {**t, "class_doc": cls.get("doc", ""), "class_names": cls.get("names", {}), "uof": cls.get("uof", ""),
                "schemas": schemas}

    # ------------------------------------------------------------------ items
    def subjects(self, q: str) -> list[dict]:
        if not q.strip():
            return []
        with self.k.lock:
            return find_subjects(self.db, q)

    def item(self, subject: str, key: str, view: str) -> dict:
        with self.k.lock:
            facts = library_facts(self.db, subject, key)
        if not facts:
            raise CrossrefError(f"Nothing is known about {subject} {key}.")
        v = self.vocab
        names = self.names_for(view, sorted({f["term"] for f in facts})) if view else {}
        rows: dict[str, dict] = {}
        for f in facts:
            t = v.terms.get(f["term"], {"id": f["term"], "label": f["term"], "doc": ""})
            r = rows.setdefault(f["term"], {"term": f["term"], "label": t["label"], "doc": t.get("doc", "")[:240],
                                            "core": t.get("core", ""), "name": names.get(f["term"]), "values": []})
            col = SOURCE_COLUMN.get(f["source"]["kind"]) or next(
                (model_label(m) for m in self.models() if (m["spec"] or "").upper() in (f["source"].get("schema") or f["source"]["kind"]).upper()), None)
            read_as = (t.get("names", {}).get(col) or {}).get("tag") if col else None
            sig = (f["value"], f["source"]["kind"], f["source"]["document"], f["context"])
            if sig in r.setdefault("_seen", set()):
                continue
            r["_seen"].add(sig)
            r["values"].append({**f, "read_as": read_as, "source_column": col})
        order = list(CORE)
        out = sorted(rows.values(), key=lambda r: (order.index(r["term"]) if r["term"] in order else 999, r["term"]))
        for r in out:
            r.pop("_seen", None)
            vals = {x["value"].strip().upper() for x in r["values"] if not x["context"]}
            r["conflict"] = len(vals) > 1
        return {"subject": subject, "subject_label": SUBJECT_LABEL.get(subject, subject), "key": key, "view": view,
                "rows": [r for r in out if r["name"] or not view], "not_in_view": [r for r in out if view and not r["name"]]}

    # ------------------------------------------------------------------ reading documents of modelled specifications
    def model_for(self, standard: str, root) -> dict | None:
        """The loaded data model a document is written in: by its schema's standard, else by its tag names."""
        for m in self.models():
            if standard and (m["spec"] or "").upper() == standard.upper().replace(" ", ""):
                return m
        tags = {etree_local(e) for e in root.iter() if isinstance(e.tag, str)}
        best, score = None, 0
        for m in self.models():
            xmls = {c["xml"] for c in m["classes"].values() if c["xml"]}
            s = len(tags & xmls)
            if s > score:
                best, score = m, s
        return best if score >= 3 else None

    def read_document(self, d: dict, root, standard: str = "") -> dict | None:
        m = self.model_for(standard, root)
        if not m:
            return None
        facts = read_document(m, self.vocab, root)
        name = d.get("original_name") or d.get("id") or "document"
        kind = m["spec"]
        for (sid,) in self.db.execute("SELECT id FROM source WHERE kind=? AND document=?", (kind, name)).fetchall():
            self.db.execute("DELETE FROM xr_fact WHERE source_id=?", (sid,))
        sid = self.k.store.source(kind, name, schema=model_label(m), note="read through the data model")
        n = store_document_facts(self.db, facts, sid)
        subjects = len({(f["subject"], f["key"]) for f in facts})
        return {"imported": bool(n), "kind": f"{model_label(m)} (data model)", "facts": n, "items": subjects,
                "reason": "" if n else f"no {model_label(m)} items found in the document"}


def etree_local(e) -> str:
    from lxml import etree
    return etree.QName(e).localname
