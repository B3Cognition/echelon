# Payment Service Spec

FR-PAY-001: The payment system must support Stripe and PayPal as providers.
FR-PAY-002: All payment events must be written to an immutable audit trail.
FR-PAY-003: Refunds must be processed within 5 business days.
NFR-PAY-001: Payment processing must complete within 3 seconds at p95.
AC-PAY-001: Given a valid card, when checkout is submitted, then a confirmation email is sent.
