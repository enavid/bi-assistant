from __future__ import annotations

from app.domain.entities import Project


class PromptAssembler:
    """
    Assembles the final prompt string from a Project's sections and output_format.
    output_format references sections by their id: {section_id}.
    {question} is always replaced with the user question.
    If output_format is empty, sections are joined in order.
    """

    def assemble(self, project: Project, question: str) -> str:
        section_map = {s.id: s.content for s in project.sections}

        if project.output_format:
            result = project.output_format
            for sid, content in section_map.items():
                result = result.replace(f"{{{sid}}}", content)
            return result.replace("{question}", question)

        parts = [
            s.content
            for s in sorted(project.sections, key=lambda s: s.order)
            if s.content.strip()
        ]
        parts.append(f"QUESTION:\n{question}\n\nSQL:")
        return "\n\n".join(parts)
