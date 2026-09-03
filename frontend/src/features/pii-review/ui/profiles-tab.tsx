import { Section } from "@astryxdesign/core/Section";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { Divider } from "@astryxdesign/core/Divider";
import { Badge } from "@astryxdesign/core/Badge";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { maskFragments } from "../../../entity/mask/model/fixtures";

/** Профиль стороны договора — сгруппированные персональные данные. */
type Profile = {
  side: string;
  color: "blue" | "purple" | "default";
  fields: Array<{ type: string; value: string; marker: string }>;
};

function buildProfiles(): Profile[] {
  const sides: Record<string, Profile> = {};

  for (const f of maskFragments) {
    const side = f.side ?? "общие";
    if (!sides[side]) {
      sides[side] = {
        side,
        color: side === "поставщик" ? "blue" : side === "покупатель" ? "purple" : "default",
        fields: [],
      };
    }
    sides[side].fields.push({ type: f.type, value: f.original, marker: f.marker });
  }

  return Object.values(sides);
}

const profiles = buildProfiles();

/** Вкладка «Профили» — персональные данные, сгруппированные по стороне договора. */
export function ProfilesTab() {
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
      {profiles.map((profile, idx) => (
        <Section key={profile.side} padding={4} dividers={idx > 0 ? ["top"] : []}>
          <VStack gap={3}>
            <HStack gap={2} vAlign="center">
              <Token size="sm" color={profile.color} label={profile.side} />
              <Badge variant="neutral" label={profile.fields.length} />
            </HStack>

            <VStack gap={3}>
              {profile.fields.map((field) => (
                <VStack key={field.marker} gap={0.5}>
                  <HStack gap={2} vAlign="end" width="100%">
                    <Text type="supporting" color="secondary" size="sm">
                      {field.type}
                    </Text>
                    <div
                      style={{
                        flex: 1,
                        borderBottom: "1px dotted var(--color-border-emphasized)",
                        marginBottom: 4,
                      }}
                    />
                    <Text type="code" color="secondary" size="sm">
                      {field.marker}
                    </Text>
                  </HStack>
                  <Text type="body" weight="medium" textWrap="pretty">
                    {field.value}
                  </Text>
                </VStack>
              ))}
            </VStack>
          </VStack>
        </Section>
      ))}
    </VStack>
  );
}
