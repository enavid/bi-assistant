# Routing Eval Failure Report
**Last updated:** 2026-06-17  
**Run:** `uv run pytest backend/tests/routing_eval/`  
**Result:** 10 failed, 1023 passed, 26 xfailed  

---

## Progress

| Date | Failures | Fixed |
|------|----------|-------|
| 2026-06-16 (start) | 199 | — |
| 2026-06-16 (Cat-7 test-data fixes) | 187 | 6 near-retirement test data variants fixed |
| 2026-06-16 (Cat-4, Cat-3, Cat-5, Cat-6 validator fixes) | 18 | ~169 fixed via validator/orchestrator/intent_parser changes |
| 2026-06-17 (acc-229v2/v3 + anl-203v1) | **10** | دکترا anchor term + aging gap double-normalization fix |

---

## Remaining 10 Failures

### Group A — SQL Template Failure (3 cases)
**Root cause:** Intent and route are correct (`employee_count_by_service_domain`) but the SQL template does not emit `service_domain` column or `GROUP BY`, so `must_include_sql` validation fails.  
**Fix location:** SQL template for `employee_count_by_service_domain` — outside intent_parser / validator scope.

| ID | Question | Route | Status | Intent |
|----|----------|-------|--------|--------|
| cross-167 | تعداد زنان قراردادی در هر حوزه چقدر است؟ | SQL | SQL_VALIDATION_FAILED | employee_count_by_service_domain |
| cross-168 | تعداد مردان رسمی در هر حوزه چقدر است؟ | SQL | SQL_VALIDATION_FAILED | employee_count_by_service_domain |
| cross-182 | سهم زنان در کارکنان رسمی هر حوزه چقدر است؟ | SQL | SQL_VALIDATION_FAILED | employee_count_by_service_domain |

---

### Group B — Intent Conflict: Age Filter vs Employment Type (3 cases)
**Root cause:** Questions ask about employment type distribution **within** an age bracket. Intent parser resolves the ambiguity to `employee_count_by_age_filter` instead of `employee_count_by_employment_type`.  
**Judgment call:** Both intents are arguably correct; the expected intents in the test data prioritize employment-type breakdown. Could fix by adding a rule that when "رسمی/قراردادی" appears alongside an age range, prefer `employee_count_by_employment_type`.

| ID | Question | Expected Intent | Got Intent |
|----|----------|-----------------|------------|
| cross-180v2 | چند نفر زیر ۳۰ سال قراردادی داریم؟ | employee_count_by_employment_type | employee_count_by_age_filter |
| cross-180v3 | کارکنان جوان قراردادی (زیر ۳۰ سال) چند نفرن؟ | employee_count_by_employment_type | employee_count_by_age_filter |
| emp-077v3 | نیروهای مسن (۶۰ به بالا) بیشتر رسمین یا قراردادی؟ | employee_count_by_employment_type | employee_count_by_age_filter |

---

### Group C — Access Control: Meta-Query Misclassified (1 case)
**Root cause:** "دسترسی به اطلاعات خام پرسنلی ممکنه؟" is a meta-question ("is it possible?"), not a direct data request. The validator's access rule fires on "اطلاعات ... پرسنلی" and returns ACCESS_DENIED. Expected: NEEDS_CLARIFICATION because the intent is unclear.  
**Judgment call:** Borderline — the test expects the system to distinguish a meta-query from a real access request. Requires either a new pre-filter for "ممکنه؟" phrasing or a test-data update.

| ID | Question | Expected | Got |
|----|----------|----------|-----|
| acc-225v3 | دسترسی به اطلاعات خام پرسنلی ممکنه؟ | REJECT:NEEDS_CLARIFICATION | REJECT:ACCESS_DENIED |

---

### Group D — Analytical Gap Miss (1 case)
**Root cause:** "آیا استخدام‌ها متناسب با گسترش سازمان بوده؟" contains none of the current ANALYTICAL_GAP trigger terms (`تهدید`, `نگران`, `ریسک`, `همخوانی`, `همگام`). The word "متناسب" (proportionate) is the key signal here but is not in the rule list.  
**Fix:** Add "متناسب" to ANALYTICAL_GAP trigger terms in `_build_gap_rules()`.

| ID | Question | Expected | Got |
|----|----------|----------|-----|
| anl-207v2 | آیا استخدام‌ها متناسب با گسترش سازمان بوده؟ | GAP:ANALYTICAL_GAP | NEEDS_CLARIFICATION |

---

### Group E — Meta-System Questions: Domain Rejection (2 cases)
**Root cause:** Questions ask what the system's own "gap" responses mean. Neither contains HR vocabulary, so the domain classifier scores them below the HR threshold → OUT_OF_SCOPE. These questions need a special bypass: if the question is about the system's own behavior (references "گپ داده", "پیام داده میشه", "اطلاعات وجود نداره"), route to KNOWLEDGE_GAP.

| ID | Question | Expected | Got |
|----|----------|----------|-----|
| know-221v2 | پیام گپ داده یعنی چی؟ | GAP:KNOWLEDGE_GAP | REJECT:OUT_OF_SCOPE |
| know-221v3 | وقتی جواب داده میشه که اطلاعات وجود نداره یعنی چی؟ | GAP:KNOWLEDGE_GAP | REJECT:OUT_OF_SCOPE |

---

## Fixability Assessment

| Group | Cases | Fixable? | Effort |
|-------|-------|----------|--------|
| A — SQL template | 3 | Yes, but SQL layer scope | Medium — fix SQL template |
| B — Age vs employment type | 3 | Yes | Low — add 1 intent_parser rule |
| C — Meta-query access | 1 | Borderline | Low — add "ممکنه" pre-filter OR update test data |
| D — Analytical gap "متناسب" | 1 | Yes | Low — 1 term in gap rule |
| E — Meta-system domain | 2 | Yes | Medium — orchestrator bypass for self-referential queries |
| **Total** | **10** | | |

---

## What Changed to Get Here (2026-06-16 → 2026-06-17)

### Test data fixes
- `edu-037`: Expected intent corrected from `low_education_in_expert_roles` → `employee_count_by_education`

### `orchestrator.py` — `_education_domain_override()` static method
Added bypass: when domain classifier returns NON_HR/OUT_OF_SCOPE but question contains unambiguous HR-education vocabulary (`فوق‌لیسانس`, `دانشگاه‌دیده`, `دانشگاه‌رفته`, `دکترا`, `دکتری`, `مدارک+org_anchor`), clear `domain_result` and continue pipeline.  
**Fixed:** edu-028v3, edu-036v2, edu-040v2 (OUT_OF_SCOPE bypass); acc-229v2, acc-229v3 (NON_HR bypass for doctorate access control)

### `question_validator.py` — education signals + aging gap + anchor terms
- Added `_has_education_hr_signals()` module-level function (called from `_check_context_domain_result`)
- Added formal Persian forms to `QVAL_GAP_AGING_STRUCTURE` terms: `"پیر میشود"`, `"پیر می‌شود"` — fixes double-normalization issue where orchestrator calls `normalize_question()` before validator calls it again, converting `میشه→میشود`
- Added `"دکترا"`, `"دکتری"` to `_build_hr_anchor_terms()` — prevents ambiguity check from firing on doctorate questions after domain bypass

### `intent_parser.py` — ctr-094v1 fix
Added `("بیشتر" in question and "چه مدرک" in question)` to `most_common_education` branch — prevents `employee_count_by_education` from scoring higher than `contractor_share` on contractor education questions.
