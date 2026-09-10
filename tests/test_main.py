from unittest.mock import patch, MagicMock
from pathlib import Path
from fotoai.main import process_directory

@patch("fotoai.main.read_metadata")
@patch("fotoai.main.generate_metadata")
@patch("fotoai.main.write_metadata")
def test_process_directory_empty(mock_write, mock_generate, mock_read, tmp_path):
    # Create an empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    
    # Run the processor
    process_directory(empty_dir)
    
    # Assert no files were processed
    mock_read.assert_not_called()
    mock_generate.assert_not_called()
    mock_write.assert_not_called()

def test_config_loads_defaults():
    from fotoai.config import AppConfig
    config = AppConfig()
    assert config.ai.model == "gpt-5-mini"
