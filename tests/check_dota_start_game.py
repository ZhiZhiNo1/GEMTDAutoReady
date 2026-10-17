from _common import DOTA_START_GAME_MATCH_THRESHOLD, run_check


if __name__ == "__main__":
    raise SystemExit(
        run_check(
            "Dota in-game start button",
            "start_game.png",
            is_dota=True,
            default_threshold=DOTA_START_GAME_MATCH_THRESHOLD,
        )
    )
