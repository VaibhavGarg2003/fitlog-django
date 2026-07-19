"""
Food — managed=False mapping of FitLog's `foods` table.

Prisma owns this schema (created in the very first FitLog migration);
Django reads and writes ROWS so the Admin becomes a real back-office.
Before this app existed, fixing one food meant editing a TypeScript seed
file and re-running scripts. Now it's a form.
"""

import uuid

from django.db import models

from apps.sharing.models import PgEnumField


def new_id() -> str:
    # Prisma generates uuid() CLIENT-side — the column has no DB default,
    # so Django must supply ids for rows it creates.
    return str(uuid.uuid4())


class Food(models.Model):
    id = models.CharField(primary_key=True, max_length=64, default=new_id)
    name = models.CharField(max_length=255)
    # null=True on the next two mirrors Prisma's nullable TEXT columns —
    # the schema is Prisma's; Django must match it, not restyle it.
    name_hindi = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    # Postgres enum "FoodSource": INDB | IFCT | USDA | MANUAL
    source = PgEnumField(
        enum_name="FoodSource",
        max_length=16,
        choices=[(x, x) for x in ("INDB", "IFCT", "USDA", "MANUAL")],
        default="MANUAL",
    )
    category = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    calories_per_100g = models.FloatField()
    protein_per_100g = models.FloatField()
    carbs_per_100g = models.FloatField()
    fat_per_100g = models.FloatField()
    fiber_per_100g = models.FloatField(null=True, blank=True)
    default_unit = models.CharField(max_length=20, default="g")
    default_quantity = models.FloatField(default=100)
    default_grams = models.FloatField(default=100)
    restaurant_multiplier = models.FloatField(default=1.5)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = "foods"
        ordering = ["name"]

    def __str__(self):
        return self.name
