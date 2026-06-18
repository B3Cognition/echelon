ARTIFACT: SPEC
TITLE: Overdue invoice reminders

REQ: BILL-001
GIVEN: an invoice whose due_date has passed
WHEN: the Billing_Service runs the sweep
THEN: the Billing_Service MUST send an overdue_invoice_email
