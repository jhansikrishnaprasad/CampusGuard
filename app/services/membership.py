"""Optional college-membership verification interface.

Uniform appearance and a visible ID card are NOT proof of membership, and this prototype does not
read ID text or use face recognition. Unless an authorised provider is implemented and configured,
every tracked person is reported as 'membership_unverified'.

To integrate a student database: subclass MembershipVerifier, return 'verified' / 'not_found' only
from an authorised lookup, and register it in `get_verifier`. Never log or expose student data.
"""
from __future__ import annotations


class MembershipVerifier:
    name = "none"
    configured = False

    def verify(self, *_args, **_kwargs) -> str:
        return "membership_unverified"


def get_verifier() -> MembershipVerifier:
    return MembershipVerifier()
