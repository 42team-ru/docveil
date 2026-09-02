"""Проверка обезличенных артефактов на утечки исходных данных (T1.8)."""

from masker.validate.agent import ValidateAgent
from masker.validate.parts import DocPart, docx_parts, pdf_parts

__all__ = ["DocPart", "ValidateAgent", "docx_parts", "pdf_parts"]
