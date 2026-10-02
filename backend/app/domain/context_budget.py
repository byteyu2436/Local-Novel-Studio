from app.domain.chunking import estimate_tokens
from app.schemas.context import SECTION_TYPES, ContextSection

ESTIMATOR_VERSION = "token-estimator.v1"
BUILDER_VERSION = "context-builder.v1"
PROTECTED_TYPES = frozenset({"locked_facts", "character_state"})


class ContextBudgetError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ContextBudget:
    def __init__(
        self,
        *,
        profile_id: str,
        max_context_tokens: int,
        input_budget: int,
        output_reserve: int,
        safety_margin: int,
    ) -> None:
        self.profile_id = profile_id
        self.max_context_tokens = max_context_tokens
        self.input_budget = input_budget
        self.output_reserve = output_reserve
        self.safety_margin = safety_margin


def estimate_section_tokens(text: str) -> int:
    return estimate_tokens(text)


def budget_for_profile(profile) -> ContextBudget:
    """Input budget follows the model profile. Output reserve is always kept."""

    maximum = int(profile.context_max_product_limit)
    reserve = min(4096, max(1024, maximum // 8))
    margin = 256
    room = maximum - reserve - margin
    preferred = int(profile.context_default)
    input_budget = min(preferred, room)
    if maximum < 1 or reserve < 1 or input_budget < 1:
        raise ContextBudgetError(
            "context_budget_exceeded",
            "这个模型配置放不下输出预留，不能组装上下文。",
        )
    if input_budget + reserve + margin > maximum:
        raise ContextBudgetError(
            "context_budget_exceeded",
            "输入和输出预留加起来超过了模型上限。",
        )
    return ContextBudget(
        profile_id=profile.profile_id,
        max_context_tokens=maximum,
        input_budget=input_budget,
        output_reserve=reserve,
        safety_margin=margin,
    )


def reject_if_reserve_exceeds_model(input_tokens: int, budget: ContextBudget) -> None:
    used = input_tokens + budget.output_reserve + budget.safety_margin
    if used > budget.max_context_tokens:
        raise ContextBudgetError(
            "context_budget_exceeded",
            "输入和输出预留加起来超过了模型上限。",
        )


def _protected(section: ContextSection) -> bool:
    return section.locked or section.section_type in PROTECTED_TYPES


def _drop(section: ContextSection, reason: str) -> None:
    section.before_tokens = section.token_estimate
    section.included = False
    section.trimmed_reason = reason
    section.after_tokens = 0
    section.token_estimate = 0


def _total(sections: list[ContextSection]) -> int:
    return sum(item.token_estimate for item in sections if item.included)


def _keep_tail(section: ContextSection, allowed: int) -> None:
    before = section.token_estimate
    if allowed <= 0:
        _drop(section, "recent_text_trimmed")
        return
    text = section.text
    start = len(text)
    while start > 0 and estimate_section_tokens(text[start - 1 :]) <= allowed:
        start -= 1
    suffix = text[start:]
    if not suffix.strip():
        _drop(section, "recent_text_trimmed")
        return
    section.text = suffix
    section.token_estimate = estimate_section_tokens(suffix)
    section.before_tokens = before
    section.after_tokens = section.token_estimate
    section.trimmed_reason = "recent_tail_kept"
    section.checksum = ""


def trim_sections(sections: list[ContextSection], budget: ContextBudget) -> list[ContextSection]:
    """Drop low-value slices until the input budget fits. Locked canon stays."""

    working = [item.model_copy(deep=True) for item in sections]
    while _total(working) > budget.input_budget:
        evidence = [
            item
            for item in working
            if item.included and item.section_type == "retrieved_evidence" and not _protected(item)
        ]
        if not evidence:
            break
        victim = min(evidence, key=lambda item: (item.score or 0, item.source_id))
        _drop(victim, "low_score_evidence")
    while _total(working) > budget.input_budget:
        summaries = [
            item
            for item in working
            if item.included and item.section_type == "global_summary" and not _protected(item)
        ]
        if not summaries:
            break
        for item in summaries:
            compressed = item.compressed_text.strip()
            smaller = estimate_section_tokens(compressed) if compressed else item.token_estimate
            if compressed and smaller < item.token_estimate:
                item.before_tokens = item.token_estimate
                item.text = compressed
                item.token_estimate = smaller
                item.after_tokens = smaller
                item.trimmed_reason = "summary_compressed"
            else:
                _drop(item, "summary_trimmed")
    while _total(working) > budget.input_budget:
        recent = [
            item
            for item in working
            if item.included and item.section_type == "recent_text" and not _protected(item)
        ]
        if len(recent) <= 1:
            break
        victim = min(recent, key=lambda item: (item.recency, item.source_id))
        _drop(victim, "distant_recent_text")
    if _total(working) > budget.input_budget:
        recent = [
            item
            for item in working
            if item.included and item.section_type == "recent_text" and not _protected(item)
        ]
        overflow = _total(working) - budget.input_budget
        for item in recent:
            allowed = max(item.token_estimate - overflow, 0)
            _keep_tail(item, allowed)
            overflow = _total(working) - budget.input_budget
            if overflow <= 0:
                break
    while _total(working) > budget.input_budget:
        optional = [
            item
            for item in working
            if item.included and not _protected(item) and item.section_type != "recent_text"
        ]
        if not optional:
            break
        victim = min(optional, key=lambda item: (item.priority, item.source_id))
        _drop(victim, "low_priority")
    if _total(working) > budget.input_budget:
        raise ContextBudgetError(
            "context_budget_exceeded",
            "关键设定放不进上下文预算，已停止，没有继续生成。",
        )
    reject_if_reserve_exceeds_model(_total(working), budget)
    order = {name: index for index, name in enumerate(SECTION_TYPES)}
    working.sort(key=lambda item: (order[item.section_type], item.source_id))
    return working
