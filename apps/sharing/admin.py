from django.contrib import admin

from .models import ShareLink


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    """Back-office visibility into shares (abuse checks, support)."""

    list_display = (
        "slug",
        "kind",
        "title",
        "owner_user_id",
        "view_count",
        "created_at",
        "revoked_at",
    )
    search_fields = ("slug", "title", "owner_user_id")
    readonly_fields = ("id", "slug", "payload", "view_count", "created_at")
    # No list_filter on enum-ish fields; no adds from admin (shares are
    # created by users through the API, admin is read/revoke only).

    def has_add_permission(self, request):
        return False
