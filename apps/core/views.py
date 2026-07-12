"""Core views — health check + an authenticated echo for JWT smoke tests."""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def healthz(request):
    """
    Liveness probe. Public by design (keepalive pings, Render health check).
    Deliberately does NOT touch the database — a liveness check answers
    "is the process up?", not "is every dependency happy?".
    """
    return Response({"status": "ok", "service": "fitlog-django"})


@api_view(["GET"])
def whoami(request):
    """
    Echo the authenticated identity. Exists so the cross-service auth can
    be smoke-tested end to end: curl with a real Supabase JWT from the
    Next.js session → your user id back; no/tampered token → 401.
    """
    return Response({"userId": request.user.id, "email": request.user.email})
