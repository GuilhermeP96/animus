"""Load peer configuration without inspecting another project's dotenv."""
from animus.config import AnimusConfig

class HelperConfig(AnimusConfig):
    model_config = {**AnimusConfig.model_config, "env_file": None,
                    "extra": "ignore", "hide_input_in_errors": True}

def load_config():
    return HelperConfig.load()
