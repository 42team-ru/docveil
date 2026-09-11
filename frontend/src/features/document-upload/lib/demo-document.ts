/** Публичный учебный договор: в нём нет рабочих персональных данных. */
const DEMO_DOCUMENT_URL = "/test.docx";
const DEMO_DOCUMENT_TYPE =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export const DEMO_DOCUMENT_NAME = "Учебный договор — пример.docx";

/**
 * Загружает учебный договор как обычный `File`, чтобы он прошёл ровно тот же
 * путь, что и документ оператора.
 */
export async function loadDemoDocument(
  fetchDocument: (input: string) => Promise<Response> = fetch,
): Promise<File> {
  const response = await fetchDocument(DEMO_DOCUMENT_URL);
  if (!response.ok) {
    throw new Error("Не удалось загрузить учебный договор");
  }

  return new File([await response.blob()], DEMO_DOCUMENT_NAME, {
    type: DEMO_DOCUMENT_TYPE,
    lastModified: 0,
  });
}
