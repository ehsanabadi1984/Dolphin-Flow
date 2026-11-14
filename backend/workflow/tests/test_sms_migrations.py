from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SMSProviderRegistryMigrationTests(TransactionTestCase):
    migrate_from = ("workflow", "0080_smsdelivery_last_queued_at")
    migrate_to = ("workflow", "0081_smsdelivery_message_source_and_more")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.old_apps = executor.loader.project_state([self.migrate_from]).apps

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = MigrationExecutor(connection).loader.project_state(
            [self.migrate_to]
        ).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_sms_registry_schema_is_created_without_seeded_secrets(self):
        delivery = self.apps.get_model("workflow", "SMSDelivery")
        provider = self.apps.get_model("workflow", "SMSProviderConfiguration")
        revision = self.apps.get_model("workflow", "SMSProviderConfigRevision")
        template = self.apps.get_model("workflow", "SMSTemplate")

        delivery_fields = {field.name for field in delivery._meta.get_fields()}
        self.assertTrue(
            {"message_source", "provider_code_snapshot", "rendered_message",
             "provider_revision", "template"}.issubset(delivery_fields)
        )
        self.assertEqual(provider.objects.count(), 0)
        self.assertEqual(revision.objects.count(), 0)
        self.assertEqual(template.objects.count(), 0)

    def test_pre_registry_schema_does_not_contain_registry_fields(self):
        delivery = self.old_apps.get_model("workflow", "SMSDelivery")
        old_fields = {field.name for field in delivery._meta.get_fields()}
        self.assertNotIn("rendered_message", old_fields)
        self.assertNotIn("provider_revision", old_fields)
