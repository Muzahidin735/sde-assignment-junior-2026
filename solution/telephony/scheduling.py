from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def is_within_calling_window(campaign, now):
    local_now = now.astimezone(ZoneInfo("Asia/Kolkata"))

    current_day = local_now.strftime("%a").lower()
    current_time = local_now.time().replace(tzinfo=None)

    regulatory_start = time(9, 0)
    regulatory_end = time(21, 0)

    return (
        current_day in campaign.calling_days
        and campaign.window_start <= current_time < campaign.window_end
        and regulatory_start <= current_time < regulatory_end
    )

def get_next_window_opening(campaign, now):
    local_now = now.astimezone(ZoneInfo("Asia/Kolkata"))

    for day_offset in range(8):
        candidate_date = local_now.date() + timedelta(days=day_offset)
        candidate_day = candidate_date.strftime("%a").lower()

        if candidate_day not in campaign.calling_days:
            continue

        opening_time = max(campaign.window_start, time(9, 0))
        closing_time = min(campaign.window_end, time(21, 0))

        if opening_time >= closing_time:
            continue

        candidate_datetime = datetime.combine(
            candidate_date,
            opening_time,
            tzinfo=ZoneInfo("Asia/Kolkata"),
        )

        if candidate_datetime > local_now:
            return candidate_datetime

    return None

def get_next_eligible_time(campaign, now, eligible_at=None):
    if eligible_at and eligible_at > now:
        now = eligible_at

    if is_within_calling_window(campaign, now):
        return now

    return get_next_window_opening(campaign, now)

def get_retry_time(disposition, ended_at, retry_policy):
    if disposition in ("no_answer", "busy"):
        delay_minutes = retry_policy["no_answer_minutes"]
    elif disposition == "failed":
        delay_minutes = retry_policy["failed_minutes"]
    else:
        return None

    return ended_at + timedelta(minutes=delay_minutes)

def get_callback_time(callback_at, campaign, now):
    eligible_at = max(callback_at, now)

    return get_next_eligible_time(
        campaign,
        eligible_at,
    )

def get_priority(lead):
    if lead.callback_at is not None:
        return 1

    if lead.next_eligible_at is not None:
        return 2

    return 3