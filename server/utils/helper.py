def parse_4step_response(text: str):
    """
    Parse STRICT 4-step LLM output into structured fields.
    """
    sections = {}
    current = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.endswith(":"):
            current = line[:-1]
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"

    return {k: v.strip() for k, v in sections.items()}