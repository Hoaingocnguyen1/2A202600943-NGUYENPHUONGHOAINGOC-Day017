"""Extension #2 — LLM-based KG triple extraction + entity resolution.

The lab's kg.py uses a deterministic regex extractor (zero-key, reproducible). This
swaps in an LLM extractor (Claude) for the hard cases regex can't reach — natural-
language references, paraphrase, implicit relations — then runs entity resolution
to collapse surface forms. The downstream graph code (build_graph, traverse) is
unchanged: that substitutability is the whole lesson (README ext. #2, deck §13).

Design for the zero-key lab:
  * extract_triples_llm() calls Claude with structured outputs (a json_schema), so
    the model returns clean, validated (subject, relation, object) triples — no
    brittle response parsing. Inject a client in tests to run it offline.
  * resolve_entities() is a pure function (canonicalize + alias-merge) and carries
    the real value an LLM extractor needs: "widgets"/"the Widget"/"WIDGET" → one node.
  * main() uses the LLM only if ANTHROPIC_API_KEY is set; otherwise it falls back to
    the deterministic extractor so the demo still runs with zero keys.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.kg import build_graph, query  # reused unchanged — the point of ext #2

MODEL = "claude-opus-4-8"

# Structured-output contract: the LLM must return exactly this shape.
_TRIPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "triples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "relation": {"type": "string"},
                    "object": {"type": "string"},
                },
                "required": ["subject", "relation", "object"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["triples"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You extract a knowledge graph from text as (subject, relation, object) triples. "
    "Relations are SCREAMING_SNAKE_CASE verbs (e.g. RETURNABLE_WITHIN, IS_A, SHIPS_FROM). "
    "Prefer entity->entity edges that make the graph traversable for multi-hop questions. "
    "Return only triples grounded in the text."
)


def extract_triples_llm(text: str, client=None, model: str = MODEL) -> list[tuple[str, str, str]]:
    """Extract triples with Claude via structured outputs. Pass a client to test offline."""
    if client is None:
        import anthropic  # imported lazily so the module loads without the SDK installed

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _TRIPLE_SCHEMA}},
        messages=[{"role": "user", "content": f"Extract triples from:\n\n{text}"}],
    )
    raw = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(raw)
    return [(t["subject"], t["relation"], t["object"]) for t in data["triples"]]


def resolve_entities(
    triples: list[tuple[str, str, str]], aliases: dict[str, str] | None = None
) -> list[tuple[str, str, str]]:
    """Entity resolution: collapse surface forms to one canonical node.

    Lowercase, strip articles (the/a/an/các/những/một), de-pluralize simple cases,
    then apply an explicit alias map. Without this, an LLM's free-form output leaves
    'widgets', 'the widget', and 'Widget' as three disconnected nodes — and the
    graph never connects. This is the half of ext #2 that matters most.
    """
    aliases = aliases or {}

    def canon(e: str) -> str:
        e = re.sub(r"^(the|a|an|các|những|một)\s+", "", e.strip().lower()).strip(" .")
        if e.endswith("s") and not e.endswith("ss"):
            e = e[:-1]
        return aliases.get(e, e)

    out, seen = [], set()
    for s, r, o in triples:
        t = (canon(s), r.strip().upper().replace(" ", "_"), canon(o))
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main() -> dict:
    from pipeline import config

    doc = (config.DOCS_DIR / "catalog.md").read_text(encoding="utf-8") + "\n" + \
          (config.DOCS_DIR / "sample.md").read_text(encoding="utf-8")

    if os.getenv("ANTHROPIC_API_KEY"):
        print(f"=== Ext #2: LLM KG extraction ({MODEL}) ===")
        triples = extract_triples_llm(doc)
        source = "LLM"
    else:
        from pipeline.kg import extract_triples
        print("=== Ext #2: LLM KG extraction (no ANTHROPIC_API_KEY -> deterministic fallback) ===")
        triples = extract_triples(doc)
        source = "regex fallback"

    resolved = resolve_entities(triples)
    graph = build_graph(resolved)
    print(f"  extractor          : {source}")
    print(f"  triples (raw->resolved): {len(triples)} -> {len(resolved)}")
    print(f"  graph nodes        : {len(graph)}")
    for s, r, o in resolved:
        print(f"    ({s}) -[{r}]-> ({o})")
    return {"source": source, "n_triples": len(resolved), "n_nodes": len(graph)}


if __name__ == "__main__":
    main()
