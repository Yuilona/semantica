r"""Chinese extractor prototype: CPU-only NER + rule-based relation extraction -> semantica ContextGraph.

  python scratch\zh_extract.py [text_file]     # extract and save scratch\zh_extract_graph.json

Pipeline
  1. ZhNER: ckiplab/bert-base-chinese-ner (BIES decoding) for PER/ORG/LOC, regex for DATE/MONEY/PERCENT.
  2. ZhRelationExtractor: per clause, mentions are replaced by placeholder characters and the
     templates in zh_rules.py are matched. Chinese-specific handling:
       - dropped subjects are carried over from the previous clause of the same sentence
       - 他/她, 公司/该公司, 该行/行内, 其 resolve to the current topic
       - 客户/申请人/借款人 + name binds a role; later bare 申请人 resolves to that person
       - coordinated mentions (北京、上海和深圳) expand into one relation each
       - "（简称“X”）" registers an alias; later mentions of X map to the full name
     No co-occurrence fallback: a pair without a matching rule produces nothing.
  3. to_context_graph: relations become edges, numeric attributes become node properties;
     every edge keeps its rule id, evidence clause and how the subject was resolved.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from zh_rules import RULES

Span = Tuple[int, int, str]  # (start, end, type)

NAME_TYPES = ("PER", "ORG", "LOC")
VALUE_TYPES = ("DATE", "MONEY", "PERCENT")
NODE_TYPE_ZH = {"PER": "人物", "ORG": "机构", "LOC": "地点"}

VALUE_PATTERNS = {
    "MONEY": r"\d+(?:\.\d+)?\s*(?:[万亿千百]\s*)*(?:元|美元|港元|欧元|英镑|日元)",
    "PERCENT": r"\d+(?:\.\d+)?\s*[%％]",
    "DATE": r"\d{4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?|[末初底中])?"
            r"|\d{1,2}\s*月\s*\d{1,2}\s*[日号]|\d+\s*个月",
}
ONTONOTES = {"PERSON": "PER", "ORG": "ORG", "GPE": "LOC", "LOC": "LOC"}

SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?”’\"]*")
CLAUSE_RE = re.compile(r"[^，,；;：:]+")
PREPOSITIONS = set("由被向在于从与和及对给为自至将把")
ROLE_WORDS = ("申请人", "借款人", "客户")
ROLE_RE = re.compile(r"(?:申请人|借款人|客户)(?!编号|经理|号)")
PRONOUNS = [
    (re.compile(r"(?<![其吉])他(?!们|人|方)|她(?!们)"), "PER"),
    (re.compile(r"(?<![一家个的分子总母限])(?:该|本)?公司"), "ORG"),
    (re.compile(r"该行|本行|行内"), "BANK"),
    (re.compile(r"(?<![尤极与])其(?![他中实余次])"), "ANY"),
]
PLACEHOLDER = 0xE000
COORDINATION_RE = re.compile(r"([-])((?:(?:、|以及|和|及|与)[-])+)")


# --------------------------------------------------------------------------- NER

def sentences(text: str):
    for m in SENTENCE_RE.finditer(text):
        if m.group().strip():
            yield m.start(), m.group()


def regex_values(text: str) -> List[Span]:
    return [(m.start(), m.end(), typ) for typ, pat in VALUE_PATTERNS.items() for m in re.finditer(pat, text)]


def decode_bies(tokens) -> List[list]:
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


class ZhNER:
    """ckiplab bert-base (BIES) for names + regex for dates, amounts and percentages."""

    def __init__(self, model: str = "ckiplab/bert-base-chinese-ner", batch_size: int = 8):
        from transformers import pipeline
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
        self.nlp = pipeline("token-classification", model=model, aggregation_strategy="none", device=-1)
        self.batch_size = batch_size

    def __call__(self, text: str) -> List[Span]:
        sents = list(sentences(text))
        values = regex_values(text)
        names = []
        for (offset, sent), out in zip(sents, self.nlp([s for _, s in sents], batch_size=self.batch_size)):
            for s, e, label in decode_bies(out):
                typ = ONTONOTES.get(label)
                while s < e and sent[s].isspace():
                    s += 1
                while e > s and sent[e - 1].isspace():
                    e -= 1
                if typ and e > s:
                    names.append([offset + s, offset + e, typ])
        names = [n for n in names if not any(n[0] < ve and vs < n[1] for vs, ve, _ in values)]
        merged = []  # adjacent LOC spans form one address: 深圳市 + 南山区
        for n in sorted(names):
            if merged and n[2] == "LOC" == merged[-1][2] and n[0] == merged[-1][1]:
                merged[-1][1] = n[1]
            else:
                merged.append(n)
        return sorted([tuple(n) for n in merged] + values)


# --------------------------------------------------------------------------- relations

@dataclass
class Mention:
    start: int
    end: int
    type: str
    text: str
    kind: str = "entity"  # entity | pronoun | role
    key: Optional[str] = None
    via: str = ""


@dataclass
class ExtractedRelation:
    subject: str
    predicate: str
    object: str
    kind: str
    rule: str
    evidence: str
    resolution: str
    confidence: float
    time: Optional[str] = None
    subject_type: str = ""
    object_type: str = ""
    source: Optional[str] = None  # document the relation was extracted from

    def triple(self):
        return self.subject, self.predicate, self.object


@dataclass
class _State:
    alias: Dict[str, str] = field(default_factory=dict)
    applicant: Optional[str] = None
    applicant_seen: int = -99
    topic: Dict[str, str] = field(default_factory=dict)
    topic_last: Optional[Tuple[str, str]] = None
    last: Dict[str, str] = field(default_factory=dict)


class _NoMatch(Exception):
    pass


class ZhRelationExtractor:
    def __init__(self, rules=RULES, role_window: int = 2):
        self.rules = [self._prepare(r) for r in rules]
        self.role_window = role_window

    @staticmethod
    def _prepare(rule):
        rule = {"kind": "relation", "fallback": [], "s_type": None, "object_filter": None, **rule}
        rule["has_subject"] = "{S:" in rule["template"]
        return rule

    @staticmethod
    def _compile(template: str, classes: Dict[str, str]):
        pattern = template.replace("……", ".{0,25}?").replace("…", ".{0,12}?")

        def slot(m):
            chars = "".join(classes.get(t, "") for t in m.group(2).split("|"))
            if not chars:
                raise _NoMatch
            return f"(?P<{m.group(1)}>[{chars}])"

        return re.compile(re.sub(r"\{([SO]):([A-Z|]+)\}", slot, pattern))

    # -- mentions ---------------------------------------------------------

    def _mentions(self, text, c0, c1, spans) -> List[Mention]:
        ments = [Mention(s, e, t, text[s:e]) for s, e, t in spans if s >= c0 and e <= c1]
        taken = [(m.start, m.end) for m in ments]

        def free(s, e):
            return not any(s < te and ts < e for ts, te in taken)

        clause = text[c0:c1]
        for rx, ptype in PRONOUNS:
            for m in rx.finditer(clause):
                s, e = c0 + m.start(), c0 + m.end()
                if free(s, e):
                    ments.append(Mention(s, e, ptype, m.group(), kind="pronoun"))
                    taken.append((s, e))
        for m in ROLE_RE.finditer(clause):
            s, e = c0 + m.start(), c0 + m.end()
            names_here = any(x.start == e and x.type == "PER" for x in ments)
            if free(s, e) and not names_here:
                ments.append(Mention(s, e, "PER", m.group(), kind="role"))
                taken.append((s, e))
        return sorted(ments, key=lambda m: m.start)

    def _resolve(self, m: Mention, st: _State) -> bool:
        if m.kind == "entity":
            m.key = st.alias.get(m.text, m.text)
            if m.key != m.text:
                m.via = f"简称“{m.text}”"
            return True
        if m.kind == "role":
            m.key, m.via = st.applicant, f"角色“{m.text}”"
            return m.key is not None
        if m.type == "PER":
            m.key = st.topic.get("PER") or st.last.get("PER")
        elif m.type == "ORG":
            m.key = st.topic.get("ORG") or st.last.get("ORG")
        elif m.type == "BANK":
            m.key, m.type = st.last.get("BANK"), "ORG"
        elif st.topic_last:  # 其
            m.type, m.key = st.topic_last
        if m.key:
            m.via = f"指代“{m.text}”"
        return m.key is not None

    # -- main -------------------------------------------------------------

    def extract(self, text: str, spans: List[Span]) -> Tuple[List[ExtractedRelation], Dict[str, str]]:
        st = _State()
        found: Dict[Tuple[str, str, str], ExtractedRelation] = {}
        entity_types: Dict[str, str] = {}

        for si, (s0, sent) in enumerate(sentences(text)):
            prev_subject: Optional[Mention] = None
            for cm in CLAUSE_RE.finditer(sent):
                c0, c1 = s0 + cm.start(), s0 + cm.end()
                ments = [m for m in self._mentions(text, c0, c1, spans) if self._resolve(m, st)]
                for m in ments:
                    if m.kind == "entity" and m.type == "PER" and any(
                            text[max(c0, m.start - len(w)):m.start] == w for w in ROLE_WORDS):
                        st.applicant, st.applicant_seen = m.key, si
                    if m.key == st.applicant:
                        st.applicant_seen = si
                    if m.kind == "entity" and m.type in NAME_TYPES:
                        entity_types.setdefault(m.key, m.type)

                subject = self._clause_subject(text, c0, ments)
                explicit = subject is not None
                clause_subject = subject or prev_subject

                rels = self._apply_rules(text, c0, c1, ments, clause_subject, prev_subject, st, si)

                # "腾讯跟投": the clause-initial name is the object of a relation whose subject
                # was borrowed from earlier text, so the topic stays put. "比亚迪董事长王传福":
                # the relation has its own subject, and 比亚迪 does become the topic.
                borrowed_objects = {r.object for r in rels if not r.resolution.startswith("显式主语")}
                if explicit and subject.key not in borrowed_objects:
                    st.topic[subject.type] = subject.key
                    st.topic_last = (subject.type, subject.key)
                for m in ments:
                    if m.kind == "entity" and m.type in NAME_TYPES:
                        st.last[m.type] = m.key
                        if m.type == "ORG" and m.key.endswith("行"):
                            st.last["BANK"] = m.key
                for r in rels:
                    if r.predicate == "简称":
                        st.alias[r.object] = r.subject
                    if "角色" in r.resolution:
                        st.applicant_seen = si
                    found.setdefault(r.triple(), r)
                prev_subject = clause_subject
        return list(found.values()), entity_types

    @staticmethod
    def _clause_subject(text, c0, ments) -> Optional[Mention]:
        for m in ments:
            if m.type not in ("PER", "ORG"):
                continue
            before = text[m.start - 1] if m.start > c0 else ""
            after = text[m.end] if m.end < len(text) else ""
            if after == "的" or before in PREPOSITIONS:
                continue
            return m
        return None

    def _mask(self, text, c0, c1, ments):
        groups: Dict[str, List[Mention]] = {}
        out, pos = [], c0
        for i, m in enumerate(ments):
            ch = chr(PLACEHOLDER + i)
            out.append(text[pos:m.start])
            out.append(ch)
            groups[ch] = [m]
            pos = m.end
        out.append(text[pos:c1])
        masked = "".join(out)

        def merge(match):
            chars = [match.group(1)] + re.findall(r"[-]", match.group(2))
            types = {groups[c][0].type for c in chars}
            if len(types) != 1 or types.pop() not in NAME_TYPES:
                return match.group(0)
            groups[chars[0]] = [m for c in chars for m in groups[c]]
            return chars[0]

        masked = COORDINATION_RE.sub(merge, masked)
        classes: Dict[str, str] = {}
        for ch in set(re.findall(r"[-]", masked)):
            t = groups[ch][0].type
            classes[t] = classes.get(t, "") + ch
        return masked, groups, classes

    def _fallback(self, rule, clause_subject, prev_subject, object_keys, st, si):
        for how in rule["fallback"]:
            if how == "clause":
                for cand, note in ((clause_subject, "承接本句主语"), (prev_subject, "承接上一小句主语")):
                    if cand and cand.key not in object_keys and rule["s_type"] in (None, cand.type):
                        return cand, note + (f"，{cand.via}" if cand.via else "")
            elif how == "role" and st.applicant and si - st.applicant_seen <= self.role_window:
                return Mention(0, 0, "PER", st.applicant, key=st.applicant), "角色“申请人”"
        return None, ""

    def _apply_rules(self, text, c0, c1, ments, clause_subject, prev_subject, st, si):
        if not ments:
            return []
        masked, groups, classes = self._mask(text, c0, c1, ments)
        evidence = text[c0:c1]
        used_objects = set()
        cands = []
        for rule in self.rules:
            try:
                pat = self._compile(rule["template"], classes)
            except _NoMatch:
                continue
            for mt in pat.finditer(masked):
                objs = groups[mt.group("O")]
                if rule["object_filter"]:
                    objs = [o for o in objs if re.search(rule["object_filter"], o.text)]
                if not objs:
                    continue
                if rule["has_subject"]:
                    subs = groups[mt.group("S")]
                    notes = [("显式主语" + (f"，{s.via}" if s.via else "")) for s in subs]
                else:
                    s, note = self._fallback(rule, clause_subject, prev_subject, {o.key for o in objs}, st, si)
                    subs, notes = ([s], [note]) if s else ([], [])
                kw = mt.groupdict().get("kw") or ""
                predicate = rule["predicate"].replace("{kw}", kw)
                for s, note in zip(subs, notes):
                    for o in objs:
                        if s.key == o.key:
                            continue
                        obj = o.text if predicate == "简称" else o.key
                        conf = 0.9 if rule["has_subject"] else (0.8 if "主语" in note else 0.7)
                        if "指代" in note or "角色" in note:
                            conf -= 0.05
                        cands.append((rule["has_subject"], ExtractedRelation(
                            subject=s.key, predicate=predicate, object=obj, kind=rule["kind"], rule=rule["id"],
                            evidence=evidence, resolution=note, confidence=round(conf, 2),
                            subject_type=s.type, object_type=o.type)))
                        used_objects.add(id(o))
        # an explicit-subject match wins over a fallback match for the same (predicate, object)
        explicit = {(r.predicate, r.object) for has_s, r in cands if has_s}
        rels = [r for has_s, r in cands if has_s or (r.predicate, r.object) not in explicit]
        dates = [m.text for m in ments if m.type == "DATE" and id(m) not in used_objects]
        for r in rels:
            r.time = dates[0] if dates else None
        return rels


# --------------------------------------------------------------------------- semantica

def to_context_graph(relations: List[ExtractedRelation], entity_types: Dict[str, str]):
    from semantica.context import ContextGraph

    nodes: Dict[str, dict] = {}

    def node(key, typ):
        if key not in nodes:
            nodes[key] = {"id": key, "text": key, "type": NODE_TYPE_ZH.get(typ, "实体")}
        return nodes[key]

    for key, typ in entity_types.items():
        node(key, typ)
    edges = []
    for r in relations:
        subj = node(r.subject, r.subject_type)
        if r.kind == "attribute":
            prev = subj.get(r.predicate)
            subj[r.predicate] = r.object if prev is None else sorted({*([prev] if isinstance(prev, str) else prev), r.object})
            continue
        if r.predicate == "简称":
            subj.setdefault("简称", []).append(r.object)
            continue
        node(r.object, r.object_type)
        edges.append({
            "source_id": r.subject, "target_id": r.object, "type": r.predicate, "confidence": r.confidence,
            "rule": r.rule, "evidence": r.evidence, "resolution": r.resolution, "time": r.time,
            "source": r.source,
        })
    graph = ContextGraph()
    graph.build_from_entities_and_relationships(list(nodes.values()), edges)
    return graph


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("zh_ner_corpus.txt")
    text = re.sub(r"\[([^\[\]|]+)\|[A-Z?]+\]", r"\1", src.read_text(encoding="utf-8"))  # drop gold markup
    spans = ZhNER()(text)
    relations, entity_types = ZhRelationExtractor().extract(text, spans)
    for r in relations:
        print(f"({r.subject}, {r.predicate}, {r.object})  [{r.rule}; {r.resolution}; {r.confidence}]")
    graph = to_context_graph(relations, entity_types)
    out = Path(__file__).with_name("zh_extract_graph.json")
    graph.save_to_file(out)
    print(f"\n{len(relations)} 条关系/属性 -> {out}  ({graph.stats()})")


if __name__ == "__main__":
    main()
