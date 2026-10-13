r"""Chinese knowledge-graph extraction for semantica (CPU only, no LLM).

Library use (from the project root):

    import sys; sys.path.insert(0, "scratch")
    import zh_semantica

    graph = zh_semantica.build_context_graph({"case-A7291": text_a, "news": text_b})
    graph.save_to_file("graph.json")                 # open it in the Explorer

    kg = zh_semantica.build_kg(text)                  # semantica GraphBuilder dict, for RDF / graph stores

    zh_semantica.register()                           # or use semantica's own extractors directly:
    NamedEntityRecognizer(method="zh_ckip"); RelationExtractor(method="zh_rules")

Command line:

    python scratch\zh_semantica.py doc1.txt doc2.txt --out graph.json [--ttl kg.ttl]

Two ways to a graph:
  build_context_graph  semantica ContextGraph. Entity relations become edges, amounts, rates and
                       dates become node properties, every edge carries rule / evidence / how its
                       subject was resolved / source document. Never adds co-occurrence edges.
  build_kg             semantica GraphBuilder output (entities + relationships dicts), which RDF
                       export and the graph stores accept. GraphBuilder turns values into nodes, and
                       RelationExtractor adds "related_to" co-occurrence edges whenever the rules
                       find nothing; build_kg drops those edges.

NER model ckiplab/bert-base-chinese-ner is GPL-3.0; pass ner_model= to swap it. ZhNER decodes both
BIES and BIO token tags and keeps OntoNotes PERSON/ORG/GPE/LOC; models with other label sets need a
label map (see zh_ner_eval.py for the model comparison).
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zh_extract import ExtractedRelation, ZhNER, ZhRelationExtractor, to_context_graph  # noqa: E402

ENTITY_METHOD = "zh_ckip"
RELATION_METHOD = "zh_rules"
DEFAULT_NER_MODEL = "ckiplab/bert-base-chinese-ner"

Docs = Union[str, Iterable[str], Dict[str, str]]

_ner: Dict[str, ZhNER] = {}
_relations = ZhRelationExtractor()


def get_ner(model: str = DEFAULT_NER_MODEL) -> ZhNER:
    """Load the NER model once per process."""
    if model not in _ner:
        _ner[model] = ZhNER(model)
    return _ner[model]


def _as_docs(docs: Docs) -> List[Tuple[Optional[str], str]]:
    if isinstance(docs, str):
        return [(None, docs)]
    if isinstance(docs, dict):
        return list(docs.items())
    return [(f"doc{i}", d) for i, d in enumerate(docs)]


# ---------------------------------------------------------------------------- extraction

def extract(text: str, ner_model: str = DEFAULT_NER_MODEL,
            source: Optional[str] = None) -> Tuple[List[ExtractedRelation], Dict[str, str]]:
    """Extract relations/attributes from one document.

    Coreference state (topic, 申请人 role, aliases) is per document, so pass
    documents separately rather than concatenated.
    Returns (relations, {entity name: PER|ORG|LOC}).
    """
    relations, entity_types = _relations.extract(text, get_ner(ner_model)(text))
    for r in relations:
        r.source = source
    return relations, entity_types


def build_context_graph(docs: Docs, ner_model: str = DEFAULT_NER_MODEL):
    """Build one semantica ContextGraph from one or more documents."""
    relations: List[ExtractedRelation] = []
    entity_types: Dict[str, str] = {}
    for name, text in _as_docs(docs):
        rels, types = extract(text, ner_model, source=name)
        relations.extend(rels)
        for key, typ in types.items():
            entity_types.setdefault(key, typ)
    return to_context_graph(relations, entity_types)


# ---------------------------------------------------------------------------- semantica registry

def _entities_method(text, **kwargs):
    from semantica.semantic_extract.types import Entity

    model = kwargs.get("zh_ner_model", DEFAULT_NER_MODEL)
    return [Entity(text=text[s:e], label=t, start_char=s, end_char=e, confidence=1.0,
                   metadata={"extraction_method": ENTITY_METHOD})
            for s, e, t in get_ner(model)(text)]


def _relations_method(text, entities, **kwargs):
    from semantica.semantic_extract.types import Entity, Relation

    rels, _ = _relations.extract(text, [(e.start_char, e.end_char, e.label) for e in entities])
    return [Relation(
        subject=Entity(text=r.subject, label=r.subject_type, start_char=0, end_char=0),
        predicate=r.predicate,
        object=Entity(text=r.object, label=r.object_type, start_char=0, end_char=0),
        confidence=r.confidence, context=r.evidence,
        metadata={"extraction_method": RELATION_METHOD, "rule": r.rule, "resolution": r.resolution,
                  "kind": r.kind, "time": r.time},
    ) for r in rels]


def register() -> None:
    """Register "zh_ckip" (entity) and "zh_rules" (relation) with semantica. Safe to call twice.

    The registry is in-process memory, so call this once per process before using
    NamedEntityRecognizer(method="zh_ckip") / RelationExtractor(method="zh_rules").
    Note: semantica's RelationExtractor still adds "related_to" co-occurrence edges when
    the rules return nothing; filter with only_rule_relations().
    """
    from semantica.semantic_extract.registry import method_registry

    method_registry.register("entity", ENTITY_METHOD, _entities_method)
    method_registry.register("relation", RELATION_METHOD, _relations_method)


def _method_of(rel) -> Optional[str]:
    meta = rel.get("metadata") if isinstance(rel, dict) else getattr(rel, "metadata", None)
    return (meta or {}).get("extraction_method")


def only_rule_relations(relations: list) -> list:
    """Keep relations produced by the zh_rules method (drops semantica's co-occurrence fallback)."""
    return [r for r in relations if _method_of(r) == RELATION_METHOD]


def build_kg(docs: Docs, ner_model: str = DEFAULT_NER_MODEL) -> dict:
    """Build a semantica GraphBuilder knowledge graph from raw text with the registered methods."""
    from semantica.kg import GraphBuilder

    register()
    sources = [{"text": text, "metadata": {"source": name}} for name, text in _as_docs(docs)]
    kg = GraphBuilder().build(sources, ner_method=ENTITY_METHOD, relation_method=RELATION_METHOD,
                              extract_relations=True, extract_triplets=False, zh_ner_model=ner_model)
    kept = only_rule_relations(kg.get("relationships", []))
    dropped = len(kg.get("relationships", [])) - len(kept)
    kg["relationships"] = kept
    kg.setdefault("metadata", {})["zh_dropped_fallback_relations"] = dropped
    return kg


def export_rdf(kg: dict, path: Union[str, Path], format: str = "turtle") -> None:
    from semantica.export.rdf_exporter import RDFExporter

    RDFExporter().export_knowledge_graph(kg, Path(path), format=format)


# ---------------------------------------------------------------------------- CLI

def main(argv=None):
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)

    ap = argparse.ArgumentParser(description="Chinese text -> semantica knowledge graph (CPU only)")
    ap.add_argument("inputs", nargs="+", type=Path, help="UTF-8 text files, one document each")
    ap.add_argument("--out", type=Path, default=Path("zh_graph.json"), help="ContextGraph JSON (Explorer)")
    ap.add_argument("--ttl", type=Path, help="also write an RDF Turtle file via GraphBuilder")
    ap.add_argument("--ner-model", default=DEFAULT_NER_MODEL)
    args = ap.parse_args(argv)

    docs = {p.stem: p.read_text(encoding="utf-8") for p in args.inputs}
    graph = build_context_graph(docs, args.ner_model)
    graph.save_to_file(args.out)
    st = graph.stats()
    print(f"ContextGraph -> {args.out}: 节点 {st['node_count']}，边 {st['edge_count']}，边类型 {st['edge_types']}")
    if args.ttl:
        kg = build_kg(docs, args.ner_model)
        export_rdf(kg, args.ttl)
        print(f"RDF -> {args.ttl}: 实体 {len(kg['entities'])}，关系 {len(kg['relationships'])}"
              f"（已丢弃兜底关系 {kg['metadata']['zh_dropped_fallback_relations']} 条）")


if __name__ == "__main__":
    main()
