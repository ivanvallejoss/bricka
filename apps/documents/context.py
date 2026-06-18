from dataclasses import dataclass

from apps.documents.models import Document


@dataclass
class DocumentContext:
    """
    Documento enriquecido para consumo del template.

    Separa los atributos computados (signed_url, file_category)
    del modelo — evita parchear instancias y hace explícito
    qué datos necesita el template.

    ⚠️ signed_url es temporal — no persistir ni cachear en cliente.
    Generada en cada render de la view.
    """
    document: Document
    signed_url: str
    file_category: str