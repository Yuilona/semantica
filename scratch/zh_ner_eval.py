r"""Evaluate CPU-only Chinese NER models on the hand-labelled corpus scratch\zh_ner_corpus.txt.

  python scratch\zh_ner_eval.py

Corpus markup: [surface|TYPE], TYPE in PER ORG LOC DATE MONEY PERCENT, or "?" for
ambiguous spans (predictions overlapping them are neither right nor wrong).
Scoring is exact character-span match after mapping each model's label set to
those six types; labels outside them (CARDINAL, position, ...) are dropped.
Text is split into sentences so BERT models never hit the 512-token limit.
"""

import logging
import re
import time
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import spacy  # noqa: E402
from transformers import pipeline  # noqa: E402
from transformers.utils import logging as hf_logging  # noqa: E402

hf_logging.set_verbosity_error()

CORPUS = Path(__file__).with_name("zh_ner_corpus.txt")
NAMES = ("PER", "ORG", "LOC")
VALUES = ("DATE", "MONEY", "PERCENT")
TYPES = NAMES + VALUES

ONTONOTES = {
    "PERSON": "PER", "ORG": "ORG", "GPE": "LOC", "LOC": "LOC",
    "DATE": "DATE", "TIME": "DATE", "MONEY": "MONEY", "PERCENT": "PERCENT",
}
CLUENER = {
    "name": "PER", "company": "ORG", "organization": "ORG", "government": "ORG", "address": "LOC",
}
PEOPLE_DAILY = {"PER": "PER", "ORG": "ORG", "LOC": "LOC", "TIME": "DATE"}

# (name, kind, model id, label map). kind: spacy | bio | bies
MODELS = [
    ("spaCy zh_core_web_sm", "spacy", "zh_core_web_sm", ONTONOTES),
    ("ckiplab albert-tiny", "bies", "ckiplab/albert-tiny-chinese-ner", ONTONOTES),
    ("ckiplab albert-base", "bies", "ckiplab/albert-base-chinese-ner", ONTONOTES),
    ("ckiplab bert-base", "bies", "ckiplab/bert-base-chinese-ner", ONTONOTES),
    ("uer roberta-cluener", "bio", "uer/roberta-base-finetuned-cluener2020-chinese", CLUENER),
    ("shibing624 bert4ner", "bio", "shibing624/bert4ner-base-chinese", PEOPLE_DAILY),
]

VALUE_PATTERNS = {
    "MONEY": r"\d+(?:\.\d+)?\s*(?:[万亿千百]\s*)*(?:元|美元|港元|欧元|英镑|日元)",
    "PERCENT": r"\d+(?:\.\d+)?\s*[%％]",
    "DATE": r"\d{4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?|[末初底中])?"
            r"|\d{1,2}\s*月\s*\d{1,2}\s*[日号]|\d+\s*个月",
}


def load_corpus():
    raw = CORPUS.read_text(encoding="utf-8")
    text, gold, ignore, pos, last = [], set(), [], 0, 0
    for m in re.finditer(r"\[([^\[\]|]+)\|([A-Z?]+)\]", raw):
        text.append(raw[last:m.start()])
        pos += m.start() - last
        surface, typ = m.group(1), m.group(2)
        span = (pos, pos + len(surface))
        (ignore.append(span) if typ == "?" else gold.add((*span, typ)))
        text.append(surface)
        pos += len(surface)
        last = m.end()
    text.append(raw[last:])
    return "".join(text), gold, ignore


def sentences(text):
    start = 0
    for m in re.finditer(r"[。；！？\n]+", text):
        if m.end() > start and text[start:m.start()].strip():
            yield start, text[start:m.end()]
        start = m.end()
    if text[start:].strip():
        yield start, text[start:]


def decode_bies(tokens):
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
        else:
            cur[1] = t["end"]
        if prefix == "E" and cur:
            spans.append(cur)
            cur = None
    if cur:
        spans.append(cur)
    return spans


def trim(text, s, e):
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def build_predictor(kind, model_id):
    if kind == "spacy":
        nlp = spacy.load(model_id)
        return lambda sents: [[(e.start_char, e.end_char, e.label_) for e in doc.ents]
                              for doc in nlp.pipe(sents)]
    nlp = pipeline("token-classification", model=model_id, device=-1,
                   aggregation_strategy="none" if kind == "bies" else "simple")
    if kind == "bies":
        return lambda sents: [[tuple(x) for x in decode_bies(out)] for out in nlp(sents, batch_size=8)]
    return lambda sents: [[(o["start"], o["end"], o["entity_group"]) for o in out]
                          for out in nlp(sents, batch_size=8)]


def predict(predictor, text, label_map):
    sents = list(sentences(text))
    raw = predictor([s for _, s in sents])
    preds = set()
    for (offset, sent), ents in zip(sents, raw):
        for s, e, label in ents:
            typ = label_map.get(label)
            if typ:
                s, e = trim(sent, s, e)
                if e > s:
                    preds.add((offset + s, offset + e, typ))
    return preds


def regex_values(text):
    return {(m.start(), m.end(), typ)
            for typ, pat in VALUE_PATTERNS.items() for m in re.finditer(pat, text)}


def drop_ignored(preds, ignore):
    return {p for p in preds if not any(p[0] < e and s < p[1] for s, e in ignore)}


def prf(preds, gold, types):
    p = {x for x in preds if x[2] in types}
    g = {x for x in gold if x[2] in types}
    tp = len(p & g)
    prec = tp / len(p) if p else None
    rec = tp / len(g) if g else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else 0.0
    return prec, rec, f1


def fmt(x):
    return "   -" if x is None else f"{x:4.2f}"


def main():
    text, gold, ignore = load_corpus()
    counts = Counter(t for *_, t in gold)
    print(f"语料 {len(text)} 字，{len(list(sentences(text)))} 句，标注实体 {len(gold)} 个："
          + "，".join(f"{t} {counts[t]}" for t in TYPES) + f"；歧义区 {len(ignore)} 处\n")

    systems = {}
    timing = {}
    for name, kind, model_id, label_map in MODELS:
        t0 = time.perf_counter()
        predictor = build_predictor(kind, model_id)
        load = time.perf_counter() - t0
        predict(predictor, text, label_map)  # warm-up
        t0 = time.perf_counter()
        preds = predict(predictor, text, label_map)
        run = time.perf_counter() - t0
        timing[name] = (load, run)
        systems[name] = drop_ignored(preds, ignore)

    rx = drop_ignored(regex_values(text), ignore)
    systems["正则（仅数值时间）"] = rx
    timing["正则（仅数值时间）"] = (0.0, 0.0)
    for name, *_ in MODELS:
        combo = f"{name} + 正则"
        systems[combo] = {p for p in systems[name] if p[2] in NAMES} | rx
        timing[combo] = timing[name]

    print(f"{'系统':34s} {'名称 P/R/F1':>17s}  {'数值时间 P/R/F1':>17s}  {'总 F1':>5s} {'仅边界F1':>7s} {'速度':>10s}")
    rows = []
    for name, preds in systems.items():
        n = prf(preds, gold, NAMES)
        v = prf(preds, gold, VALUES)
        a = prf(preds, gold, TYPES)
        untyped = prf({(s, e, "X") for s, e, _ in preds}, {(s, e, "X") for s, e, _ in gold}, ("X",))
        load, run = timing[name]
        speed = f"{len(text) / run:7.0f}字/s" if run else "      -"
        rows.append((a[2], name))
        print(f"{name:34s} {fmt(n[0])}/{fmt(n[1])}/{fmt(n[2])}  {fmt(v[0])}/{fmt(v[1])}/{fmt(v[2])}  "
              f"{a[2]:5.2f} {untyped[2]:7.2f} {speed}")

    print("\n各类型 F1：")
    print(f"{'系统':34s} " + " ".join(f"{t:>7s}" for t in TYPES))
    for name, preds in systems.items():
        print(f"{name:34s} " + " ".join(f"{prf(preds, gold, (t,))[2]:7.2f}" for t in TYPES))

    for _, name in sorted(rows, reverse=True)[:3]:
        preds = systems[name]
        fn = sorted(gold - preds)
        fp = sorted(preds - gold)
        print(f"\n== {name} 的错误：漏掉 {len(fn)}，误报 {len(fp)}")
        print("  漏掉:", "，".join(f"{text[s:e]}/{t}" for s, e, t in fn))
        print("  误报:", "，".join(f"{text[s:e]}/{t}" for s, e, t in fp))


if __name__ == "__main__":
    main()
