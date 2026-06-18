import factory
from django.contrib.auth import get_user_model

from apps.contacts.models import Contact
from apps.contacts.choices import ContactType, ContactRole, ContactSource

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user_{n}")
    email = factory.Sequence(lambda n: f"user_{n}@bricka.com")
    is_active = True


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact

    full_name = factory.Sequence(lambda n: f"Contacto {n}")
    contact_type = ContactType.PERSON
    email = factory.Sequence(lambda n: f"contacto_{n}@email.com")
    source = ContactSource.DIRECT
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)