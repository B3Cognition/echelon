ARTIFACT: SPEC
TITLE: Overdue invoice reminders

REQ: BILL-001
GIVEN: an invoice whose due_date has passed
WHEN: the Billing_Service runs the sweep
THEN: the Billing_Service should quickly send a robust overdue_invoice_email to the customer_gateway
OUTPUT: a queued overdue_invoice_email
