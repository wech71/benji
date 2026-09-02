#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
import operator
import os
import re
from functools import reduce
from os.path import expanduser
from typing import List, Callable, Union, Dict, Any, Optional, Sequence

import ruamel.yaml
import semantic_version
from pydantic import ValidationError

from benji.config_models import get_model_for_module, _BenjiBaseModel
from benji.exception import ConfigurationError, InternalError
from benji.logging import logger
from benji.versions import VERSIONS

# ruamel.yaml 0.18 removed the top-level load(stream, Loader=...) helper.
# Use a single safe-loader YAML instance for all parsing in this module.
# Safe loading produces plain dict/list/str/int/float/bool/None — identical
# parsing semantics to the previous ruamel.yaml.SafeLoader, so config and
# schema content is parsed byte-for-byte the same as on ruamel.yaml 0.16.
_YAML = ruamel.yaml.YAML(typ='safe')


class ConfigDict(dict):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.full_name: Optional[str] = None


class ConfigList(list):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.full_name: Optional[str] = None


class Config:
    _CONFIG_DIRS = ['/etc', '/etc/benji']
    _CONFIG_FILE = 'benji.yaml'
    _CONFIGURATION_VERSION_KEY = 'configurationVersion'
    _CONFIGURATION_VERSION_REGEX = r'\d+'

    _SCHEMA_VERSIONS = [semantic_version.Version(major=1, minor=0, patch=0)]

    @staticmethod
    def _schema_name(module: str, version: semantic_version.Version) -> str:
        return '{}-v{}'.format(module, version.major)

    @staticmethod
    def _output_validation_errors(errors) -> None:

        def traverse(cursor, path=''):
            if isinstance(cursor, dict):
                for key, value in cursor.items():
                    traverse(value, path + ('.' if path else '') + str(key))
            elif isinstance(cursor, list):
                for value in cursor:
                    if isinstance(value, dict):
                        traverse(value, path)
                    else:
                        logger.error('  {}: {}'.format(path, value))

        traverse(errors)

    def validate(self,
                 *,
                 module: str,
                 version: semantic_version.Version = None,
                 config: Union[Dict, ConfigDict]) -> Dict:
        version = self._config_version if version is None else version
        try:
            model_cls = get_model_for_module(module, version.major)
        except KeyError:
            raise InternalError('No configuration model registered for module {}.'.format(module))

        try:
            if issubclass(model_cls, _BenjiBaseModel):
                if module == __name__:
                    model = model_cls.model_validate(config)
                else:
                    model = model_cls.model_validate(config if config is not None else {})
                config_validated = model.to_config_dict()
            else:
                raise InternalError('Model for module {} is not a _BenjiBaseModel.'.format(module))
        except ValidationError as exception:
            logger.error('Configuration validation errors:')
            for error in exception.errors():
                loc = '.'.join(str(x) for x in error['loc'])
                logger.error('  {}: {}'.format(loc, error['msg']))
            raise ConfigurationError('Configuration for module {} is invalid.'.format(module)) from exception

        # This output leaks sensitive information. Only reinstate when such infos are redacted somehow.
        # logger.debug('Configuration for module {}: {}.'.format(module, config_validated))
        return config_validated

    def __init__(self, ad_hoc_config: str = None, sources: Sequence[str] = None) -> None:
        if ad_hoc_config is None:
            if not sources:
                sources = self._get_sources()

            config = None
            for source in sources:
                if os.path.isfile(source):
                    try:
                        with open(source, 'r') as f:
                            config = _YAML.load(f)
                    except Exception as exception:
                        raise ConfigurationError('Configuration file {} is invalid.'.format(source)) from exception
                    if config is None:
                        raise ConfigurationError('Configuration file {} is empty.'.format(source))
                    break

            if not config:
                raise ConfigurationError('No configuration file found in the default places ({}).'.format(
                    ', '.join(sources)))
        else:
            config = _YAML.load(ad_hoc_config)
            if config is None:
                raise ConfigurationError('Configuration string is empty.')

        if self._CONFIGURATION_VERSION_KEY not in config:
            raise ConfigurationError('Configuration is missing required key "{}".'.format(self._CONFIGURATION_VERSION_KEY))

        version = str(config[self._CONFIGURATION_VERSION_KEY])
        if not re.fullmatch(self._CONFIGURATION_VERSION_REGEX, version):
            raise ConfigurationError('Configuration has invalid version of "{}".'.format(version))

        version_obj = semantic_version.Version.coerce(version)
        if version_obj not in VERSIONS.configuration.supported:
            raise ConfigurationError('Configuration has unsupported version of "{}".'.format(version))

        self._config_version = version_obj
        self._config = ConfigDict(self.validate(module=__name__, config=config))
        logger.debug('Loaded configuration.')

    def _get_sources(self) -> List[str]:
        sources = []
        for directory in self._CONFIG_DIRS:
            sources.append('{directory}/{file}'.format(directory=directory, file=self._CONFIG_FILE))
        sources.append(expanduser('~/.{file}'.format(file=self._CONFIG_FILE)))
        sources.append(expanduser('~/{file}'.format(file=self._CONFIG_FILE)))
        return sources

    @staticmethod
    def _get(root,
             name: str,
             *args,
             types: Any = None,
             check_func: Callable[[object], bool] = None,
             check_message: str = None,
             full_name_override: str = None,
             index: int = None) -> object:
        if full_name_override is not None:
            full_name = full_name_override
        elif hasattr(root, 'full_name') and root.full_name:
            full_name = root.full_name
        else:
            full_name = ''

        if index is not None:
            full_name = '{}{}{}'.format(full_name, '.' if full_name else '', index)

        full_name = '{}{}{}'.format(full_name, '.' if full_name else '', name)

        if len(args) > 1:
            raise InternalError('Called with more than two arguments for key {}.'.format(full_name))

        try:
            value = reduce(operator.getitem, name.split('.'), root)
            if types is not None and not isinstance(value, types):
                raise TypeError('Config value {} has wrong type {}, expected {}.'.format(full_name, type(value), types))
            if check_func is not None and not check_func(value):
                if check_message is None:
                    raise ConfigurationError(
                        'Config option {} has the right type but the supplied value is invalid.'.format(full_name))
                else:
                    raise ConfigurationError('Config option {} is invalid: {}.'.format(full_name, check_message))
            if isinstance(value, dict):
                value = ConfigDict(value)
                value.full_name = full_name
            elif isinstance(value, list):
                value = ConfigList(value)
                value.full_name = full_name
            return value
        except KeyError:
            if len(args) == 1:
                return args[0]
            else:
                if types and isinstance({}, types):
                    raise KeyError('Config section {} is missing.'.format(full_name)) from None
                else:
                    raise KeyError('Config option {} is missing.'.format(full_name)) from None

    def get(self, name: str, *args, **kwargs) -> Any:
        return Config._get(self._config, name, *args, **kwargs)

    @staticmethod
    def get_from_dict(dict_: ConfigDict, name: str, *args, **kwargs) -> Any:
        return Config._get(dict_, name, *args, **kwargs)
