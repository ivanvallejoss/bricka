def categorize_document(content_type: str) -> str:
    """
    Categoría visual para el template.
    Retorna: 'image' | 'pdf' | 'word' | 'other'

    Necesario porque Django templates no soportan `in` para substrings.

    MIME types cubiertos:
    - image/*          → 'image'
    - application/pdf  → 'pdf'
    - application/msword                                                    → 'word' (.doc)
    - application/vnd.openxmlformats-officedocument.wordprocessingml.document → 'word' (.docx)
    """
    if content_type.startswith("image/"):
        return "image"
    if content_type == "application/pdf":
        return "pdf"
    if content_type in (
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return "word"
    return "other"