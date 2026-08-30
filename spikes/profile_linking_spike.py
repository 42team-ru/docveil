"""Спайк: связывание реквизитов с их владельцем без модели.

Вопрос, который решает ProfileAgent: слой правил нашёл «ИНН 123» и «ИНН 456»,
слой NER нашёл «Ромашка» и «Бумашка» — кто чей?

Ответ: в договорах реквизиты расположены не случайно. Работают два
структурных сигнала, и оба видны без всякой модели:

  1. ОДИН СЕГМЕНТ. «ООО «Ромашка», ИНН 123, КПП 456» — реквизит стоит
     в том же абзаце, что и название. Сильнейший сигнал, срабатывает
     в преамбуле любого договора.
  2. БЛОК РЕКВИЗИТОВ. Заголовок «Реквизиты Поставщика» открывает секцию,
     и всё до следующего заголовка принадлежит названной стороне.

LLM подключается только к остатку — к тому, что не легло ни в один блок.
"""

from __future__ import annotations

import re
import sys

sys.path.insert(0, "src")

from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter  # noqa: E402

from masker.detect.rules import detect_by_rules  # noqa: E402
from masker.ingest.docx_ingest import ingest_docx  # noqa: E402
from masker.model import Entity, EntityType, Party, Profile, Source  # noqa: E402

#: Типы, вокруг которых собирается профиль. Остальные к ним приписываются.
ANCHOR_TYPES = {EntityType.ORG_NAME}

#: Заголовок секции реквизитов: «Реквизиты Поставщика», «Реквизиты сторон».
SECTION_RE = re.compile(r"реквизит\w*\s+(поставщик\w*|покупател\w*|сторон)", re.I)

#: Роль из преамбулы: «именуемое в дальнейшем «Поставщик»».
ROLE_RE = re.compile(r"именуем\w*\s+в\s+дальнейшем\s+[«\"]?(поставщик|покупател\w*)", re.I)

ROLE_MAP = {"поставщик": Party.SUPPLIER, "покупател": Party.BUYER}


def _party_from(text: str, pattern: re.Pattern[str]) -> Party:
    m = pattern.search(text)
    if not m:
        return Party.UNKNOWN
    word = m.group(1).lower()
    for prefix, party in ROLE_MAP.items():
        if word.startswith(prefix):
            return party
    return Party.UNKNOWN


def detect_orgs(doc) -> list[Entity]:
    """Организации через NER, с обратным пересчётом смещений в сегменты."""
    seg, emb = Segmenter(), NewsEmbedding()
    ner = NewsNERTagger(emb)

    # doc.text() склеивает сегменты через \n — значит смещение восстановимо.
    offsets, pos = [], 0
    for s in doc.segments:
        offsets.append((pos, pos + len(s.text), s.order))
        pos += len(s.text) + 1

    d = Doc(doc.text())
    d.segment(seg)
    d.tag_ner(ner)

    out: list[Entity] = []
    for span in d.spans:
        if span.type != "ORG":
            continue
        # Мусор NER: заголовки и слова-роли организациями не являются.
        if span.text.isupper() or span.text.lower() in ("поставщик", "покупатель"):
            continue
        for start, end, order in offsets:
            if start <= span.start < end:
                out.append(
                    Entity(
                        type=EntityType.ORG_NAME,
                        text=span.text,
                        segment_order=order,
                        start=span.start - start,
                        end=min(span.stop, end) - start,
                        source=Source.NER,
                        confidence=0.9,
                        normalized=re.sub(r"[^\w]", "", span.text).casefold(),
                    )
                )
                break
    return out


def build_profiles(doc, entities: list[Entity]) -> tuple[list[Profile], list[Entity]]:
    """Связать реквизиты с владельцами. Возвращает профили и осадок."""
    by_order = sorted(entities, key=lambda e: (e.segment_order, e.start))
    anchors = [e for e in by_order if e.type in ANCHOR_TYPES]

    profiles: dict[str, Profile] = {}
    for i, a in enumerate(anchors, 1):
        pid = f"p{i}"
        seg_text = doc.segments[a.segment_order].text
        a.profile_id = pid
        profiles[pid] = Profile(
            id=pid,
            party=_party_from(seg_text, ROLE_RE),   # сигнал преамбулы
            display_name=a.text,
            members=[a],
        )

    # Секции реквизитов: заголовок задаёт владельца до следующего заголовка.
    section_owner: dict[int, Party] = {}
    current = Party.UNKNOWN
    for s in doc.segments:
        m = SECTION_RE.search(s.text)
        if m:
            current = _party_from(s.text, SECTION_RE)
        section_owner[s.order] = current

    leftover: list[Entity] = []
    for e in by_order:
        if e.type in ANCHOR_TYPES:
            continue
        # Сигнал 1 — тот же сегмент, что и название.
        same = [a for a in anchors if a.segment_order == e.segment_order]
        if same:
            target = max(
                (a for a in same if a.start <= e.start), key=lambda a: a.start, default=same[0]
            )
            e.profile_id = target.profile_id
            profiles[target.profile_id].members.append(e)
            continue
        # Сигнал 2 — блок реквизитов named-стороны.
        owner = section_owner.get(e.segment_order, Party.UNKNOWN)
        match = [p for p in profiles.values() if p.party is owner and owner is not Party.UNKNOWN]
        if match:
            e.profile_id = match[0].id
            match[0].members.append(e)
            continue
        leftover.append(e)

    return list(profiles.values()), leftover


def main() -> int:
    doc = ingest_docx("fixtures/labeled/contract_01.docx")
    entities = detect_by_rules(doc.segments) + detect_orgs(doc)
    profiles, leftover = build_profiles(doc, entities)

    for p in profiles:
        role = {Party.SUPPLIER: "ПОСТАВЩИК", Party.BUYER: "ПОКУПАТЕЛЬ"}.get(p.party, "?")
        print(f"\n╔═ {p.display_name}  [{role}]")
        for m in sorted(p.members, key=lambda e: (e.segment_order, e.start)):
            if m.type in ANCHOR_TYPES:
                continue
            where = doc.segments[m.segment_order].anchor.label
            print(f"║   {m.type.value:<14} {m.text:<26} ({where})")

    print(f"\n── не привязано (сюда идёт LLM): {len(leftover)}")
    for e in leftover:
        print(f"     {e.type.value:<14} {e.text}")

    ok = {
        "профилей ровно 2": len(profiles) == 2,
        "у обоих определена роль": all(p.party is not Party.UNKNOWN for p in profiles),
        "ИНН поставщика привязан верно": any(
            m.text == "3662103003" for p in profiles if p.party is Party.SUPPLIER for m in p.members
        ),
        "ИНН покупателя привязан верно": any(
            m.text == "7707083893" for p in profiles if p.party is Party.BUYER for m in p.members
        ),
        "счёт ушёл поставщику": any(
            m.type is EntityType.BANK_ACCOUNT
            for p in profiles
            if p.party is Party.SUPPLIER
            for m in p.members
        ),
        "LLM не потребовался": not leftover,
    }
    print()
    for name, good in ok.items():
        print(f"  {'ok  ' if good else 'ПЛОХО'}  {name}")
    passed = all(ok.values())
    print("\nСПАЙК ПРОЙДЕН" if passed else "\nСПАЙК ПРОВАЛЕН")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
