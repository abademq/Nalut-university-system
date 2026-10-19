"""Face verification extension point.

The platform does NOT implement face recognition itself. A live selfie is captured
from the camera and stored encrypted for a limited time so that an authorised
reviewer can look at it when a check-in is flagged.

To enable automatic matching, plug in a specialised vendor that provides face
matching *and* presentation-attack (liveness) detection, certified against photo,
screen-replay and mask attacks (e.g. ISO/IEC 30107-3 tested). Consumer tools such
as Teachable Machine are not suitable as a security control.

The verifier result is only one signal: it can route a check-in to human review,
it never rejects or penalises a user on its own.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FaceResult:
    status: str  # not_configured | match | no_match | liveness_failed | error
    score: float | None = None


class FaceVerifier:
    def verify(self, user_id: int, live_image: bytes) -> FaceResult:  # pragma: no cover - interface
        raise NotImplementedError


class NotConfiguredVerifier(FaceVerifier):
    def verify(self, user_id: int, live_image: bytes) -> FaceResult:
        return FaceResult(status="not_configured")


_verifier: FaceVerifier = NotConfiguredVerifier()


def get_verifier() -> FaceVerifier:
    return _verifier


def set_verifier(verifier: FaceVerifier) -> None:
    global _verifier
    _verifier = verifier
