from _common import DOTA_START_CANCEL_MATCH_THRESHOLD, DOTA_START_CANCEL_SEARCH_REGION, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota start cancel button",
            "dota_start_cancel.png",
            is_dota=True,
            default_threshold=DOTA_START_CANCEL_MATCH_THRESHOLD,
            search_region=DOTA_START_CANCEL_SEARCH_REGION,
            force_fallback=True,
        )
    )
