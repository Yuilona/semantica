"""Relation rules for the Chinese extractor prototype (zh_extract.py).

Template syntax (matched against a clause in which every mention is replaced by
one placeholder character):
  {S:PER}      subject slot, PER mention (alternatives: {S:PER|ORG})
  {O:ORG}      object slot
  …            any 0-12 characters (mentions included), non-greedy
  ……           any 0-25 characters
  (?P<kw>...)  keyword captured for the predicate, e.g. predicate "{kw}位于"
  anything else is a regular expression.

A rule without {S:..} takes its subject from `fallback`, tried in order:
  "clause"  the clause subject (explicit, or carried over from the previous
            clause of the same sentence when Chinese drops it)
  "role"    the entity bound to the 申请人/客户/借款人 role, if it was mentioned
            in the last few sentences
`s_type` restricts the fallback subject's type.

kind: "relation" -> graph edge; "attribute" -> property on the subject node.
"""

# Title words that mark "ORG + title + PER" employment. 创始人 is handled separately.
TITLES = (
    r"(?:董事会主席|董事长|主席|副总裁|总裁|副行长|行长|总经理|经理|首席[^，。-]{0,4}官"
    r"|首席科学家|新闻发言人|发言人|副局长|局长|董事|合伙人|工程师|专员|研究员|教授|CEO|CTO|CFO)"
)
NOT_MENTION = r"[^，。-]"
VERB_FOUND = r"(?:联合创立|联合创办|创立|创办|创建|成立)"
VERB_WORK = r"(?:担任|任职|任|工作|就职)"
NUM_VERB = r"(?:为|是|达到|达|约|升至|降至|定为)?(?:约)?"

RULES = [
    # ---- employment (PER -> ORG)
    dict(id="work_at", predicate="任职于", template=r"(?:在|于){O:ORG}" + VERB_WORK,
         fallback=["clause"], s_type="PER"),
    dict(id="work_title", predicate="任职于", template=r"{O:ORG}的?" + NOT_MENTION + r"{0,6}?" + TITLES + r"{S:PER}"),
    dict(id="work_held", predicate="任职于", template=r"{S:PER}(?:曾任|曾担任|现任|担任|出任|兼任){O:ORG}"),
    dict(id="work_held_fb", predicate="任职于", template=r"(?:曾任|曾担任|现任|出任|兼任){O:ORG}",
         fallback=["clause"], s_type="PER"),

    # ---- founding (ORG -> PER / LOC)
    dict(id="found_by", predicate="创始人", template=r"{S:ORG}…由{O:PER}…" + VERB_FOUND),
    dict(id="found_by_rel", predicate="创始人", template=r"{O:PER}" + VERB_FOUND + r"的{S:ORG}"),
    dict(id="found_title", predicate="创始人",
         template=r"{S:ORG}的?(?:联合)?创始人(?:兼" + NOT_MENTION + r"{1,8}?)?{O:PER}"),
    dict(id="found_active", predicate="创始人", template=r"{O:PER}…" + VERB_FOUND + r"了?{S:ORG}"),
    dict(id="found_place", predicate="创立地", template=r"{S:ORG}…在{O:LOC}" + VERB_FOUND),
    dict(id="found_place_fb", predicate="创立地", template=r"在{O:LOC}" + VERB_FOUND,
         fallback=["clause"], s_type="ORG"),

    # ---- organisation facts
    dict(id="hq", predicate="总部位于", template=r"{S:ORG}总部(?:位于|设在|设于)…{O:LOC}"),
    dict(id="hq_fb", predicate="总部位于", template=r"总部(?:位于|设在|设于){O:LOC}",
         fallback=["clause"], s_type="ORG"),
    dict(id="facility", predicate="{kw}位于",
         template=r"在{O:LOC}(?:设有|设立|建设|建立|新建|开设)了?"
                  r"(?P<kw>研发中心|工厂|分公司|办事处|生产基地|数据中心)",
         fallback=["clause"], s_type="ORG"),
    dict(id="listed", predicate="上市于", template=r"在{O:ORG}(?:挂牌)?上市",
         fallback=["clause"], s_type="ORG"),
    dict(id="alias", predicate="简称", template=r"{S:ORG}[（(](?:以下)?简称[“\"「]?{O:ORG}"),
    dict(id="investor", predicate="投资方", template=r"{O:ORG}(?:领投|跟投|参投)",
         fallback=["clause"], s_type="ORG"),
    dict(id="graduated", predicate="毕业于", template=r"{S:PER}(?:曾)?毕业于{O:ORG}"),
    dict(id="graduated_fb", predicate="毕业于", template=r"毕业于{O:ORG}",
         fallback=["clause"], s_type="PER"),

    # ---- people
    dict(id="spouse", predicate="配偶", template=r"{S:PER}的(?:妻子|丈夫|配偶|爱人|太太){O:PER}"),
    dict(id="approver", predicate="审批人", template=r"审批人(?:是|为){O:PER}",
         fallback=["role", "clause"], s_type="PER"),

    # ---- loans (PER -> bank)
    dict(id="bank_apply", predicate="贷款银行", template=r"{S:PER}…向{O:ORG}…申请"),
    dict(id="bank_received", predicate="贷款银行", template=r"{O:ORG}…收到……{S:PER}……申请"),
    dict(id="bank_client", predicate="贷款银行", template=r"{O:ORG}的(?:客户|借款人){S:PER}"),
    dict(id="bank_is", predicate="贷款银行", template=r"(?:贷款行|贷款银行|放款行)(?:是|为){O:ORG}",
         fallback=["clause", "role"], s_type="PER"),
    dict(id="bank_account", predicate="开户银行", template=r"{S:PER}在{O:ORG}开立的?(?:账户|帐户)"),
    dict(id="property_loc", predicate="房产位于",
         template=r"位于{O:LOC}的(?:住房|房产|房屋|住宅|商铺)", fallback=["clause", "role"], s_type="PER"),

    # ---- numeric attributes
    dict(id="apply_amount", predicate="申请金额", kind="attribute",
         template=r"{S:PER}申请了?{O:MONEY}"),
    dict(id="apply_amount_fb", predicate="申请金额", kind="attribute",
         template=r"申请(?:金额)?(?:为|是|了)?…{O:MONEY}", fallback=["role", "clause"], s_type="PER"),
    dict(id="loan_amount", predicate="贷款金额", kind="attribute",
         template=r"(?:有|借了?|欠)一笔{O:MONEY}的?…贷款", fallback=["clause", "role"], s_type="PER"),
    dict(id="disbursed", predicate="放款金额", kind="attribute",
         template=r"{O:MONEY}的?贷款(?:已)?(?:发放|放款|划)至?{S:PER}"),
    dict(id="term", predicate="贷款期限", kind="attribute", template=r"期限(?:为|是)?{O:DATE}",
         fallback=["role", "clause"], s_type="PER", object_filter=r"个月|年期|年$"),
    dict(id="income", predicate="月收入", kind="attribute", template=r"月收入" + NUM_VERB + r"{O:MONEY}",
         fallback=["clause", "role"], s_type="PER"),
    dict(id="appraisal", predicate="房产估值", kind="attribute", template=r"评估价值" + NUM_VERB + r"{O:MONEY}",
         fallback=["clause", "role"], s_type="PER"),
    dict(id="dti_family", predicate="家庭负债收入比", kind="attribute",
         template=r"家庭负债收入比" + NUM_VERB + r"{O:PERCENT}", fallback=["role", "clause"], s_type="PER"),
    dict(id="dti", predicate="负债收入比", kind="attribute",
         template=r"(?<!家庭)负债收入比" + NUM_VERB + r"{O:PERCENT}", fallback=["role", "clause"], s_type="PER"),
    dict(id="rate", predicate="年利率", kind="attribute",
         template=r"(?:年利率|年化利率)" + NUM_VERB + r"{O:PERCENT}", fallback=["role", "clause"], s_type="PER"),
    dict(id="rate_at", predicate="年利率", kind="attribute", template=r"以{O:PERCENT}的年化?利率",
         fallback=["role", "clause"], s_type="PER"),
    dict(id="risk_premium", predicate="信用风险溢价", kind="attribute",
         template=r"信用风险溢价" + NUM_VERB + r"{O:PERCENT}", fallback=["role", "clause"], s_type="PER"),
    dict(id="funding", predicate="融资金额", kind="attribute", template=r"(?:完成|获得)了?(?:约)?{O:MONEY}…融资",
         fallback=["clause"], s_type="ORG"),
    dict(id="funding_raise", predicate="融资金额", kind="attribute",
         template=r"(?:募资|募集资金|募集)(?:约)?{O:MONEY}", fallback=["clause"], s_type="ORG"),
    dict(id="revenue", predicate="营业收入", kind="attribute",
         template=r"(?<!月)(?:营业收入|营收)" + NUM_VERB + r"{O:MONEY}", fallback=["clause"], s_type="ORG"),
    dict(id="growth", predicate="同比增长率", kind="attribute", template=r"同比增长(?:了)?{O:PERCENT}",
         fallback=["clause"], s_type="ORG"),
]
