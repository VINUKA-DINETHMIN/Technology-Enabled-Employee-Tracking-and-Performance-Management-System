# C1 — User Interaction Pattern Analysis

Analyses keystroke dynamics and mouse behaviour to build per-user behavioural profiles.

## Owner
Team Member 1

## Dependencies
```
pynput
numpy
scikit-learn
pymongo
```

## Interfaces
- `start_interaction_profiling(user_id, shutdown_event)` — starts all trackers

## Data Flow
```
Keyboard / Mouse events
    ↓
Feature extraction (timing, velocity, pressure proxy)
    ↓
BehavioralBaselineDocument → MongoDB::behavioral_baselines
    ↓
Alert if profile deviates from baseline
```
