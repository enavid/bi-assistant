from __future__ import annotations

from app.domain.entities import GenerationResult, Project
from app.domain.interfaces import ILLMClient, IPromptAssembler


class GenerateSQLUseCase:
    """
    Generates SQL from a user question using a project's prompt template.
    Depends on ILLMClient and IPromptAssembler — no infrastructure import.
    """

    def __init__(self, llm: ILLMClient, assembler: IPromptAssembler) -> None:
        self._llm = llm
        self._assembler = assembler

    async def execute(
        self,
        question: str,
        project: Project | None = None,
        model: str | None = None,
    ) -> GenerationResult:
        if project:
            prompt = self._assembler.assemble(project, question)
        else:
            prompt = f"Generate a PostgreSQL SELECT query for: {question}\n\nSQL:"

        return await self._llm.generate(prompt, model)
