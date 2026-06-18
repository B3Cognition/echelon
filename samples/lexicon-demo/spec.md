ARTIFACT: SPEC
TITLE: Overdue invoice reminders

INPUT: invoice
TYPE: record
REQUIRED: yes
SOURCE: Billing_Service
VALID_WHEN: invoice has a due_date

REQ: BILL-001
GIVEN: an invoice whose due_date has passed
WHEN: the Billing_Service runs the daily reminder sweep
THEN: the Billing_Service MUST send an overdue_invoice_email
OUTPUT: a queued overdue_invoice_email
CONSTRAINT: delivery_time <= 30 s

AC: BILL-001-A
GIVEN: an invoice whose due_date has passed
WHEN: the daily reminder sweep completes
THEN: the email_status is SENT

ERROR: BILL-001-E
WHEN: the mail relay rejects the message
THEN: requeue the overdue_invoice_email for retry
ERROR_CODE: RELAY_REJECTED
