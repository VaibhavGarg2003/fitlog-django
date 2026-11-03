"""
ChatWsTicket — managed=False mapping of the Prisma-owned `chat_ws_tickets`.

Next.js issues a 60-second signed ticket and stores only sha256(jti). This
service CONSUMES it once (tickets.consume_ticket). Prisma owns the schema;
Django only updates `consumed_at` — through the restricted runtime role,
which has SELECT/UPDATE on this table and nothing more on chat data.
"""

from django.db import models


class ChatWsTicket(models.Model):
    jti_hash = models.CharField(primary_key=True, max_length=64)
    user_id = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "chat_ws_tickets"

    def __str__(self) -> str:
        return f"ticket {self.jti_hash[:8]}… for {self.user_id}"
