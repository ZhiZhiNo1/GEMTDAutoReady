from _common import DOTA_ARCADE_NAV_MATCH_THRESHOLD, DOTA_ARCADE_TAB_SEARCH_REGION, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota Arcade tab",
            ("dota_arcade_tab_unselected.png", "dota_arcade_tab_selected.png"),
            is_dota=True,
            default_threshold=DOTA_ARCADE_NAV_MATCH_THRESHOLD,
            search_region=DOTA_ARCADE_TAB_SEARCH_REGION,
        )
    )
