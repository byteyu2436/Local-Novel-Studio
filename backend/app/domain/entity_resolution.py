import re
from dataclasses import dataclass
from enum import StrEnum

_ALIAS_MARKER = re.compile(r"(?:又名|又称|称作|昵称|外号)")


class EntityKind(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    ORGANIZATION = "organization"


class ResolutionAction(StrEnum):
    MERGED = "merged"
    CREATED = "created"
    CANDIDATE = "candidate"


@dataclass(frozen=True)
class EntityRef:
    id: str
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ResolutionMatch:
    action: ResolutionAction
    entity_id: str | None
    candidate_ids: tuple[str, ...]
    reason: str


def normalize_name(value: str) -> str:
    return "".join(value.split())


def aliases_from_phrase(phrase: str) -> list[str]:
    """Pull nicknames from 又名 / 称作 / 昵称 phrases. The phrase is not a fact."""

    found: list[str] = []
    for part in _ALIAS_MARKER.split(phrase):
        cleaned = part.strip(" ，,。;；:：")
        if not cleaned or _ALIAS_MARKER.search(cleaned):
            continue
        nickname = cleaned.split("，")[0].split(",")[0].strip()
        if nickname:
            found.append(nickname)
    if not found:
        return []
    return found[1:] if len(found) > 1 else found


def classify_mention(
    name: str, aliases: list[str], entities: list[EntityRef], *, phrase: str = ""
) -> ResolutionMatch:
    """Match a mention. Same name alone never merges two people."""

    mention_aliases = [item for item in (*aliases, *aliases_from_phrase(phrase)) if item.strip()]
    alias_keys = {normalize_name(item) for item in mention_aliases}
    mention = normalize_name(name)
    known_alias = [
        entity
        for entity in entities
        if mention and mention in _alias_keys(entity) and mention != normalize_name(entity.name)
    ]
    if len(known_alias) == 1:
        return ResolutionMatch(ResolutionAction.MERGED, known_alias[0].id, (), "exact_alias")
    if len(known_alias) > 1:
        return _candidate(known_alias, "ambiguous_alias")

    pointed = [
        entity
        for entity in entities
        if alias_keys & ({normalize_name(entity.name)} | _alias_keys(entity))
    ]
    if len(pointed) == 1:
        return ResolutionMatch(ResolutionAction.MERGED, pointed[0].id, (), "alias_overlap")
    if len(pointed) > 1:
        return _candidate(pointed, "ambiguous_alias")

    same_name = [entity for entity in entities if normalize_name(entity.name) == mention]
    if len(same_name) == 1 and alias_keys:
        return ResolutionMatch(ResolutionAction.MERGED, same_name[0].id, (), "explicit_alias")
    if same_name:
        return _candidate(same_name, "same_name")

    partial = [
        entity
        for entity in entities
        if mention
        and (mention in normalize_name(entity.name) or normalize_name(entity.name) in mention)
    ]
    if partial:
        return _candidate(partial, "low_confidence")
    return ResolutionMatch(ResolutionAction.CREATED, None, (), "no_match")


def _alias_keys(entity: EntityRef) -> set[str]:
    return {normalize_name(item) for item in entity.aliases if normalize_name(item)}


def _candidate(entities: list[EntityRef], reason: str) -> ResolutionMatch:
    return ResolutionMatch(
        ResolutionAction.CANDIDATE,
        None,
        tuple(entity.id for entity in entities),
        reason,
    )
