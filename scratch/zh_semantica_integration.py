r"""Plug the Chinese extractor into semantica and check each integration path.

  python scratch\zh_semantica_integration.py

Registers zh_semantica's two methods (entity "zh_ckip", relation "zh_rules")
with semantica's method_registry, then checks:
  A. semantica's NamedEntityRecognizer / RelationExtractor return the same triples as the prototype
  B. what RelationExtractor does when the rules find nothing (its co-occurrence fallback)
  C. GraphBuilder builds a KG from raw text with the registered methods; RDF export round-trips
  D. the ContextGraph JSON saved by zh_extract reloads
"""

import logging
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

from semantica.semantic_extract import NamedEntityRecognizer, RelationExtractor  # noqa: E402

import zh_semantica as zs  # noqa: E402

HERE = Path(__file__).parent
zs.register()


def corpus_text(name):
    raw = (HERE / name).read_text(encoding="utf-8")
    return re.sub(r"\[([^\[\]|]+)\|[A-Z?]+\]", r"\1", raw)


def main():
    text = corpus_text("zh_ner_corpus.txt")

    print("== A. 通过 semantica 的 NamedEntityRecognizer / RelationExtractor 调用")
    ents = NamedEntityRecognizer(method="zh_ckip").extract_entities(text)
    rels = RelationExtractor(method="zh_rules").extract_relations(text, entities=ents)
    via_semantica = {(r.subject.text, r.predicate, r.object.text) for r in rels}
    direct = {r.triple() for r in zs.extract(text)[0]}
    print(f"   实体 {len(ents)}，关系 {len(rels)}；与直接调用原型一致: {via_semantica == direct}"
          f"（只在 semantica 侧 {len(via_semantica - direct)}，只在原型侧 {len(direct - via_semantica)}）")

    print("\n== B. 规则一条都没命中时")
    quiet = "张伟和李娜昨天在杭州见面，聊了聊招商银行的近况。"
    q_ents = NamedEntityRecognizer(method="zh_ckip").extract_entities(quiet)
    q_rels = RelationExtractor(method="zh_rules").extract_relations(quiet, entities=q_ents)
    print(f"   原型直接调用: {len(zs.extract(quiet)[0])} 条")
    print(f"   经 semantica RelationExtractor: {len(q_rels)} 条 -> "
          + "，".join(f"{r.subject.text}·{r.predicate}·{r.object.text}[{r.metadata.get('extraction_method')}]"
                     for r in q_rels))

    print("\n== C. GraphBuilder 从原始文本构建 KG，再导出 RDF")
    from semantica.kg import GraphBuilder

    kg = GraphBuilder().build([{"text": text}], ner_method="zh_ckip", relation_method="zh_rules",
                              extract_relations=True, extract_triplets=False)
    kg_rels = kg.get("relationships", [])
    types = {}
    for r in kg_rels:
        types[r.get("type")] = types.get(r.get("type"), 0) + 1
    print(f"   实体 {len(kg.get('entities', []))}，关系 {len(kg_rels)}；关系类型 {types}")
    sample = next((r for r in kg_rels if r.get("type") == "任职于"), None)
    if sample:
        print(f"   样例关系: { {k: sample.get(k) for k in ('source', 'target', 'type', 'confidence')} }"
              f"  元数据保留: {sorted((sample.get('metadata') or {}).keys())}")
    ent_sample = next((e for e in kg.get("entities", []) if e.get("type") == "PER"), None)
    print(f"   样例实体: { {k: ent_sample.get(k) for k in ('id', 'name', 'type')} if ent_sample else None}")

    from rdflib import Graph as RDFGraph
    from semantica.export.rdf_exporter import RDFExporter

    ttl = HERE / "zh_kg.ttl"
    RDFExporter().export_knowledge_graph(kg, ttl, format="turtle")
    g = RDFGraph().parse(ttl, format="turtle")
    zh_iris = [s for s in set(g.subjects()) if re.search(r"%E[4-9]|[一-鿿]", str(s))]
    print(f"   RDF: {ttl.name} 回读 {len(g)} 个三元组；含中文的主语 IRI 示例: {[str(s) for s in zh_iris[:2]]}")

    print("\n== D. ContextGraph JSON 重新加载")
    from semantica.context import ContextGraph

    path = HERE / "zh_extract_graph.json"
    cg = ContextGraph()
    cg.load_from_file(path)
    st = cg.stats()
    edge = next((e for e in cg.find_edges() if e.get("type") == "任职于" or e.get("edge_type") == "任职于"), None)
    print(f"   {path.name}: 节点 {st['node_count']}，边 {st['edge_count']}")
    node = cg.find_node("张伟")
    attrs = {k: v for k, v in (node or {}).get("metadata", {}).items() if k not in ("id", "text", "type", "content")}
    print(f"   张伟 节点属性: {attrs}")
    if edge:
        print(f"   边元数据示例: { {k: edge.get('metadata', {}).get(k) for k in ('rule', 'resolution', 'evidence')} }")


if __name__ == "__main__":
    main()
