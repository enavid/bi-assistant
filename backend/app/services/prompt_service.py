from __future__ import annotations

from app.db.models import Project


def assemble_prompt(project: Project, question: str) -> str:
    """
    Assemble the final prompt from a Project's sections and output_format.

    output_format references sections by their id: {section_id}.
    The special placeholder {question} is always replaced with the question.

    If output_format is empty, sections are joined in order with double newlines,
    followed by a default QUESTION/SQL footer.
    """
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
