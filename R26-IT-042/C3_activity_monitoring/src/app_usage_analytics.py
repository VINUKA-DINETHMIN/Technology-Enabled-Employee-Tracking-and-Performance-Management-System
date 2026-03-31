"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/app_usage_analytics.py

AppUsageAnalytics — Aggregates app usage data from activity_logs collection
and generates analytics summaries for display in admin panel.

Usage
─────
>>> analytics = AppUsageAnalytics(db_client=db)
>>> summary = analytics.get_app_usage_summary(user_id="EMP001", days=1)
>>> print(summary.apps)  # List of {app: str, time_sec: float, sessions: int, ...}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from common.database import MongoDBClient


class AppUsageAnalytics:
    """
    Aggregates app usage statistics from activity_logs collection.
    Handles timerange queries and per-app consolidation.
    """

    def __init__(self, db_client: Optional["MongoDBClient"] = None) -> None:
        """
        Parameters
        ----------
        db_client:
            MongoDBClient instance for querying activity_logs.
        """
        self._db = db_client

    def get_app_usage_summary(
        self,
        user_id: str,
        days: int = 1,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> "AppUsageSummary":
        """
        Aggregate app usage for a time range.

        Parameters
        ----------
        user_id:
            Employee ID.
        days:
            Number of days to include (if start_date/end_date not provided).
        start_date:
            Optional explicit start (defaults to N days ago).
        end_date:
            Optional explicit end (defaults to now).

        Returns
        -------
        AppUsageSummary
            Aggregated stats including app list, totals, and top apps.
        """
        if self._db is None or not self._db.is_connected:
            return AppUsageSummary.empty()

        try:
            # Calculate time range
            if end_date is None:
                end_date = datetime.now(timezone.utc)
            if start_date is None:
                start_date = end_date - timedelta(days=days)

            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()

            col = self._db.get_collection("activity_logs")
            if col is None:
                return AppUsageSummary.empty()

            # Aggregation pipeline: group by top_app and sum metrics
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id,
                        "timestamp": {"$gte": start_iso, "$lte": end_iso},
                    }
                },
                {
                    "$group": {
                        "_id": "$top_app",
                        "total_time": {"$sum": "$total_focus_duration"},
                        "session_count": {"$sum": 1},
                        "last_used": {"$max": "$timestamp"},
                        "avg_risk_score": {"$avg": "$composite_risk_score"},
                        "productivity_avg": {"$avg": "$productivity_score"},
                    }
                },
                {
                    "$sort": {"total_time": -1}
                },
            ]

            results = list(col.aggregate(pipeline))

            # Transform into APP records
            apps = []
            total_time = 0.0
            session_total = 0

            for doc in results:
                app_name = doc.get("_id") or "Unknown"
                time_sec = float(doc.get("total_time", 0.0) or 0.0)
                sessions = int(doc.get("session_count", 0) or 0)
                last_used = doc.get("last_used") or ""

                if app_name and app_name != "Unknown" and time_sec > 0:
                    apps.append(
                        {
                            "app": app_name,
                            "time_sec": time_sec,
                            "sessions": sessions,
                            "last_used": last_used,
                            "avg_risk_score": float(doc.get("avg_risk_score", 0.0) or 0.0),
                            "productivity_avg": float(doc.get("productivity_avg", 0.0) or 0.0),
                        }
                    )
                    total_time += time_sec
                    session_total += sessions

            # Calculate percentages and rank
            for i, app in enumerate(apps):
                app["rank"] = i + 1
                app["percentage"] = (app["time_sec"] / total_time * 100.0) if total_time > 0 else 0.0

            # Summary stats
            most_used = apps[0]["app"] if apps else "None"
            app_count = len(apps)
            avg_focus = total_time / session_total if session_total > 0 else 0.0

            return AppUsageSummary(
                user_id=user_id,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                apps=apps,
                total_time_sec=total_time,
                total_sessions=session_total,
                most_used_app=most_used,
                app_count=app_count,
                avg_focus_time=avg_focus,
            )

        except Exception as exc:
            logger.error("App usage analytics error: %s", exc)
            return AppUsageSummary.empty()

    def get_apps_by_period(
        self, user_id: str, period: str = "today"
    ) -> "AppUsageSummary":
        """
        Convenience method for common time ranges.

        Parameters
        ----------
        user_id:
            Employee ID.
        period:
            "today" | "week" | "month"

        Returns
        -------
        AppUsageSummary
            Aggregated stats for the period.
        """
        now = datetime.now(timezone.utc)

        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif period == "week":
            start = now - timedelta(days=7)
            end = now
        elif period == "month":
            start = now - timedelta(days=30)
            end = now
        else:
            return AppUsageSummary.empty()

        return self.get_app_usage_summary(user_id, start_date=start, end_date=end)


class AppUsageSummary:
    """Container for app usage analytics results."""

    def __init__(
        self,
        user_id: str = "UNKNOWN",
        start_date: str = "",
        end_date: str = "",
        apps: list[dict] = None,
        total_time_sec: float = 0.0,
        total_sessions: int = 0,
        most_used_app: str = "None",
        app_count: int = 0,
        avg_focus_time: float = 0.0,
    ) -> None:
        self.user_id = user_id
        self.start_date = start_date
        self.end_date = end_date
        self.apps = apps or []
        self.total_time_sec = total_time_sec
        self.total_sessions = total_sessions
        self.most_used_app = most_used_app
        self.app_count = app_count
        self.avg_focus_time = avg_focus_time

    @staticmethod
    def empty() -> "AppUsageSummary":
        """Return an empty summary."""
        return AppUsageSummary()

    def get_hours_string(self, seconds: float) -> str:
        """Format seconds as readable time string."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"

    def top_apps(self, limit: int = 5) -> list[dict]:
        """Return top N apps by time spent."""
        return self.apps[:limit]
