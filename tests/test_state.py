from steam_game_switcher.state import load_state, save_state


def test_separate_install_directories_default_on_per_game(tmp_path):
    config_path = tmp_path / "config.json"
    root, first_game = load_state(config_path, 526870)
    assert first_game["separate_install_dirs"] is True

    first_game["separate_install_dirs"] = False
    save_state(config_path, root)

    _, first_game_reloaded = load_state(config_path, 526870)
    _, second_game = load_state(config_path, 400)
    assert first_game_reloaded["separate_install_dirs"] is False
    assert second_game["separate_install_dirs"] is True


def test_v1_shared_directory_preference_is_preserved(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"schema_version": 1, "games": {"526870": '
        '{"separate_install_dirs": false, "profiles": {}}}}',
        encoding="utf-8",
    )

    root, game = load_state(config_path, 526870)

    assert root["schema_version"] == 2
    assert game["separate_install_dirs"] is False
    assert "profiles" in game
