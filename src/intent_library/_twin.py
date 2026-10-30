"""Access to Component 02 from the Intent Library.

Tests import packages as ``src.<name>`` while an installed distribution exposes
top-level ``twin_builder``. Importing relative to the parent package keeps both
components bound to the same module objects in either layout.
"""

if __package__ and "." in __package__:
    from ..twin_builder.schema import Interface, NetworkEvidence, Node
    from ..twin_builder.verifier import TwinVerifier, VerificationError
else:
    from twin_builder.schema import Interface, NetworkEvidence, Node  # type: ignore[no-redef]
    from twin_builder.verifier import (  # type: ignore[no-redef]
        TwinVerifier,
        VerificationError,
    )

__all__ = ["Interface", "NetworkEvidence", "Node", "TwinVerifier", "VerificationError"]
