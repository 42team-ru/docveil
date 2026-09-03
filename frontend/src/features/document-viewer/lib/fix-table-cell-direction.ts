/**
 * Обходит баг docx-preview@0.4.0: для `w:textDirection w:val="lrTb"`
 * (обычное горизонтальное письмо, левый край → правый, сверху вниз) библиотека
 * ошибочно ставит `writing-mode: vertical-lr` вместо `horizontal-tb`
 * (node_modules/docx-preview/dist/docx-preview.js:2340-2343, directionMap).
 * Из трёх значений OOXML только `lrTb` — «обычный» режим; `tbRl`/`btLr` —
 * настоящая вертикаль и корректно превращаются в `vertical-rl`. Библиотека
 * никогда не производит `vertical-lr` для двух других значений, поэтому по
 * самому этому writing-mode безошибочно узнаётся именно баг, а не настоящая
 * вертикальная ячейка (которых в этом продукте — русские юридические
 * документы — практически не бывает).
 *
 * Последняя опубликованная версия библиотеки — 0.4.0, апстрим-фикса ждать
 * неоткуда; правим ран-тайм результат один раз после рендера.
 */
export function fixTableCellDirection(host: HTMLElement): void {
  const cells = host.querySelectorAll<HTMLElement>("td, th");
  for (const cell of cells) {
    if (cell.style.writingMode === "vertical-lr") {
      cell.style.writingMode = "";
      cell.style.transform = "";
    }
  }
}
