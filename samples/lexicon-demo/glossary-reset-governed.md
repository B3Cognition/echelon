# Glossary — Password reset (governed: approved terms + reviewed codes/metrics)

- **Identity_Service**: the service that owns authentication and password reset
- **reset_request**: a user request to reset their password
- **reset_link**: a single-use, time-limited link emailed to the user
- **link_expiry**: the time after which a reset_link is no longer valid
- **password_hash**: the stored hash of a user's password
- **reset_email**: the email carrying the reset_link
- **link_status**: the lifecycle state of a reset_link
- **response_time_delta**: response-time difference used to bound enumeration timing leaks
- **PENDING_RETRY**: link_status value while a failed reset_email awaits retry
- **EMAIL_DELIVERY_FAILED**: error code when a reset_email cannot be delivered
- **HASH_UPDATE_FAILED**: error code when a password_hash update fails
