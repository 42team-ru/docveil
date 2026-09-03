import { Token } from "@astryxdesign/core/Token";

import type { DocumentFormat } from "../model/types";

const FORMAT_COLOR: Record<DocumentFormat, "red" | "blue" | "green"> = {
  PDF: "red",
  DOCX: "blue",
  XLSX: "green",
};

/** Чип формата файла. Цвет закреплён за форматом, чтобы список читался бегло. */
export function FormatToken({
  format,
  size = "sm",
}: {
  format: DocumentFormat;
  size?: "sm" | "md";
}) {
  return <Token size={size} color={FORMAT_COLOR[format]} label={format} />;
}
