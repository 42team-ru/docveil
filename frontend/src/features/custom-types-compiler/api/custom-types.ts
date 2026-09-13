import {
  compileTypesApiCustomTypesCompilePost,
  answerQuestionsApiCustomTypesCompileThreadIdAnswersPost,
} from "../../../shared/api/generated/core/custom-types/custom-types";

export type { CompileResponse, CompiledTypeOut, CompileQuestionOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";

export async function compileType(objectName: string, description: string) {
  const response = await compileTypesApiCustomTypesCompilePost({
    object_name: objectName,
    descriptions: [description],
  });
  if (response.status !== 200) throw new Error("Не удалось запустить компиляцию");
  return response.data;
}

export async function answerCompilerQuestions(
  threadId: string,
  answers: Record<string, string>,
) {
  const response = await answerQuestionsApiCustomTypesCompileThreadIdAnswersPost(threadId, { answers });
  if (response.status !== 200) throw new Error("Не удалось отправить ответы");
  return response.data;
}
