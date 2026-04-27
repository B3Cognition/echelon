# Auth Service Spec

FR-AUTH-001: The system must authenticate users via OAuth2 with JWT tokens.
FR-AUTH-002: The system must store user sessions in Redis with 30-minute TTL.
FR-AUTH-003: Session tokens must be rotated on privilege escalation.
NFR-AUTH-001: Response time must be under 200ms at p99 for authenticated requests.
NFR-AUTH-002: The auth service must sustain 5000 concurrent sessions.
AC-AUTH-001: Given a valid token, when the user calls /api/me, then a 200 response is returned.
AC-AUTH-002: Given an expired token, when the user calls any protected endpoint, then a 401 is returned.
