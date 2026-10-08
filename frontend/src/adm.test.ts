import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ataNumber, applyTextEdits, headerInfo, refLabel, displayText, editText, setEntityValues, diagRange, inlineLabel, leafDescendants, expandsEntities, renderTarget, setTextContent, parseAdm, readablePath, resolvePath, setAttributeValue, toProseMirror, kindOf, elementAtOffset, lineAt } from "./adm";

const fx = (n: string) => readFileSync(`../backend/tests/fixtures/documents/${n}`, "utf-8");

describe("ADM", () => {
  it("maps every element and keeps spans exact", () => {
    for (const f of ["s1000d_descript_valid.xml", "s1000d_proced_valid.xml", "s1000d_ipd_valid.xml", "s2000m_provisioning_valid.xml", "s3000l_lsa_valid.xml"]) {
      const a = parseAdm(fx(f));
      expect(a.ok, f).toBe(true);
      expect(a.visualBlocked, f).toBeUndefined();
      a.elements.forEach((el, k) => {
        const s = a.spans[k];
        expect(a.text.slice(s.start + 1).startsWith(s.qname), f).toBe(true);
        expect(s.qname.split(":").pop()).toBe(el.localName);
      });
    }
  });

  it("reports parse errors; DOCTYPE entities stay editable and are never expanded into the source", () => {
    expect(parseAdm("<a><b></a>").ok).toBe(false);
    const src = '<!DOCTYPE a [<!ENTITY co "ACME">]><a><p>by &co; today</p></a>';
    const x = parseAdm(src);
    expect(x.ok && !x.visualBlocked).toBe(true);
    const p = x.elements.findIndex((e) => e.localName === "p");
    expect(applyTextEdits(x, new Map([[p, [{ kind: "text", text: "by " }, { kind: "atom", raw: "&co;" }, { kind: "text", text: " now" }]]])))
      .toBe(src.replace("today", "now"));
  });
  it("documents importing the ISO entity sets through a parameter entity stay editable", () => {
    const iso = '<?xml version="1.0"?>\n<!DOCTYPE dmodule [\n<!ENTITY % ISOEntities PUBLIC "ISO 8879-1986//ENTITIES ISO Character Entities 20030531//EN//XML" "http://www.s1000d.org/S1000D_4-1/ent/ISOEntities">\n%ISOEntities;\n]>\n<dmodule><para>20&deg;C</para></dmodule>';
    const a = parseAdm(iso);
    expect(a.ok && !a.visualBlocked).toBe(true);
    expect(JSON.stringify(toProseMirror(a))).toContain('"raw":"&deg;"');
  });

  it("resolves the same readable paths the backend emits", () => {
    const a = parseAdm(fx("s1000d_proced_valid.xml"));
    const k = resolvePath(a, "/dmodule/content/procedure/mainProcedure/proceduralStep[2]/caution")!;
    expect(a.elements[k].localName).toBe("caution");
    expect(readablePath(a.elements[k])).toBe("/dmodule/content/procedure/mainProcedure/proceduralStep[2]/caution");
    const b = parseAdm(fx("s2000m_provisioning_valid.xml"));
    expect(b.elements[resolvePath(b, "/provisioningExchange/ipdRecords/ipdItem[2]/quantityPerAssembly")!].textContent).toBe("4");
  });

  it("classifies text, container and atom elements", () => {
    const a = parseAdm(fx("s1000d_descript_valid.xml"));
    const by = (n: string) => a.elements.find((e) => e.localName === n)!;
    expect(kindOf(by("para"))).toBe("text");
    expect(kindOf(by("levelledPara"))).toBe("block");
    expect(kindOf(by("dmCode"))).toBe("atom");
    const pm = toProseMirror(a);
    expect(pm.content[0].attrs.name).toBe("dmodule");
    expect(JSON.stringify(pm)).toContain('"type":"xinline"');     // internalRef inside para
  });

  it("text edits splice only the edited element; everything else byte-identical", () => {
    const src = fx("s1000d_descript_valid.xml");
    const a = parseAdm(src);
    const para = a.elements.findIndex((e) => e.localName === "para");
    const ref = a.elements.findIndex((e) => e.localName === "internalRef");
    const s = a.spans[ref];
    const out = applyTextEdits(a, new Map([[para, [
      { kind: "text", text: "Gear & strut <support> the aircraft. See " },
      { kind: "atom", raw: src.slice(s.start, s.end) },
      { kind: "text", text: "." },
    ]]]));
    const ps = a.spans[para];
    expect(out.slice(0, ps.tagEnd)).toBe(src.slice(0, ps.tagEnd));
    expect(out.slice(out.length - (src.length - ps.contentEnd))).toBe(src.slice(ps.contentEnd));
    expect(out).toContain("Gear &amp; strut &lt;support&gt; the aircraft. See <internalRef internalRefId=\"fig-0001\"/>.");
    const b = parseAdm(out);
    expect(b.ok).toBe(true);
    expect(b.elements.length).toBe(a.elements.length);            // structure (and nids) unchanged
  });

  it("marks round-trip with their original start tags", () => {
    const src = `<?xml version="1.0"?>\n<doc>\n  <para>Press <emphasis   type='x'>firmly</emphasis> now</para>\n</doc>\n`;
    const a = parseAdm(src);
    const para = a.elements.findIndex((e) => e.localName === "para");
    const em = a.elements.findIndex((e) => e.localName === "emphasis");
    const out = applyTextEdits(a, new Map([[para, [
      { kind: "text", text: "Press " }, { kind: "text", text: "very firmly", mark: em }, { kind: "text", text: " now" }]]]));
    expect(out).toBe(src.replace(">firmly<", ">very firmly<"));
  });

  it("editing a self-closing empty element expands it", () => {
    const src = `<doc>\n  <para/>\n</doc>`;
    const a = parseAdm(src);
    expect(applyTextEdits(a, new Map([[1, [{ kind: "text", text: "Hello" }]]]))).toBe(`<doc>\n  <para>Hello</para>\n</doc>`);
  });

  it("attribute edits keep quote style and the rest of the tag", () => {
    const src = `<doc>\n  <part  id='p1'\n     cage="ZZ001"/>\n</doc>`;
    const a = parseAdm(src);
    expect(setAttributeValue(a, 1, "cage", 'A"B')).toBe(src.replace('cage="ZZ001"', 'cage="A&quot;B"'));
    expect(setAttributeValue(a, 1, "id", "p2")).toBe(src.replace("id='p1'", "id='p2'"));
  });

  it("maps source offsets back to elements", () => {
    const src = fx("s1000d_proced_valid.xml");
    const a = parseAdm(src);
    const off = src.indexOf("Remove the access panel");
    expect(a.elements[elementAtOffset(a, off)!].localName).toBe("para");
    expect(lineAt(src, off)).toBeGreaterThan(10);
  });

  it("preserves comments and CDATA inside textblocks as raw atoms", () => {
    const src = `<doc><para>A <!-- keep --> B <![CDATA[<x>]]> C</para></doc>`;
    const a = parseAdm(src);
    expect(a.visualBlocked).toBeUndefined();
    const pm = toProseMirror(a);
    const inl = pm.content[0].content[0].content.filter((n: any) => n.type === "xinline").map((n: any) => n.attrs.raw);
    expect(inl).toEqual(["<!-- keep -->", "<![CDATA[<x>]]>"]);
  });
});


describe("diagnostic ranges and fixes", () => {
  const src = `<doc>\n  <para>Torque to <quantity><quantityGroup><quantityValue quantityUnitOfMeasure="Mpa">0,5</quantityValue></quantityGroup></quantity>.</para>\n  <issueInfo issueNumber='1'/>\n</doc>`;
  it("underlines exactly the attribute value or element text", () => {
    const a = parseAdm(src);
    const p = "/doc/para/quantity/quantityGroup/quantityValue";
    const r1 = diagRange(a, { element_path: p, attribute: "quantityUnitOfMeasure", value: "Mpa" })!;
    expect(src.slice(r1.start, r1.end)).toBe("Mpa");
    const r2 = diagRange(a, { element_path: p, value: "0,5" })!;
    expect(src.slice(r2.start, r2.end)).toBe("0,5");
    const r3 = diagRange(a, { element_path: "/doc/issueInfo", attribute: "inWork" })!;   // missing attribute -> element name
    expect(src.slice(r3.start, r3.end)).toBe("issueInfo");
  });
  it("applies text and attribute fixes without touching anything else", () => {
    const a = parseAdm(src);
    const k = a.elements.findIndex((e) => e.localName === "quantityValue");
    expect(setTextContent(a, k, "0.5")).toBe(src.replace(">0,5<", ">0.5<"));
    const i = a.elements.findIndex((e) => e.localName === "issueInfo");
    expect(setAttributeValue(a, i, "issueNumber", "001")).toBe(src.replace("'1'", "'001'"));
  });
  it("maps elements inside inline chips to the chip in the visual view", () => {
    const a = parseAdm(src);
    const qv = a.elements.findIndex((e) => e.localName === "quantityValue");
    expect(a.elements[renderTarget(a, qv)].localName).toBe("quantity");
  });
  it("allows S1000D ICN declarations but not text entities", () => {
    expect(expandsEntities('<!NOTATION cgm SYSTEM "cgm"><!ENTITY ICN-A SYSTEM "ICN-A.cgm" NDATA cgm>')).toBe(false);
    expect(expandsEntities('<!ENTITY co "ACME Corp">')).toBe(true);
    expect(expandsEntities('<!ENTITY % ext SYSTEM "x.ent">')).toBe(true);
    const doc = parseAdm('<?xml version="1.0"?>\n<!DOCTYPE d [\n<!NOTATION cgm SYSTEM "cgm">\n<!ENTITY ICN-A SYSTEM "ICN-A.cgm" NDATA cgm>\n]>\n<d><graphic infoEntityIdent="ICN-A"/></d>');
    expect(doc.ok).toBe(true);
    expect(doc.visualBlocked).toBeUndefined();
  });
});


describe("inline chips", () => {
  it("show real values instead of the element name", () => {
    const a = parseAdm(`<p>up to <quantity><quantityGroup><quantityValue quantityUnitOfMeasure="in">0.030</quantityValue><quantityTolerance quantityToleranceType="plusorminus">0.005</quantityTolerance></quantityGroup><quantityGroup><quantityValue quantityUnitOfMeasure="mm">0.76</quantityValue></quantityGroup></quantity> and <acronym><acronymTerm>LPT</acronymTerm><acronymDefinition>Low Pressure Turbine</acronymDefinition></acronym> <internalRef internalRefId="fig-0001"/></p>`);
    const by = (n: string) => a.elements.find((e) => e.localName === n)!;
    expect(inlineLabel(by("quantity"))).toBe("0.030 in ±0.005 / 0.76 mm");
    expect(inlineLabel(by("acronym"))).toBe("LPT");
    expect(inlineLabel(by("internalRef"))).toBe("fig-0001");          // target not in this snippet
    const b = parseAdm(`<para>Torque to <torque unit="lbf.in">45</torque>. See <refint refid="T-001"/>.</para>`);
    expect(inlineLabel(b.elements.find((e) => e.localName === "torque")!)).toBe("45 lbf.in");
    expect(inlineLabel(b.elements.find((e) => e.localName === "refint")!)).toBe("T-001");
    const q = a.elements.indexOf(by("quantity"));
    expect(leafDescendants(a, q).map((k) => a.elements[k].localName)).toEqual(["quantityValue", "quantityTolerance", "quantityValue"]);
  });
});


describe("named entities (DTD-based documents)", () => {
  const src = `<?xml version="1.0"?>\n<!DOCTYPE cmm PUBLIC "-//X//DTD CMM//EN" "cmm.dtd">\n<cmm model="A&mdash;B"><para>Heat to 120&deg;F &amp; hold</para></cmm>`;
  it("parses, shows entities as chips and writes them back unchanged", () => {
    setEntityValues({ deg: "\u00b0", mdash: "\u2014" });
    const a = parseAdm(src);
    expect(a.ok).toBe(true);
    expect(a.visualBlocked).toBeUndefined();
    const para = a.elements.findIndex((e) => e.localName === "para");
    const pm = toProseMirror(a);
    const inl = JSON.stringify(pm);
    expect(inl).toContain('"raw":"&deg;"');
    expect(inl).toContain('"summary":"\u00b0"');
    // a visual text edit keeps the entity reference and escapes the literal ampersand
    const out = applyTextEdits(a, new Map([[para, [
      { kind: "text", text: "Heat to 125" }, { kind: "atom", raw: "&deg;" }, { kind: "text", text: "F & hold" }]]]));
    expect(out).toBe(src.replace("120&deg;F", "125&deg;F"));
    // attribute values display the character, edit as the reference
    const cmm = a.elements[0];
    expect(displayText(cmm.getAttribute("model")!, a.doc)).toBe("A\u2014B");
    expect(editText(cmm.getAttribute("model")!, a.doc)).toBe("A&mdash;B");
    expect(setAttributeValue(a, 0, "model", "A&mdash;C")).toBe(src.replace("A&mdash;B", "A&mdash;C"));
  });
  it("leaves documents without a DOCTYPE alone (entities there are a real error)", () => {
    expect(parseAdm("<cmm><para>&mdash;</para></cmm>").ok).toBe(false);
  });
});


describe("publication view data", () => {
  it("numbers figures and tables and labels references by them", () => {
    const a = parseAdm(fx("s1000d_descript_valid.xml"));
    expect(refLabel(a.doc, "fig-0001")).toBe("Figure 1");
    const ref = a.elements.find((e) => e.localName === "internalRef")!;
    expect(inlineLabel(ref)).toBe("Figure 1");
  });
  it("reads the S1000D title block", () => {
    const h = headerInfo(parseAdm(fx("s1000d_proced_valid.xml")))!;
    expect(h.kind).toBe("s1000d");
    expect(h.code).toBe("DMC-ASTHRA-A-32-10-00-00A-520A-A");
    expect(h.issue).toBe("Issue 001-00");
    expect(h.title).toBe("Main landing gear");
    expect(h.applic).toBe("All synthetic test aircraft");
  });
  it("reads an ATA title block and labels task references by title", () => {
    const src = fx("ata_cmm_nodoctype.xml");
    const a = parseAdm(src);
    const h = headerInfo(a)!;
    expect(h.kind).toBe("ata");
    expect(h.code).toBe("29-10-41");
    expect(h.subtitle).toBe("Model SYN-PUMP-1");
    expect(refLabel(a.doc, "T-001")).toBe("Remove the pump cover");
    expect(refLabel(a.doc, "TAB-1")).toBe("Table 1");
  });
});

import { addAttribute, deleteElement, insertChild, moveElement, removeAttribute, xmlToSgml, childElements } from "./adm";

describe("structural edits", () => {
  const src = `<doc>\n  <step>\n    <para>One</para>\n    <para>Two</para>\n  </step>\n  <empty/>\n</doc>\n`;
  const a = parseAdm(src);
  const step = a.elements.findIndex((e) => e.localName === "step");
  it("inserts with the surrounding indentation", () => {
    const [t1] = insertChild(a, step, 1, "<note/>");
    expect(t1).toBe(src.replace("<para>One</para>\n", "<para>One</para>\n    <note/>\n"));
    const [t2] = insertChild(a, step, 2, "<figure/>");
    expect(t2).toBe(src.replace("<para>Two</para>\n", "<para>Two</para>\n    <figure/>\n"));
    const emp = a.elements.findIndex((e) => e.localName === "empty");
    expect(insertChild(a, emp, 0, "<x/>")[0]).toContain("<empty><x/></empty>");
    expect(parseAdm(t1).ok && parseAdm(t2).ok).toBe(true);
  });
  it("deletes the element and its line", () => {
    const p2 = childElements(a, step)[1];
    expect(deleteElement(a, p2)).toBe(src.replace("    <para>Two</para>\n", ""));
  });
  it("moves elements past their sibling", () => {
    const p1 = childElements(a, step)[0];
    expect(moveElement(a, p1, 1)).toBe(src.replace("<para>One</para>\n    <para>Two</para>", "<para>Two</para>\n    <para>One</para>"));
    expect(moveElement(a, p1, -1)).toBeNull();
  });
  it("adds and removes attributes, keeping the rest of the tag", () => {
    const emp = a.elements.findIndex((e) => e.localName === "empty");
    const t = addAttribute(a, emp, "id", "e-1");
    expect(t).toContain('<empty id="e-1"/>');
    expect(addAttribute(a, step, "key", "a&b")).toContain('<step key="a&amp;b">');
    expect(removeAttribute(parseAdm(t), emp, "id")).toBe(src);
  });
});

describe("SGML write-back", () => {
  it("keeps the SGML DOCTYPE, writes EMPTY elements without end tags, keeps entity references", () => {
    const sgml = `<!DOCTYPE CMM PUBLIC "-//X//DTD CMM//EN">\n<CMM CHAPNBR=29><TITLE>Pump &mdash; A\n<PARA>Heat to 20&deg;C. See <REFINT REFID=T1>\n</CMM>\n`;
    const view = `<?xml version="1.0"?>\n<!DOCTYPE cmm [<!ENTITY mdash "\u2014"><!ENTITY deg "\u00b0">]><cmm chapnbr="29"><title>Pump &mdash; A</title><para>Heat to 20&deg;C. See <refint refid="t1"/></para><note/></cmm>`;
    const out = xmlToSgml(parseAdm(view), sgml, new Set(["refint"]));
    expect(out.startsWith('<!DOCTYPE CMM PUBLIC "-//X//DTD CMM//EN">\n<cmm chapnbr="29">')).toBe(true);
    expect(out).toContain('<refint refid="t1"></para>');        // EMPTY: no end tag, no "/>"
    expect(out).toContain("<note></note>");                      // not EMPTY: explicit end tag
    expect(out).toContain("&mdash;") ; expect(out).toContain("&deg;");
    expect(out).not.toContain("/>");
    expect(out).toMatch(/\n  <title>/);                          // element-only content, one per line
  });
});

import { calsTable, localName, nextCell, tableAddColumn, tableAddRow, tableContext, tableDeleteColumn, tableDeleteRow, tidy } from "./adm";

describe("tables", () => {
  const src = `<doc><table><tgroup cols="2"><colspec colname="col1"/><colspec colname="col2"/>` +
    `<thead><row><entry>A</entry><entry>B</entry></row></thead>` +
    `<tbody><row><entry>1</entry><entry>2</entry></row></tbody></tgroup></table></doc>`;
  const a = parseAdm(src);
  const cell = (txt: string) => a.elements.findIndex((e) => localName(e) === "entry" && e.textContent === txt);
  it("finds the table position of a cell", () => {
    const c = tableContext(a, cell("2"))!;
    expect(c.col).toBe(1);
    expect(c.rows.length).toBe(2);
    expect(nextCell(a, c, -1)).toBe(cell("1"));
    expect(nextCell(a, c, 1)).toBeNull();
  });
  it("adds a row with the same cells", () => {
    const [t] = tableAddRow(a, tableContext(a, cell("1"))!, "<entry></entry>");
    expect(t).toContain("<row><entry>1</entry><entry>2</entry></row><row><entry></entry><entry></entry></row></tbody>");
  });
  it("adds a column in every row and updates cols and colspec", () => {
    const t = tableAddColumn(a, tableContext(a, cell("1"))!, "<entry></entry>");
    expect(t).toContain('<tgroup cols="3">');
    expect(t).toContain('<colspec colname="col1"/><colspec colname="col3"/><colspec colname="col2"/>');
    expect(t).toContain("<entry>A</entry><entry></entry><entry>B</entry>");
    expect(t).toContain("<entry>1</entry><entry></entry><entry>2</entry>");
    expect(parseAdm(t).ok).toBe(true);
  });
  it("deletes a column and a row", () => {
    const t = tableDeleteColumn(a, tableContext(a, cell("B"))!);
    expect(t).toContain('<tgroup cols="1"><colspec colname="col1"/><thead><row><entry>A</entry></row>');
    expect(() => tableDeleteRow(a, tableContext(a, cell("1"))!)).toThrow(/only row/);
  });
  it("refuses column edits on merged cells", () => {
    const m = parseAdm(src.replace("<entry>A</entry><entry>B</entry>", '<entry namest="col1" nameend="col2">AB</entry>'));
    const k = m.elements.findIndex((e) => localName(e) === "entry" && e.textContent === "1");
    expect(() => tableAddColumn(m, tableContext(m, k)!, "<entry/>")).toThrow(/merged/);
  });
  it("builds a CALS table", () => {
    const x = calsTable('<table id="t1">', "</table>", { title: true, colspec: true, head: true, rows: 2, cols: 3 }, "<entry></entry>");
    const t = parseAdm(`<doc>${x}</doc>`);
    expect(t.ok).toBe(true);
    expect(t.elements.filter((e) => localName(e) === "entry").length).toBe(9);
    expect(x).toContain('<tgroup cols="3"><colspec colname="col1"/>');
  });
});

describe("tidy source", () => {
  it("indents structure and never touches text", () => {
    const src = `<doc><step><para>Keep  this   text <b>as</b> is</para><para>Two</para></step></doc>`;
    const out = tidy(parseAdm(src));
    expect(out).toBe(`<doc>\n  <step>\n    <para>Keep  this   text <b>as</b> is</para>\n    <para>Two</para>\n  </step>\n</doc>`);
    expect(tidy(parseAdm(out))).toBe(out);                 // idempotent
  });
});

describe("CALS table layout", () => {
  const tg = (xml: string) => new DOMParser().parseFromString(xml, "application/xml").documentElement;
  it("places merged and spanned-down cells exactly, numbering thead and tbody on one grid", async () => {
    const { calsLayout } = await import("./adm");
    const t = tg(`<tgroup cols="4">
      <colspec colname="c1" colwidth="1*"/><colspec colname="c2" colwidth="2*"/><colspec colname="c3"/><colspec colname="c4"/>
      <thead>
        <row><entry morerows="1">Ref</entry><entry namest="c2" nameend="c3">Limits</entry><entry morerows="1">Wear</entry></row>
        <row><entry>Min</entry><entry>Max</entry></row>
      </thead>
      <tbody><row><entry>A</entry><entry>1</entry><entry>2</entry><entry>3</entry></row></tbody></tgroup>`);
    const l = calsLayout(t);
    const at = (txt: string) => { for (const [e, p] of l.cells) if (e.textContent === txt) return p; throw new Error(txt); };
    expect(l.cols).toBe(4);
    expect(at("Ref")).toMatchObject({ row: 1, col: 1, rowSpan: 2, colSpan: 1, head: true });
    expect(at("Limits")).toMatchObject({ row: 1, col: 2, colSpan: 2 });
    expect(at("Wear")).toMatchObject({ col: 4, rowSpan: 2 });
    expect(at("Min")).toMatchObject({ row: 2, col: 2, headEnd: true });     // pushed past the cell spanning down
    expect(at("Max")).toMatchObject({ row: 2, col: 3 });
    expect(at("A")).toMatchObject({ row: 3, col: 1, head: false });
    expect(l.template).toBe("minmax(min-content, 1fr) minmax(min-content, 2fr) minmax(min-content, 1fr) minmax(min-content, 1fr)");
  });
  it("uses absolute colwidths as proportions and spanspec spans", async () => {
    const { calsLayout } = await import("./adm");
    const l = calsLayout(tg(`<tgroup cols="2"><colspec colname="a" colwidth="20mm"/><colspec colname="b" colwidth="60mm"/>
      <spanspec spanname="all" namest="a" nameend="b"/><tbody><row><entry spanname="all">x</entry></row></tbody></tgroup>`));
    expect([...l.cells.values()][0]).toMatchObject({ col: 1, colSpan: 2 });
    expect(l.template).toBe("minmax(min-content, 20fr) minmax(min-content, 60fr)");
  });
});

describe("publication numbering and display data", () => {
  const ATA = { numbering: { scheme: "ata" as const, elements: ["task", "subtask", "prcitem1", "prcitem2", "prcitem3"], resets: ["pgblk"],
    ident: { task: "TASK", subtask: "SUBTASK" } } };
  const nodes = (pm: any, name: string): any[] => {
    const out: any[] = [];
    const walk = (n: any) => { if (n.attrs?.name === name) out.push(n); (n.content ?? []).forEach(walk); };
    walk(pm);
    return out;
  };
  const cmm = `<cmm><pgblk><title>DISASSEMBLY</title>
    <task chapnbr="25" sectnbr="26" subjnbr="62" func="040" seq="1" confltr="a" varnbr="1"><title>General</title><topic>
      <subtask chapnbr="25" sectnbr="26" subjnbr="62" func="040" seq="2" confltr="A" varnbr="1"><title>Remove</title><prclist1>
        <prcitem1><prcitem><para>First</para></prcitem><prclist2><prcitem2><prcitem><para>Sub</para></prcitem></prcitem2></prclist2></prcitem1>
        <prcitem1><prcitem><caution><para>be careful</para></caution><para>Second <revst/>changed<revend/></para></prcitem></prcitem1>
      </prclist1></subtask></topic></task>
    <task chapnbr="25" sectnbr="26" subjnbr="62" seq="3" varnbr="1"><title>Next</title><topic><prclist1><prcitem1><prcitem><para>Only</para></prcitem></prcitem1></prclist1></topic></task>
  </pgblk><pgblk><title>REPAIR</title><task chapnbr="25" sectnbr="26" subjnbr="62" seq="9" varnbr="1"><title>Again</title><topic><prclist1>
    <prcitem1><prcitem><para>x</para></prcitem></prcitem1></prclist1></topic></task></pgblk></cmm>`;

  it("numbers ATA tasks, subtasks and procedure items by level (1. A. (1) (a)) and restarts per page block", () => {
    const pm = toProseMirror(parseAdm(cmm), ATA);
    expect(nodes(pm, "task").map((n) => n.attrs.x.num)).toEqual(["1.", "2.", "1."]);
    expect(nodes(pm, "subtask")[0].attrs.x.num).toBe("A.");
    expect(nodes(pm, "prcitem1").map((n) => n.attrs.x.num)).toEqual(["(1)", "(2)", "A.", "A."]);
    expect(nodes(pm, "prcitem2")[0].attrs.x.num).toBe("(a)");
  });

  it("gives ATA task and subtask identifier lines", () => {
    const pm = toProseMirror(parseAdm(cmm), ATA);
    expect(nodes(pm, "task")[0].attrs.x.ident).toBe("TASK 25-26-62-040-001-A01");
    expect(nodes(pm, "subtask")[0].attrs.x.ident).toBe("SUBTASK 25-26-62-040-002-A01");
  });

  it("puts the number of a step that opens with a caution on its first paragraph", () => {
    const pm = toProseMirror(parseAdm(cmm), ATA);
    const second = nodes(pm, "prcitem1")[1];
    expect(second.attrs.x.nl).toBe("1");
    expect(nodes(second, "para").find((p: any) => p.attrs.x.lead)?.attrs.x.lead).toBe("(2)");
  });

  it("marks text between revst and revend for a revision bar and never shows the marks as text", () => {
    const pm = toProseMirror(parseAdm(cmm), ATA);
    const changed = nodes(pm, "para").filter((p) => p.attrs.x.chg);
    expect(changed).toHaveLength(1);
    expect(changed[0].attrs.x.chg).toBe("a3");
    expect(JSON.stringify(changed[0].content)).not.toContain('"text":"revst');
  });

  it("numbers S1000D levelled paragraphs and steps decimally", () => {
    const s = `<dmodule><content><description><levelledPara><title>A</title><levelledPara><title>B</title></levelledPara>
      <levelledPara><title>C</title></levelledPara></levelledPara><levelledPara><title>D</title></levelledPara></description></content></dmodule>`;
    const pm = toProseMirror(parseAdm(s), { numbering: { scheme: "decimal", elements: ["levelledPara", "proceduralStep"] } });
    expect(nodes(pm, "levelledPara").map((n) => n.attrs.x.num)).toEqual(["1", "1.1", "1.2", "2"]);
  });

  it("shows source line breaks and indentation as single spaces", () => {
    const pm = toProseMirror(parseAdm(`<doc><para>
        one
           two <b>three</b>  four
      </para></doc>`));
    const t = nodes(pm, "para")[0].content.map((c: any) => c.text).join("");
    expect(t).toBe("one two three four");
  });

  it("does not repeat the word before a reference (Table <refint/> reads Table 9)", () => {
    const pm = toProseMirror(parseAdm(`<doc><table id="t9"><title>Fits</title></table><para>Refer to Table <refint refid="t9"/>.</para></doc>`));
    const ref = nodes(pm, "refint")[0];
    expect(ref.attrs.summary.toLowerCase().startsWith("table")).toBe(false);
  });

  it("ATA numbering labels", () => {
    expect([0, 1, 2, 3, 4, 5, 6].map((d) => ataNumber(d, 3))).toEqual(["3.", "C.", "(3)", "(c)", "3", "c", "(iii)"]);
    expect(ataNumber(1, 27)).toBe("AA.");
  });
});
