"""Shared, single-source domain constants.

These values were previously duplicated as literals across several pipeline
components, which risked silent drift between security/privacy controls. They
live here so there is exactly one source of truth.
"""

from __future__ import annotations

# k-anonymity privacy floor: the smallest group size whose aggregate may ever be
# shown. This is a deliberate code constant — NOT an environment-overridable
# setting — so the privacy guarantee cannot be weakened by configuration. The
# metadata `access_policies` may only *raise* the effective threshold above this
# floor; any value at or below the floor is clamped back up to it.
MIN_GROUP_SIZE_FLOOR = 5
