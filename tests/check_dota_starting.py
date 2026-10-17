from _common import DOTA_STARTING_MATCH_THRESHOLD, DOTA_STARTING_SEARCH_REGION, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota start countdown indicator",
            "dota_starting.png",
            is_dota=True,
            default_threshold=DOTA_STARTING_MATCH_THRESHOLD,
            search_region=DOTA_STARTING_SEARCH_REGION,
            force_fallback=True,
        )
    )
