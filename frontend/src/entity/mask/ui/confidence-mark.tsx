import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

/** Порог, ниже которого уверенность модели требует внимания оператора. */
const LOW_CONFIDENCE = 0.6;

/** Уверенность модели: обычная — вторичным текстом, низкая — красным чипом. */
export function ConfidenceMark({ value }: { value: number }) {
  const formatted = value.toFixed(2);

  if (value < LOW_CONFIDENCE) {
    return <Token size="sm" color="red" label={formatted} />;
  }

  return (
    <Text type="supporting" hasTabularNumbers>
      {formatted}
    </Text>
  );
}
