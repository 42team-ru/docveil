import { useReviewStore } from "../../../entity/pii/model/review-store";
import { resolvePaintState } from "./apply-highlights";
import { paintRun } from "./paint-run";

export type SyncTarget = {
  occurrenceId: string;
  groupId: string;
  run: HTMLElement;
};

/**
 * Подписывает уже расставленные метки на изменения стора: решение по группе,
 * выбор строки и режим показа тулбара («Все / Только замены / Оригинал»)
 * перекрашивают раны точечно, без перерендера чужого DOM —
 * `subscribeWithSelector` (см. `entity/pii/model/review-store.ts`) для этого и
 * заведён, документация zustand v5 прямо называет ручные DOM-обновления целевым
 * сценарием. Раны немного (~30), поэтому перекраска всех сразу на любое
 * изменение проще и надёжнее точечного diff — преждевременная оптимизация тут
 * не нужна.
 *
 * Смена выбора ещё и скроллит документ к метке — так работает синхронизация
 * панель → документ. Направление документ → панель не отсюда: клик по метке
 * уже виден (это и есть источник выбора), а раскрытие/скролл нужной строки
 * панели делает `entity/pii/ui/pii-occurrence-item.tsx` и
 * `features/pii-review/ui/pii-group-item.tsx` своим эффектом на `isSelected`.
 */
export function subscribeHighlightSync(targets: SyncTarget[]): () => void {
  const runByOccurrenceId = new Map(targets.map((t) => [t.occurrenceId, t.run]));

  const repaint = () => {
    const state = useReviewStore.getState();
    for (const { occurrenceId, groupId, run } of targets) {
      const decision = state.groupDecisions[groupId] ?? "pending";
      paintRun(
        run,
        resolvePaintState(decision, state.viewMode),
        state.selectedOccurrenceId === occurrenceId,
      );
    }
  };

  repaint();

  const unsubDecisions = useReviewStore.subscribe(
    (state) => state.groupDecisions,
    repaint,
  );
  const unsubSelection = useReviewStore.subscribe(
    (state) => state.selectedOccurrenceId,
    (selectedId) => {
      repaint();
      const run = selectedId ? runByOccurrenceId.get(selectedId) : null;
      // Клик по уже видимой метке в документе — no-op: элемент и так в кадре.
      run?.scrollIntoView({ block: "center", behavior: "smooth" });
    },
  );
  const unsubViewMode = useReviewStore.subscribe(
    (state) => state.viewMode,
    repaint,
  );

  return () => {
    unsubDecisions();
    unsubSelection();
    unsubViewMode();
  };
}
