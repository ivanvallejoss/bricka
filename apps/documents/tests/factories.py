import factory

from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.documents.models import Document


class DocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Document

    contact = factory.SubFactory(ContactFactory)
    original_filename = factory.Sequence(lambda n: f"documento_{n}.pdf")
    r2_key = factory.Sequence(lambda n: f"docs/documento_{n}.pdf")
    content_type = "application/pdf"
    file_size = 1024
    description = ""
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)