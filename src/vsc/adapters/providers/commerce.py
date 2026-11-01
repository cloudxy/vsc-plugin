"""External commerce ports. No default pricing, payment or invoice gateway."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PaymentEvent:
    """Verified status; refund_rejected must be definitive refund failure evidence."""
    gateway: str
    event_id: str
    order_id: str
    status: str
    amount_minor: int
    currency: str
    external_id: str


@dataclass(frozen=True)
class Checkout:
    external_id: str
    checkout_url: str | None = None


@dataclass(frozen=True)
class InvoiceResult:
    external_id: str
    status: str
    document: bytes | None = None


class PaymentGateway(Protocol):
    id: str
    def create_checkout(self, order: dict) -> Checkout: ...
    def query_order(self, order: dict) -> PaymentEvent: ...
    def verify_notification(self, headers: dict, body: bytes) -> PaymentEvent: ...
    def refund(self, order: dict) -> PaymentEvent: ...
    def cancel(self, order: dict) -> PaymentEvent: ...


class InvoiceGateway(Protocol):
    id: str
    def issue(self, invoice: dict, order: dict) -> InvoiceResult: ...
    def query(self, invoice: dict) -> InvoiceResult: ...
