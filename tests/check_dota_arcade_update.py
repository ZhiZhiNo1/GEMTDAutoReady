from _common import DOTA_ARCADE_ACTION_SEARCH_REGION, DOTA_ARCADE_UPDATE_MATCH_THRESHOLD, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota Gem TD update button",
            "dota_arcade_update.png",
            is_dota=True,
            default_threshold=DOTA_ARCADE_UPDATE_MATCH_THRESHOLD,
            search_region=DOTA_ARCADE_ACTION_SEARCH_REGION,
        )
    )
