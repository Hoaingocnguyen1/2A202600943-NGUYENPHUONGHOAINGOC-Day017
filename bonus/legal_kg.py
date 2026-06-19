"""Bonus prototype — Knowledge graph + point-in-time validity over Vietnamese legal text.

    python bonus/legal_kg.py

This extends the lab's KG track (§13) and its point-in-time track (§11) to the
problem I brainstormed in `bonus/DESIGN.md`: answering legal questions over a
corpus of messy Vietnamese văn bản (Nghị định / Luật / Thông tư).

It demonstrates the ONE core decision the design hinges on, on purpose-dirty data
(`data/nd_giao_thong_sample.md` keeps OCR-like noise, nested Điều→Khoản→Điểm, and
cross-document references):

  1. MULTI-HOP DẪN CHIẾU (why a graph, not flat vector RAG).
     "Xe ô tô tải chạy quá tốc độ 10–20 km/h trong khu đông dân cư bị phạt bao nhiêu?"
     The fine is NOT in the article about trucks. You must walk the reference chain
        Điều 6 k5 (xe tải) --DẪN_CHIẾU--> điểm a khoản 5 Điều 5 (mức phạt)
     No single chunk contains both "xe tải / khu đông dân cư" and the amount, so
     flat chunk retrieval can only ever return half the chain — the lab's vector
     foil, but on real legal structure.

  2. POINT-IN-TIME HIỆU LỰC (why ASOF, not "latest version").
     điểm a khoản 5 Điều 5 was amended by NĐ-168/2024 (in force 2025-01-01). A
     violation on 2024-06-01 must be judged by the version in force THEN, not the
     newest text. Serving the latest version = retroactive heavier penalty = a
     legally WRONG answer (trái nguyên tắc không hồi tố, Điều 156 Luật BHVBQPPL).
     This is exactly the training-serving-skew bug, but where the silent error is
     a citizen over-fined. ASOF on `valid_from <= violation_date` is the fix.

Zero-key, deterministic. The regex extractor stands in for an LLM extractor —
see DESIGN.md for why production needs the LLM + human-curated hiệu lực table.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DOC = HERE / "data" / "nd_giao_thong_sample.md"
HIEU_LUC = HERE / "data" / "hieu_luc.csv"

# Map a văn bản's surface form to a short, canonical document code (entity
# resolution at the document level). A real pipeline does this against a registry.
_DOC_CODES = {
    "100/2019": "NĐ100",
    "168/2024": "NĐ168",
    "23/2008": "Luật23",
}

# One reference, e.g. "điểm a khoản 5 Điều 5", "khoản 11 Điều 5", "Điều 6",
# "điểm c khoản 11 Điều này". Vietnamese order is điểm -> khoản -> Điều.
_REF = re.compile(
    r"(?:điểm\s+([a-zđ])\s+)?(?:khoản\s+(\d+)\s+)?Điều\s+(\d+|này)",
    re.IGNORECASE,
)
# Which văn bản a reference points at (defaults to the current document).
_REF_DOC = re.compile(r"Nghị định\s+(\d+/\d+)|Nghị định\s+(này)", re.IGNORECASE)


def _node(doc: str, dieu: str, khoan: str | None = None, diem: str | None = None) -> str:
    """Canonical node id, e.g. 'NĐ100:đ5.k5.đa'. Granularity = điểm/khoản/điều."""
    nid = f"{doc}:đ{dieu}"
    if khoan:
        nid += f".k{khoan}"
    if diem:
        nid += f".đ{diem}"
    return nid


def _resolve_doc(tail: str, current_doc: str) -> str:
    """Resolve which văn bản a reference tail names; default to the current doc."""
    m = _REF_DOC.search(tail)
    if not m:
        return current_doc
    if m.group(2):                      # "Nghị định này"
        return current_doc
    return _DOC_CODES.get(m.group(1), current_doc)


_MARKER = re.compile(r"^(#|>|---|\*{0,2}Điều\s+\d+\.|\d+\.|[a-zđ]\))")


def _logical_lines(text: str) -> list[str]:
    """Merge wrapped continuation lines back into one logical line per structural
    unit. Scanned legal PDFs wrap mid-sentence (and mid-reference), so a reference
    like 'Điều 5 và Điều 6\\nNghị định 100/2019' is split across raw lines. De-
    wrapping is a standard OCR clean-up step and is what lets a reference see the
    văn bản that qualifies it. A line that starts with a structural marker (#, Điều
    N., khoản digit., điểm letter)) begins a new unit; anything else continues it.
    """
    units: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if units and not _MARKER.match(line):
            units[-1] += " " + line
        else:
            units.append(line)
    return units


def extract_references(text: str) -> list[tuple[str, str, str]]:
    """Scan the corpus and emit (src_node, relation, dst_node) reference edges.

    Tracks the current document/Điều/khoản/điểm as it walks logical lines, so a
    relative reference ('Điều này', 'điểm c khoản 11') resolves to the right source
    node, and an amendment's chapeau ('Sửa đổi … của Nghị định số 100/2019') sets
    the target document for the bare references that follow it. This stateful walk
    over nested, noisy structure is what makes legal extraction genuinely hard —
    and where the deterministic version still falls short of an LLM (see DESIGN.md
    §"phương án bị loại").
    """
    triples: list[tuple[str, str, str]] = []
    doc, dieu, khoan, diem = "NĐ100", None, None, None
    amend_target: str | None = None        # doc that the current "sửa đổi" block edits

    for line in _logical_lines(text):
        low = line.lower()

        # An amendment chapeau names the document being edited -> bare refs in this
        # block default to it, not to the amending decree itself.
        if "sửa đổi" in low:
            for surface, code in _DOC_CODES.items():
                if surface in line and code != doc:
                    amend_target = code

        # --- document context (## ... NĐ-100/2019 ... / Luật ... 23/2008 ...) ---
        if line.startswith("#"):
            for surface, code in _DOC_CODES.items():
                if surface in line:
                    doc, dieu, khoan, diem = code, None, None, None
            continue

        # --- structural markers update the "current source node" ---
        head = re.match(r"\*{0,2}Điều\s+(\d+)\.", line)      # "Điều 5. ..." (definition)
        if head:
            dieu, khoan, diem = head.group(1), None, None
            body = line[head.end():]                          # refs after the heading dot
        else:
            kho = re.match(r"(\d+)\.", line)                 # "5. Phạt tiền ..."  (khoản)
            dim = re.match(r"([a-zđ])\)", line)              # "a) Điều khiển ..." (điểm)
            if kho:
                khoan, diem = kho.group(1), None
                body = line[kho.end():]
            elif dim:
                diem = dim.group(1)
                body = line[dim.end():]
            else:
                body = line

        if dieu is None:
            continue
        src = _node(doc, dieu, khoan, diem)
        is_amend = "sửa đổi" in body.lower()
        rel = "SỬA_ĐỔI" if is_amend else "DẪN_CHIẾU"
        default_doc = amend_target if is_amend and amend_target else doc

        # --- pull every reference out of the line body ---
        for m in _REF.finditer(body):
            r_diem, r_khoan, r_dieu = m.group(1), m.group(2), m.group(3)
            tail = body[m.end(): m.end() + 60]               # look ahead for an explicit văn bản
            r_doc = _resolve_doc(tail, default_doc)
            r_dieu = dieu if r_dieu.lower() == "này" else r_dieu
            dst = _node(r_doc, r_dieu, r_khoan, r_diem)
            if dst != src:                                   # ignore self-reference noise
                triples.append((src, rel, dst))
    # de-dup while preserving order
    seen, out = set(), []
    for t in triples:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_graph(triples: list[tuple[str, str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Adjacency list: node -> [(relation, neighbour), ...]."""
    g: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for s, r, o in triples:
        g[s].append((r, o))
    return dict(g)


def resolve_chain(graph: dict, start: str, max_hops: int = 4) -> list[dict]:
    """BFS the DẪN_CHIẾU edges from `start` to every leaf it ultimately points to.

    A 'leaf' is a node that resolves the question (it has no further DẪN_CHIẾU out-
    edge). For the truck-speeding question this walks
        NĐ100:đ6.k5 -> NĐ100:đ5.k5.đa   (the article that states the fine).
    """
    results: list[dict] = []
    q: deque = deque([(start, [start])])
    seen = {start}
    while q:
        node, path = q.popleft()
        if len(path) > max_hops + 1:
            continue
        outs = [(r, o) for r, o in graph.get(node, []) if r == "DẪN_CHIẾU"]
        if not outs and node != start:
            results.append({"path": path, "hops": len(path) - 1, "target": node})
            continue
        for _, nxt in outs:
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, path + [nxt]))
    return results


def point_in_time_fine(con: duckdb.DuckDBPyConnection, node_id: str, violation_date: str) -> dict | None:
    """ASOF: the fine version in force AT OR BEFORE the violation date — never newer.

    The naive 'latest version' query is shown alongside so the retroactive-penalty
    bug (a legally wrong answer) is visible, exactly like the lab's leaky join.
    """
    con.execute("DROP TABLE IF EXISTS hieu_luc")
    con.execute(
        f"""CREATE TABLE hieu_luc AS
            SELECT node_id, CAST(valid_from AS DATE) AS valid_from, van_ban, muc_phat
            FROM read_csv_auto('{HIEU_LUC.as_posix()}', header=true)"""
    )
    con.execute(
        "CREATE TEMP TABLE q AS SELECT ? AS node_id, CAST(? AS DATE) AS violation_date",
        [node_id, violation_date],
    )
    correct = con.execute(
        """SELECT h.van_ban, h.muc_phat, h.valid_from
           FROM q ASOF LEFT JOIN hieu_luc h
             ON q.node_id = h.node_id AND q.violation_date >= h.valid_from"""
    ).fetchone()
    leaky = con.execute(
        """SELECT van_ban, muc_phat FROM hieu_luc
           WHERE node_id = ? ORDER BY valid_from DESC LIMIT 1""",
        [node_id],
    ).fetchone()
    con.execute("DROP TABLE q")
    if not correct or correct[0] is None:
        return None
    return {
        "node_id": node_id,
        "violation_date": violation_date,
        "asof_van_ban": correct[0], "asof_muc_phat": correct[1], "valid_from": str(correct[2]),
        "leaky_van_ban": leaky[0], "leaky_muc_phat": leaky[1],
        "leaked": (correct[1] != leaky[1]),
    }


def vector_foil(text: str, subject_hint: str, answer_hint: str) -> dict:
    """Why flat chunk RAG loses: subject and answer live in DIFFERENT articles."""
    chunks = [c.strip() for c in re.split(r"(?<=[.;])\s+|\n", text) if c.strip()]
    with_subj = [c for c in chunks if subject_hint.lower() in c.lower()]
    with_ans = [c for c in chunks if answer_hint.lower() in c.lower()]
    both = [c for c in chunks if subject_hint.lower() in c.lower() and answer_hint.lower() in c.lower()]
    return {
        "n_chunks": len(chunks),
        "chunk_with_subject": with_subj[0] if with_subj else None,
        "chunk_with_answer": with_ans[0] if with_ans else None,
        "single_chunk_answers_it": bool(both),
    }


def main() -> dict:
    text = DOC.read_text(encoding="utf-8")
    triples = extract_references(text)
    graph = build_graph(triples)

    print("=== Bonus: Legal KG (Vietnamese) — multi-hop dẫn chiếu + point-in-time hiệu lực ===")
    print(f"  reference edges extracted: {len(triples)} over {len(graph)} source nodes")
    for s, r, o in triples:
        print(f"    ({s}) -[{r}]-> ({o})")

    # --- 1) multi-hop reference resolution (graph wins) ---
    start = "NĐ100:đ6.k5"        # xe ô tô tải, khu đông dân cư
    print(f"\n  Q: mức phạt cho hành vi tại {start} (xe tải quá tốc độ khu đông dân cư)?")
    chains = resolve_chain(graph, start)
    for c in chains:
        print("    " + "  ->  ".join(c["path"]) + f"   ({c['hops']} hops)  => {c['target']}")
    fine_node = chains[0]["target"] if chains else None

    foil = vector_foil(text, "ô tô tải", "đến 8.000.000")
    print("\n  [Vector RAG foil] does any single chunk contain BOTH the truck rule "
          f"and a fine amount? {foil['single_chunk_answers_it']}  "
          "=> flat retrieval cannot bridge the dẫn chiếu")

    # --- 2) point-in-time hiệu lực (ASOF wins) ---
    con = duckdb.connect(":memory:")
    try:
        for date in ("2024-06-01", "2025-03-01"):
            pit = point_in_time_fine(con, fine_node, date)
            print(f"\n  Vi phạm ngày {date} tại {fine_node}:")
            print(f"    [ASOF đúng ] {pit['asof_muc_phat']}  ({pit['asof_van_ban']}, hiệu lực {pit['valid_from']})")
            print(f"    [latest sai] {pit['leaky_muc_phat']}  ({pit['leaky_van_ban']})"
                  f"   {'<-- HỒI TỐ: phạt nặng hơn luật thời điểm vi phạm!' if pit['leaked'] else ''}")
    finally:
        con.close()

    return {
        "n_edges": len(triples),
        "multihop_target": fine_node,
        "multihop_hops": chains[0]["hops"] if chains else 0,
        "single_chunk_answers_it": foil["single_chunk_answers_it"],
    }


if __name__ == "__main__":
    main()
