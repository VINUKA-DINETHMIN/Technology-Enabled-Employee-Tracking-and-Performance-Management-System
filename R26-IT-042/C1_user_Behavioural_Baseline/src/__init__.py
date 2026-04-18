"""
R26-IT-042 — Component 1: User Interaction Pattern Analysis
C1_user_interaction/src/__init__.py

Public interface for C1.  main.py calls start_interaction_profiling().
"""

# TODO (C1 owner): implement and export start_interaction_profiling


def start_interaction_profiling(user_id: str, shutdown_event=None) -> None:
    """
    Entry point called by main.py to start keystroke / mouse profiling.

    Parameters
    ----------
    user_id:
        Employee identifier.
    shutdown_event:
        threading.Event — set to True by main.py on logout.
    """
    # TODO: wire up keyboard_tracker and mouse_tracker here
    pass
