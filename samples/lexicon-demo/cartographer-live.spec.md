ARTIFACT: SPEC
TITLE: Password reset via email link

REQ: RESET-001
GIVEN: a signed-out user with a registered email address
WHEN: the user submits a reset_request with their email address
THEN: the Identity_Service MUST generate a single-use reset_link and send a reset_email to the registered address
OUTPUT: a delivered reset_email containing the reset_link
CONSTRAINT: link_expiry <= 15 min

REQ: RESET-002
GIVEN: the Identity_Service has received a reset_request
WHEN: the Identity_Service generates a reset_link
THEN: the Identity_Service MUST set the link_status to ACTIVE and associate it with exactly one reset_request
OUTPUT: a persisted reset_link with link_status ACTIVE

REQ: RESET-003
GIVEN: a user follows a reset_link whose link_status is ACTIVE and whose link_expiry has not elapsed
WHEN: the user submits a new password
THEN: the Identity_Service MUST replace the existing password_hash with a hash derived from the new password and set the link_status to CONSUMED
OUTPUT: an updated password_hash and link_status set to CONSUMED

REQ: RESET-004
GIVEN: a user follows a reset_link whose link_expiry has elapsed
WHEN: the Identity_Service evaluates the reset_link
THEN: the Identity_Service MUST reject the reset_link and set the link_status to EXPIRED
OUTPUT: a rejection notice displayed to the user

REQ: RESET-005
GIVEN: a user follows a reset_link whose link_status is CONSUMED or EXPIRED
WHEN: the Identity_Service evaluates the reset_link
THEN: the Identity_Service MUST reject the reset_link without modifying the password_hash
OUTPUT: a rejection notice indicating the link is no longer valid

REQ: RESET-006
GIVEN: a reset_request is submitted with an email address not matching any registered account
WHEN: the Identity_Service processes the reset_request
THEN: the Identity_Service MUST respond with the same confirmation message as for a valid reset_request
OUTPUT: a confirmation message identical to a successful reset_request submission
CONSTRAINT: response_time_delta <= 200 ms

REQ: RESET-007
GIVEN: a reset_request is submitted with any email address
WHEN: the Identity_Service responds to the reset_request
THEN: the Identity_Service MUST NOT include any indication of whether the email address is registered
OUTPUT: a response that is indistinguishable regardless of account existence

AC: RESET-001-A
GIVEN: a signed-out user submits a reset_request with a registered email address
WHEN: the reset_email is delivered
THEN: the reset_email contains a reset_link that resolves to the password reset form

AC: RESET-002-A
GIVEN: a user follows a valid reset_link and submits a new password
WHEN: the password_hash update completes
THEN: the user can authenticate with the new password and the previous password is rejected

AC: RESET-003-A
GIVEN: a reset_link has been used once to change a password
WHEN: the same reset_link is followed a second time
THEN: the Identity_Service displays a rejection notice and the password_hash remains unchanged

ERROR: RESET-001-E
WHEN: the reset_email cannot be delivered to the mail relay within the configured timeout
THEN: the Identity_Service logs the delivery failure and sets the link_status to PENDING_RETRY
ERROR_CODE: EMAIL_DELIVERY_FAILED

ERROR: RESET-002-E
WHEN: the password_hash update fails during the reset_link redemption
THEN: the Identity_Service rolls back the link_status to ACTIVE and displays a failure notice to the user
ERROR_CODE: HASH_UPDATE_FAILED
