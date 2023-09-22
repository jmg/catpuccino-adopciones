import json
from os import environ

from pathlib2 import Path


def config_paths(env, root_path=None, file_name=None):
    """Build tuple of Paths to the ejson and json files for this environment.

    :return: ejson_path, config_json_path, config_override_path
    :rtype: (pathlib2.Path, pathlib2.Path, pathlib2.Path)
    """
    if env in [ "LOCAL" , "TEST"]:
        config_dir = Path(__file__)
        config_json = config_dir.joinpath(root_path, "config", "config.{}.json".format(env.lower())).resolve()
    else:
        config_dir = Path("/etc/secrets/")
        if not file_name:
            file_name = "config"
        config_json = config_dir.joinpath("{}.{}.json".format(file_name, env.lower())).resolve()

    return config_json


def init_app_config(app):
    """Initialize the app config.

    :type app: flask.Flask
    """
    app_config = read_config()
    app.config.from_mapping(app_config)
    app.config.from_mapping(dict(environ))


def read_config(env, root_path=None, file_name=None):
    """Fetch the config from /etc/secrets/config.ENV.json.

    :return: dict
    """
    try:
        # FIXME: Remove once we switch to json config on production!
        config_json = config_paths(env, root_path=root_path, file_name=file_name)

        if not config_json.is_file():
            raise SystemExit("Attempted to load config {} but it wasn't found.".format(config_json))

        with config_json.open() as f:
            app_config = json.loads(f.read())
            clean_config = {}
            for key, value in app_config.items():
                if isinstance(value, dict):
                    clean_config[key] = value
                elif value:
                    clean_config[key] = str(value)

        return clean_config
    except Exception as e:
        raise SystemExit("Attempted to load config {} but there was an error: {}.".format(config_json, str(e)))
