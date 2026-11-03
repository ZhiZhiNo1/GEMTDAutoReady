from _common import DOTA_ARCADE_UNINSTALL_MATCH_THRESHOLD, DOTA_ARCADE_UNINSTALL_SEARCH_REGION, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota Gem TD uninstall button",
            "dota_arcade_uninstall.png",
            is_dota=True,
            default_threshold=DOTA_ARCADE_UNINSTALL_MATCH_THRESHOLD,
            search_region=DOTA_ARCADE_UNINSTALL_SEARCH_REGION,
        )
    )
