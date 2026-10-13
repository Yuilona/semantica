r"""Compare CPU-only Chinese NER: spaCy zh_core_web_sm vs. small HuggingFace BERT-style models.

  python scratch\zh_ner_compare.py

For each model it reports load time, warm per-text latency, exact-boundary
recall against a small hand-labelled gold set (names vs. numbers/dates), and
what semantica's NamedEntityRecognizer(method="huggingface") returns for the
same model, to check whether the wrapper keeps the original entity text.
"""

import logging
import time
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import spacy  # noqa: E402
from transformers import pipeline  # noqa: E402
from transformers.utils import logging as hf_logging  # noqa: E402

from semantica.semantic_extract import NamedEntityRecognizer  # noqa: E402

hf_logging.set_verbosity_error()

HF_MODELS = [
    "ckiplab/albert-tiny-chinese-ner",
    "ckiplab/albert-base-chinese-ner",
    "uer/roberta-base-finetuned-cluener2020-chinese",
    "shibing624/bert4ner-base-chinese",
]
SPACY_MODEL = "zh_core_web_sm"
WARM_RUNS = 5

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

# Gold entities by surface form (spaces ignored when matching).
GOLD_NAMES = {
    "贷款": ["张伟", "招商银行", "李娜"],
    "新闻": ["华为", "深圳", "任正非", "上海", "北京", "腾讯", "马化腾", "深圳大学"],
    "企业": ["阿里巴巴集团", "马云", "杭州", "阿里巴巴", "纽约证券交易所", "蚂蚁集团"],
}
GOLD_VALUES = {
    "贷款": ["30万元", "31%", "36个月", "2024年3月", "8.9%"],
    "新闻": ["2023年5月"],
    "企业": ["1999年", "2014年", "250亿美元"],
}


def norm(s):
    return s.replace(" ", "")


def recall(found, gold):
    found = {norm(f) for f in found}
    hits = [g for g in gold if norm(g) in found]
    return len(hits), len(gold), [g for g in gold if norm(g) not in found]


def timed(fn, text):
    fn(text)  # warm-up
    t0 = time.perf_counter()
    for _ in range(WARM_RUNS):
        out = fn(text)
    return out, (time.perf_counter() - t0) / WARM_RUNS * 1000


def run_spacy():
    t0 = time.perf_counter()
    nlp = spacy.load(SPACY_MODEL)
    load = time.perf_counter() - t0
    results = {}
    for name, text in TEXTS.items():
        doc, ms = timed(nlp, text)
        results[name] = ([(e.text, e.label_) for e in doc.ents], ms)
    return load, results


def decode_bies(tokens):
    """Group per-token B-/I-/E-/S- tags (CKIP models) into (start, end, type) spans."""
    spans, cur = [], None
    for t in tokens:
        prefix, _, typ = t["entity"].partition("-")
        if prefix == "S":
            if cur:
                spans.append(cur)
            spans.append([t["start"], t["end"], typ])
            cur = None
        elif prefix == "B" or not cur or cur[2] != typ:
            if cur:
                spans.append(cur)
            cur = [t["start"], t["end"], typ]
        else:  # I- or E- continuing the same type
            cur[1] = t["end"]
        if prefix == "E" and cur:
            spans.append(cur)
            cur = None
    if cur:
        spans.append(cur)
    return spans


def run_hf(model, bies=False):
    t0 = time.perf_counter()
    nlp = pipeline(
        "token-classification",
        model=model,
        aggregation_strategy="none" if bies else "simple",
        device=-1,
    )
    load = time.perf_counter() - t0
    results = {}
    for name, text in TEXTS.items():
        out, ms = timed(nlp, text)
        if bies:
            ents = [(text[s:e], typ) for s, e, typ in decode_bies(out)]
        else:
            # Take the surface text from the original string, not the decoded "word".
            ents = [(text[o["start"]:o["end"]], o["entity_group"]) for o in out]
        results[name] = (ents, ms)
    return load, results


def report(title, load, results):
    print(f"\n######## {title}  (加载 {load:.1f}s)")
    tot = {"n": [0, 0], "v": [0, 0]}
    for name, res in results.items():
        ents, ms = res[0], res[1]
        texts = [t for t, _ in ents]
        nh, ng, nmiss = recall(texts, GOLD_NAMES[name])
        vh, vg, vmiss = recall(texts, GOLD_VALUES[name])
        tot["n"][0] += nh; tot["n"][1] += ng
        tot["v"][0] += vh; tot["v"][1] += vg
        print(f"[{name}] {ms:.0f}ms  名称 {nh}/{ng}  数值时间 {vh}/{vg}")
        print("   实体:", ", ".join(f"{t}/{l}" for t, l in ents))
        if nmiss or vmiss:
            print("   漏掉:", ", ".join(nmiss + vmiss))
    n, v = tot["n"], tot["v"]
    print(f"== 合计  名称 {n[0]}/{n[1]}  数值时间 {v[0]}/{v[1]}")
    return n, v


def main():
    summary = []
    load, res = run_spacy()
    summary.append((SPACY_MODEL, load, res, *report(f"spaCy {SPACY_MODEL}", load, res)))

    for m in HF_MODELS:
        load, res = run_hf(m)
        summary.append((m, load, res, *report(m, load, res)))
        if m.startswith("ckiplab/"):
            title = f"{m} +BIES解码"
            load, res = run_hf(m, bies=True)
            summary.append((title, load, res, *report(title, load, res)))

    print("\n######## semantica 封装检查（NamedEntityRecognizer, method=huggingface）")
    sample = TEXTS["新闻"]
    for m in HF_MODELS:
        ents = NamedEntityRecognizer(method="huggingface", huggingface_model=m, device="cpu").extract_entities(sample)
        print(f"{m}:")
        print("   word 字段:", [e.text for e in ents][:8])
        print("   原文切片:", [sample[e.start_char:e.end_char] for e in ents][:8])

    print("\n######## 汇总")
    print(f"{'模型':50s} {'加载':>6s} {'平均耗时':>8s} {'名称':>7s} {'数值时间':>8s}")
    for m, load, res, n, v in summary:
        avg = sum(r[1] for r in res.values()) / len(res)
        print(f"{m:50s} {load:5.1f}s {avg:7.0f}ms {n[0]:>3d}/{n[1]:<3d} {v[0]:>4d}/{v[1]:<3d}")


if __name__ == "__main__":
    main()
