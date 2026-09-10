import { Badge } from "@astryxdesign/core/Badge";
import { Divider } from "@astryxdesign/core/Divider";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

import { piiTypeLabel } from "../../../entity/pii/model/pii-type-dict";
import type {
  MaskGroupRecord,
  PartyProfile,
} from "../../../entity/pii/model/types";

type ProfilesTabProps = {
  profiles: PartyProfile[];
  /** Группы плана — из них берётся маркер, вписанный в документ. */
  groups?: MaskGroupRecord[];
};

/**
 * Цвет стороны. Роли в документах открытые («Заказчик», «Исполнитель»,
 * «Поставщик», …), поэтому цвет назначается по порядку профилей, а не по
 * зашитому словарю ролей: закрытый список здесь всё равно рано или поздно
 * встретит роль, которой в нём нет.
 */
const PROFILE_COLORS = ["blue", "purple", "green", "orange"] as const;

/**
 * Маркер конкретного реквизита. Ищем в плане группу того же профиля и типа;
 * если таких групп несколько, маркер не показываем вовсе — угадывать номер
 * (`[ЗАКАЗЧИК-ИНН-2]`) означало бы показать оператору не то, что вписано в
 * документ.
 */
function markerFor(
  groups: MaskGroupRecord[],
  profileId: string,
  type: string,
): string | null {
  const matches = groups.filter(
    (group) => group.profileId === profileId && group.type === type,
  );
  return matches.length === 1 ? matches[0].marker : null;
}

/** Вкладка «Профили» — реквизиты, сгруппированные по стороне договора. */
export function ProfilesTab({ profiles, groups = [] }: ProfilesTabProps) {
  if (profiles.length === 0) {
    return (
      <EmptyState
        isCompact
        title="Профили не найдены"
        description="Агент не извлёк ни одной стороны договора."
      />
    );
  }

  return (
    <VStack gap={0} isScrollable height="100%">
      {profiles.map((profile, index) => (
        <Section
          key={profile.id}
          padding={4}
          dividers={index > 0 ? ["top"] : []}
        >
          <VStack gap={3}>
            <HStack gap={2} vAlign="center">
              <Token
                size="sm"
                color={PROFILE_COLORS[index % PROFILE_COLORS.length]}
                label={profile.roleTitle || profile.markerLabel}
              />
              <Badge variant="neutral" label={profile.members.length} />
            </HStack>

            <VStack gap={3}>
              {profile.members.map((member) => {
                const marker = markerFor(groups, profile.id, member.type);

                return (
                  <VStack key={member.ref} gap={0.5}>
                    <HStack gap={2} vAlign="end" width="100%">
                      <Text type="supporting" color="secondary" size="sm">
                        {piiTypeLabel(member.type)}
                      </Text>
                      <StackItem size="fill">
                        <Divider />
                      </StackItem>
                      <Text type="code" color="secondary" size="sm">
                        {marker ?? member.ref}
                      </Text>
                    </HStack>
                    <Text type="body" weight="medium" textWrap="pretty">
                      {member.text}
                    </Text>
                  </VStack>
                );
              })}
            </VStack>
          </VStack>
        </Section>
      ))}
    </VStack>
  );
}
