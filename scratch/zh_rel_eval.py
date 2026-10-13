r"""Evaluate the Chinese relation extractor prototype against hand-labelled gold relations.

  python scratch\zh_rel_eval.py          # all documents
  python scratch\zh_rel_eval.py --dev    # dev only (use this while editing rules)

Documents: the dev corpus (zh_ner_corpus.txt, rules were written against it);
held-out set 1 (zh_rel_heldout.txt), whose errors drove the topic-update fix, so
it is no longer a clean test; held-out set 2 (zh_rel_heldout2.txt), written
before that fix was run and never tuned on. Each is scored with gold entities (relation extraction alone) and with ZhNER's
predicted entities (end to end). semantica's built-in RelationExtractor is run on
the same gold entities as a baseline.
"""

import logging
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

from zh_extract import VALUE_PATTERNS, ZhNER, ZhRelationExtractor, to_context_graph  # noqa: E402

HERE = Path(__file__).parent
DOCS = [
    ("开发集", HERE / "zh_ner_corpus.txt", HERE / "zh_rel_gold.tsv"),
    ("验证集1（已用于修复）", HERE / "zh_rel_heldout.txt", HERE / "zh_rel_heldout_gold.tsv"),
    ("验证集2（新）", HERE / "zh_rel_heldout2.txt", HERE / "zh_rel_heldout2_gold.tsv"),
]
VALUE_RE = re.compile("|".join(f"(?:{p})" for p in VALUE_PATTERNS.values()))


def is_attribute(triple):
    """A triple whose object is an amount, percentage or date is a node attribute."""
    return VALUE_RE.fullmatch(triple[2]) is not None


def load_marked(path):
    raw = path.read_text(encoding="utf-8")
    text, spans, pos, last = [], [], 0, 0
    for m in re.finditer(r"\[([^\[\]|]+)\|([A-Z?]+)\]", raw):
        text.append(raw[last:m.start()])
        pos += m.start() - last
        if m.group(2) != "?":
            spans.append((pos, pos + len(m.group(1)), m.group(2)))
        text.append(m.group(1))
        pos += len(m.group(1))
        last = m.end()
    text.append(raw[last:])
    return "".join(text), sorted(spans)


def load_gold(path):
    rows = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]
    return {tuple(r) for r in rows}


def prf(pred, gold):
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def line(name, pred, gold):
    split = lambda s, attr: {t for t in s if is_attribute(t) == attr}  # noqa: E731
    p, r, f = prf(pred, gold)
    rp, rr, rf = prf(split(pred, False), split(gold, False))
    ap, ar, af = prf(split(pred, True), split(gold, True))
    print(f"  {name:26s} 总 {p:4.2f}/{r:4.2f}/{f:4.2f}   关系 {rp:4.2f}/{rr:4.2f}/{rf:4.2f}   "
          f"属性 {ap:4.2f}/{ar:4.2f}/{af:4.2f}   (输出 {len(pred)})")


def baseline(text, spans, method, **kw):
    from semantica.semantic_extract import RelationExtractor
    from semantica.semantic_extract.types import Entity

    ents = [Entity(text=text[s:e], label=t, start_char=s, end_char=e) for s, e, t in spans]
    rels = RelationExtractor(method=method, **kw).extract_relations(text, entities=ents)
    return {(r.subject.text, r.predicate, r.object.text) for r in rels}


def main():
    ner = ZhNER()
    extractor = ZhRelationExtractor()
    docs = DOCS[:1] if "--dev" in sys.argv else DOCS  # --dev: tune on the dev corpus only
    for name, doc, gold_path in docs:
        text, gold_spans = load_marked(doc)
        gold = load_gold(gold_path)
        n_attr = sum(map(is_attribute, gold))
        print(f"\n######## {name}：{doc.name}，{len(text)} 字，标准答案 {len(gold)} 条"
              f"（关系 {len(gold) - n_attr}，属性 {n_attr}）   格式 P/R/F1")

        rels_gold, _ = extractor.extract(text, gold_spans)
        pred_gold = {r.triple() for r in rels_gold}
        pred_spans = ner(text)
        rels_ner, types_ner = extractor.extract(text, pred_spans)
        pred_ner = {r.triple() for r in rels_ner}

        line("原型（标准实体）", pred_gold, gold)
        line("原型（NER 预测实体）", pred_ner, gold)
        line("semantica pattern（标准实体）", baseline(text, gold_spans, "pattern"), gold)
        line("semantica dependency（标准实体）",
             baseline(text, gold_spans, "dependency", model="zh_core_web_sm"), gold)

        for label, pred, rels in (("标准实体", pred_gold, rels_gold), ("NER 预测实体", pred_ner, rels_ner)):
            fn, fp = sorted(gold - pred), sorted(pred - gold)
            print(f"  -- 原型（{label}）漏掉 {len(fn)}：" + "；".join("·".join(t) for t in fn))
            info = {r.triple(): r for r in rels}
            print(f"  -- 原型（{label}）误报 {len(fp)}：" + "；".join(
                f"{'·'.join(t)} [{info[t].rule}，{info[t].resolution}]" for t in fp))

        if name == "开发集":
            graph = to_context_graph(rels_ner, types_ner)
            out = HERE / "zh_extract_graph.json"
            graph.save_to_file(out)
            sample = next((r for r in rels_ner if r.triple() == ("张伟", "年利率", "8.9%")), None)
            print(f"  -> 端到端结果已存为 {out.name}：{graph.stats()}")
            if sample:
                print(f"  -> 溯源示例 (张伟·年利率·8.9%)：规则 {sample.rule}；{sample.resolution}；"
                      f"置信度 {sample.confidence}；证据“{sample.evidence}”")


if __name__ == "__main__":
    main()
