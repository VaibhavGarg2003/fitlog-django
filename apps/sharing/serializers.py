"""
Sharing serializers — the Zod of DRF (same trust-boundary job).

Only the CREATE input needs validation; responses are shaped by hand in
views.py (camelCase, to match the FitLog API conventions the Next.js
client already speaks).
"""

from rest_framework import serializers

from .models import ShareLink


class CreateShareLinkSerializer(serializers.Serializer):
    # D3 ships template sharing only; kind stays in the model so
    # NUTRITION_DAY / WORKOUT_SESSION can arrive without a migration.
    kind = serializers.ChoiceField(choices=[ShareLink.Kind.WORKOUT_TEMPLATE])
    templateId = serializers.CharField(max_length=64)
    # Optional custom title; defaults to the template's name server-side.
    title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    expiresInDays = serializers.IntegerField(
        required=False, min_value=1, max_value=365, default=90
    )
