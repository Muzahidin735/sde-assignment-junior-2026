from datetime import datetime

import httpx


def get_simulated_now():
    response = httpx.get(
        "http://127.0.0.1:8099/v1/clock",
        timeout=5.0,
    )

    response.raise_for_status()

    clock_data = response.json()

    return datetime.fromisoformat(clock_data["sim_now"])