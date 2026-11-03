from _common import DOTA_ARCADE_ACTION_SEARCH_REGION, DOTA_ARCADE_INSTALL_MATCH_THRESHOLD, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota Gem TD install button",
            "dota_arcade_install.png",
            is_dota=True,
            default_threshold=DOTA_ARCADE_INSTALL_MATCH_THRESHOLD,
            search_region=DOTA_ARCADE_ACTION_SEARCH_REGION,
        )
    )
