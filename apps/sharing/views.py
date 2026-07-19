"""
Share-links API — the five endpoints (doc 06 contract):

  POST   /api/share-links            (JWT)     create snapshot → slug
  GET    /api/share-links            (JWT)     my links
  GET    /api/share-links/<slug>     (PUBLIC)  the shared page's data
  DELETE /api/share-links/<slug>     (JWT)     revoke (owner only)
  POST   /api/share-links/<slug>/copy (JWT)    import snapshot into MY account

Design rules carried over from the FitLog codebase:
- Owner-scoped lookups answer 404, never 403 (don't reveal existence).
- Revoked/expired links answer 410 Gone — "was here, deliberately isn't".
- The snapshot payload is derived SERVER-SIDE from the template row —
  the client sends only an id it owns; it cannot fabricate content.
"""

import uuid

from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import FitLogUser, ShareLink, WorkoutTemplate
from .serializers import CreateShareLinkSerializer


def _first_name(user_id: str) -> str:
    row = FitLogUser.objects.filter(id=user_id).only("name").first()
    if not row or not row.name:
        return ""
    return row.name.split()[0]


def _link_state(link: ShareLink) -> str:
    """'ok' | 'gone'. Revoked or past expiry both read as gone (410)."""
    if link.revoked_at is not None:
        return "gone"
    if link.expires_at is not None and link.expires_at <= timezone.now():
        return "gone"
    return "ok"


def _serialize_own_link(link: ShareLink) -> dict:
    return {
        "slug": link.slug,
        "kind": link.kind,
        "title": link.title,
        "viewCount": link.view_count,
        "createdAt": link.created_at.isoformat(),
        "expiresAt": link.expires_at.isoformat() if link.expires_at else None,
        "revoked": link.revoked_at is not None,
    }


class ShareLinkListCreateView(APIView):
    """POST create (throttled) + GET list-mine."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "share-create"

    def get_throttles(self):
        # Throttle CREATION only — listing your own links is cheap.
        if self.request.method != "POST":
            return []
        return super().get_throttles()

    def get(self, request):
        links = ShareLink.objects.filter(owner_user_id=request.user.id)[:100]
        return Response({"links": [_serialize_own_link(x) for x in links]})

    def post(self, request):
        serializer = CreateShareLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Owner-scoped template lookup — someone else's template id is a 404.
        template = WorkoutTemplate.objects.filter(
            id=data["templateId"], user_id=request.user.id
        ).first()
        if template is None:
            return Response(
                {"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # THE SNAPSHOT — frozen now; later edits to the template stay private.
        payload = {
            "templateName": template.name,
            "splitType": template.split_type,
            "exercises": template.exercises,
        }

        link = ShareLink.objects.create(
            owner_user_id=request.user.id,
            owner_first_name=_first_name(request.user.id),
            kind=data["kind"],
            title=(data.get("title") or template.name)[:120],
            payload=payload,
            expires_at=timezone.now() + timezone.timedelta(days=data["expiresInDays"]),
        )

        return Response(
            _serialize_own_link(link) | {"slug": link.slug},
            status=status.HTTP_201_CREATED,
        )


class ShareLinkDetailView(APIView):
    """GET public read + DELETE owner revoke — same path, different rules."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]  # the whole point: no login to view
        return super().get_permissions()

    def get_authenticators(self):
        # Public GET must not 401 on a garbage/expired Authorization header
        # someone's browser happens to send.
        if getattr(self, "request", None) is None or self.request.method == "GET":
            return []
        return super().get_authenticators()

    def get(self, request, slug):
        link = ShareLink.objects.filter(slug=slug).first()
        if link is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if _link_state(link) == "gone":
            # 410: existed, deliberately doesn't anymore. The Next.js page
            # turns this into the friendly "link expired" landing page.
            return Response(
                {"error": "This share link has expired or been revoked."},
                status=status.HTTP_410_GONE,
            )

        # Atomic view-count bump (F() = no read-modify-write race).
        ShareLink.objects.filter(pk=link.pk).update(view_count=F("view_count") + 1)

        response = Response(
            {
                "kind": link.kind,
                "title": link.title,
                "ownerFirstName": link.owner_first_name,
                "payload": link.payload,
                "createdAt": link.created_at.isoformat(),
            }
        )
        # Keep unshared-by-obscurity pages out of search engines until we
        # DECIDE we want them indexed (doc 06, hidden requirement 5).
        response["X-Robots-Tag"] = "noindex"
        return response

    def delete(self, request, slug):
        # Owner-scoped soft revoke; zero rows updated → 404 (never 403).
        updated = ShareLink.objects.filter(
            slug=slug, owner_user_id=request.user.id, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        if updated == 0:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"revoked": True})


class ShareLinkCopyView(APIView):
    """
    POST /<slug>/copy — import the snapshot into MY account.

    This is the growth moment: the friend clicked, liked the plan, and
    signup became necessary for an honest reason (the copy must be stored
    somewhere). Writes a row into FitLog's workout_templates — writing
    ROWS is fine; only the SCHEMA is Prisma's.
    """

    def post(self, request, slug):
        link = ShareLink.objects.filter(slug=slug).first()
        if link is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if _link_state(link) == "gone":
            return Response(
                {"error": "This share link has expired or been revoked."},
                status=status.HTTP_410_GONE,
            )
        if link.kind != ShareLink.Kind.WORKOUT_TEMPLATE:
            return Response(
                {"error": "Only workout templates can be copied."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        try:
            template = WorkoutTemplate.objects.create(
                id=str(uuid.uuid4()),
                user_id=request.user.id,
                name=link.title[:100],
                # split_type deliberately NULL on copies — the value is
                # still visible in the payload; skipping the enum write
                # keeps the cross-service insert simple.
                split_type=None,
                exercises=link.payload.get("exercises", []),
                created_at=now,
                updated_at=now,
            )
        except IntegrityError:
            # FK to users failed → JWT is valid but the user has no FitLog
            # row yet (never onboarded).
            return Response(
                {"error": "Complete onboarding in FitLog before copying plans."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {"copied": True, "templateId": template.id, "name": template.name},
            status=status.HTTP_201_CREATED,
        )
