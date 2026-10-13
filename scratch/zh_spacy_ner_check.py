r"""CPU-only Chinese extraction check with spaCy zh_core_web_sm (no LLM).

  python scratch\zh_spacy_ner_check.py

Compares raw spaCy NER, semantica's NamedEntityRecognizer wrapper, and the
dependency / pattern relation extractors on a few Chinese sentences.
"""

import time

import spacy

from semantica.semantic_extract import NamedEntityRecognizer, RelationExtractor, TripletExtractor

MODEL = "zh_core_web_sm"

TEXTS = {
    "贷款": (
        "申请人张伟（编号 A-7291）向招商银行申请了 30 万元个人消费贷款。"
        "初审专员李娜确认其月收入达标、负债收入比为 31%，并移交核保部门。"
        "核保团队依据其 36 个月良好信用记录批准了贷款，2024年3月定价系统给出 8.9% 的年利率。"
    ),
    "新闻": (
        "2023年5月，华为在深圳发布了新一代手机。"
        "公司创始人任正非表示，华为将继续加大在上海和北京的研发投入。"
        "腾讯董事会主席马化腾毕业于深圳大学。"
    ),
    "企业": (
        "阿里巴巴集团由马云于1999年在杭州创立。"
        "2014年，阿里巴巴在纽约证券交易所上市，募资250亿美元。"
        "蚂蚁集团是阿里巴巴的关联公司，总部位于杭州。"
    ),
}


def main():
    t0 = time.perf_counter()
    nlp = spacy.load(MODEL)
    print(f"加载 {MODEL}: {time.perf_counter() - t0:.2f}s\n")

    ner = NamedEntityRecognizer(model=MODEL)
    dep = RelationExtractor(method="dependency", model=MODEL)
    pat = RelationExtractor(method="pattern")
    trip = TripletExtractor(method="ml", model=MODEL)

    for name, text in TEXTS.items():
        print(f"===== {name} =====")

        t0 = time.perf_counter()
        doc = nlp(text)
        dt = time.perf_counter() - t0
        print(f"[spaCy 原生] {dt * 1000:.0f}ms")
        print("  分词:", " / ".join(t.text for t in doc))
        print("  实体:", [(e.text, e.label_) for e in doc.ents])

        ents = ner.extract_entities(text)
        print(f"[semantica NER] {len(ents)} 个:", [(e.text, e.label) for e in ents])

        for label, ex in (("dependency", dep), ("pattern", pat)):
            rels = ex.extract_relations(text, entities=ents)
            print(f"[关系 {label}] {len(rels)} 条:", [(r.subject.text, r.predicate, r.object.text) for r in rels])

        trips = trip.extract_triplets(text, entities=ents)
        print(f"[三元组 ml] {len(trips)} 条:", [(t.subject, t.predicate, t.object) for t in trips])

        print("  依存:", " ".join(f"{t.text}<{t.dep_}-{t.head.text}" for t in doc if t.dep_ in ("nsubj", "dobj", "ROOT", "nsubjpass", "pobj")))
        print()


if __name__ == "__main__":
    main()
