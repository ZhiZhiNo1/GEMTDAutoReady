from _common import DOTA_ARCADE_LIBRARY_SEARCH_REGION, DOTA_ARCADE_NAV_MATCH_THRESHOLD, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota Arcade game library",
            ("dota_arcade_library_unselected.png", "dota_arcade_library_selected.png"),
            is_dota=True,
            default_threshold=DOTA_ARCADE_NAV_MATCH_THRESHOLD,
            search_region=DOTA_ARCADE_LIBRARY_SEARCH_REGION,
        )
    )
