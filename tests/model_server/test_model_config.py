from pathlib import Path

from gisting.model_server.config import DEFAULT_MODEL_DIR, load_config


def test_defaults_when_nothing_is_set() -> None:
    config = load_config({})
    assert config.model_dir == Path(DEFAULT_MODEL_DIR).expanduser()
    assert config.device is None


def test_environment_overrides_the_directory_and_device(tmp_path: Path) -> None:
    config = load_config({"GISTING_MODEL_DIR": str(tmp_path), "GISTING_DEVICE": "cpu"})
    assert config.model_dir == tmp_path
    assert config.device == "cpu"


def test_empty_values_fall_back_to_defaults() -> None:
    config = load_config({"GISTING_MODEL_DIR": "", "GISTING_DEVICE": ""})
    assert config.model_dir == Path(DEFAULT_MODEL_DIR).expanduser()
    assert config.device is None


def test_gist_directory_is_optional_and_comes_from_the_environment(tmp_path: Path) -> None:
    assert load_config({}).gist_dir is None
    assert load_config({"GISTING_GIST_DIR": ""}).gist_dir is None
    assert load_config({"GISTING_GIST_DIR": str(tmp_path)}).gist_dir == tmp_path
