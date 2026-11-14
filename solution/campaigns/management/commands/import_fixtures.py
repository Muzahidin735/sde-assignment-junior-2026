
import csv
import json

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tenants.models import Tenant
from campaigns.models import Campaign
from leads.models import Lead


class Command(BaseCommand):
    help = "Import tenants, campaigns, and leads from assignment fixtures."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixtures-dir",
            type=str,
            help="Path to the directory containing campaigns.json and lead CSV files.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        fixtures_dir = options["fixtures_dir"]

        if fixtures_dir:
            fixtures_path = Path(fixtures_dir)
        else:
            fixtures_path = (
                Path(__file__).resolve().parents[4]
                / "assignment-b-workflow"
                / "fixtures"
            )

        config_path = fixtures_path / "campaigns.json"

        if not config_path.exists():
            raise CommandError(
                f"Could not find campaigns.json at {config_path}"
            )

        self.stdout.write("Reading campaign configuration...")
        try:
            with config_path.open("r", encoding="utf-8") as file:
                config = json.load(file)
        except json.JSONDecodeError as error:
            raise CommandError(
                f"Invalid JSON in campaigns.json: {error}"
            )

        required_keys = [
            "timezone",
            "retry_policy",
            "webhook_secret",
            "tenants",
            "campaigns",
        ]

        missing_keys = [
            key for key in required_keys if key not in config
        ]

        if missing_keys:
            raise CommandError(
                f"Missing configuration keys: {', '.join(missing_keys)}"
            )

        self.stdout.write(
            self.style.SUCCESS("Campaign configuration loaded successfully.")
        )

        tenants_created = 0
        tenants_updated = 0

        with transaction.atomic():
            for tenant_data in config["tenants"]:
                tenant, created = Tenant.objects.update_or_create(
                    tenant_id=tenant_data["tenant_id"],
                    defaults={
                        "max_concurrent_calls": tenant_data[
                            "max_concurrent_calls"
                        ],
                    },
                )

                if created:
                    tenants_created += 1
                else:
                    tenants_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Tenants imported: {tenants_created} created, "
                f"{tenants_updated} updated."
            )
        )


        campaigns_created = 0
        campaigns_updated = 0

        with transaction.atomic():
            for campaign_data in config["campaigns"]:
                campaign_window = campaign_data["window"]

                try:
                    tenant = Tenant.objects.get(
                        tenant_id=campaign_data["tenant_id"]
                    )
                except Tenant.DoesNotExist:
                    raise CommandError(
                        f"Tenant not found: {campaign_data['tenant_id']}"
                    )

                campaign, created = Campaign.objects.update_or_create(
                    campaign_id=campaign_data["campaign_id"],
                    defaults={
                        "tenant": tenant,
                        "window_start": campaign_window["start"],
                        "window_end": campaign_window["end"],
                        "calling_days": campaign_window["days"],
                        "max_attempts": campaign_data["max_attempts"],
                        "webhook_secret": config["webhook_secret"],
                    },
                )

                if created:
                    campaigns_created += 1
                else:
                    campaigns_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Campaigns imported: {campaigns_created} created, "
                f"{campaigns_updated} updated."
            )
        )

        leads_created = 0
        leads_updated = 0

        for campaign_data in config["campaigns"]:
            csv_path = fixtures_path / campaign_data["leads_file"]

            if not csv_path.exists():
                raise CommandError(
                    f"Lead CSV file not found: {csv_path}"
                )
            try:
                campaign = Campaign.objects.get(
                    campaign_id=campaign_data["campaign_id"]
                )
            except Campaign.DoesNotExist:
                raise CommandError(
                    f"Campaign not found: {campaign_data['campaign_id']}"
                )
            with csv_path.open("r", encoding="utf-8", newline="") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    lead, created = Lead.objects.update_or_create(
                        campaign=campaign,
                        lead_id=row["lead_id"],
                        defaults={
                            "phone": row["phone"],
                            "customer_name": row["customer_name"],
                        },
                    )

                    if created:
                        leads_created += 1
                    else:
                        leads_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Leads imported: {leads_created} created, "
                f"{leads_updated} updated."
            )
        )


