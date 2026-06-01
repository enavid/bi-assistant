from __future__ import annotations

from app.models.domain import Project


def assemble_prompt(project: Project, question: str) -> str:
    """
    Assemble the final prompt string from a Project.

    The output_format field is a template that references sections by their id:
        {section_id_1}\\n\\n{section_id_2}\\n\\nQUESTION:\\n{question}\\n\\nSQL:

    If output_format is empty, sections are joined with double newlines in order.
    The special placeholder {question} is always replaced with the actual question.
    """
    section_map = {s.id: s.content for s in project.sections}

    if project.output_format:
        result = project.output_format
        for section_id, content in section_map.items():
            result = result.replace(f"{{{section_id}}}", content)
        result = result.replace("{question}", question)
        return result

    parts = [
        s.content
        for s in sorted(project.sections, key=lambda s: s.order)
        if s.content.strip()
    ]
    parts.append(f"QUESTION:\n{question}\n\nSQL:")
    return "\n\n".join(parts)
