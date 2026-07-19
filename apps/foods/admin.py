"""
The food back-office — Django's killer feature, earned in ~20 lines.

Add a food, fix a calorie value, mark verified — live in the Next.js
app's search instantly (same table). Staff-only by Django default.
"""

from django.contrib import admin

from .models import Food


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "name_hindi",
        "category",
        "calories_per_100g",
        "protein_per_100g",
        "default_unit",
        "default_grams",
        "is_verified",
    )
    list_editable = ("is_verified",)
    search_fields = ("name", "name_hindi", "category")
    list_per_page = 50
    readonly_fields = ("id", "created_at")
    # NOTE: no list_filter on `source` — it's a Postgres enum column and
    # text-parameter comparisons don't implicitly cast (see PgEnumField).
