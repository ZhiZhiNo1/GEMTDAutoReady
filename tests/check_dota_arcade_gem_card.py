from _common import DOTA_ARCADE_GEM_CARD_SEARCH_REGION, DOTA_ARCADE_NAV_MATCH_THRESHOLD, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota Gem TD installed game card",
            "dota_arcade_gem_card.png",
            is_dota=True,
            default_threshold=DOTA_ARCADE_NAV_MATCH_THRESHOLD,
            search_region=DOTA_ARCADE_GEM_CARD_SEARCH_REGION,
        )
    )
