# SPDX-License-Identifier: LGPL-3.0-only
# SPDX-FileCopyrightText: 2025 elemental-lf
#
# Pydantic v2 models that replace the Cerberus YAML schemas in schemas/v1/.
#
# Each model corresponds to a schema file, and the model hierarchy mirrors
# the Cerberus ``parents`` inheritance.  The public API (Config.validate)
# instantiates the appropriate model, then calls ``to_config_dict()`` which
# returns a plain dict matching the exact output Cerberus produced:
#
#   - Fields with a Cerberus ``default`` are always present.
#   - Optional fields without a default are present only if the user supplied
#     a value.
#   - Unknown keys are rejected (extra='forbid'), matching Cerberus default.
#
# The YAML config syntax visible to the user is unchanged (PORTING-TASKS D4).
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Sentinel for "no Cerberus default" — distinguishes Optional[T] = None
# (Cerberus default: null) from a field that simply has no default.
_UNSET: Any = object()


class _BenjiBaseModel(BaseModel):
    """Base class for all benji configuration models."""

    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    def to_config_dict(self) -> Dict[str, Any]:
        """Convert to a plain dict, matching Cerberus validated output.

        Fields whose default is _UNSET (no Cerberus default) are excluded
        when they still hold the sentinel value.  All other fields are
        included, matching Cerberus behaviour where defaults are always
        materialised in the output.
        """
        result: Dict[str, Any] = {}
        for name in type(self).model_fields:
            value = getattr(self, name)
            if value is _UNSET:
                continue
            # Recursively convert nested benji models
            if isinstance(value, _BenjiBaseModel):
                result[name] = value.to_config_dict()
            elif isinstance(value, list):
                result[name] = [
                    v.to_config_dict() if isinstance(v, _BenjiBaseModel) else v
                    for v in value
                ]
            elif isinstance(value, dict):
                result[name] = value
            else:
                result[name] = value
        return result


# ── Transform schemas ─────────────────────────────────────────────────────

class TransformBaseConfig(_BenjiBaseModel):
    """benji.transform.base — nullable, allows empty/None configuration."""
    model_config = ConfigDict(extra='allow')


class TransformZstdConfig(_BenjiBaseModel):
    """benji.transform.zstd"""
    level: int = Field(default=3, ge=1)
    dictDataFile: Optional[str] = Field(default=_UNSET)


class TransformAes256GcmConfig(_BenjiBaseModel):
    """benji.transform.aes_256_gcm — masterKey OR (kdfSalt + kdfIterations + password)."""
    masterKey: Optional[str] = Field(default=_UNSET)
    kdfSalt: Optional[str] = Field(default=_UNSET)
    kdfIterations: Optional[int] = Field(default=_UNSET)
    password: Optional[str] = Field(default=_UNSET)

    @model_validator(mode='after')
    def _check_excludes_and_dependencies(self):
        has_master = self.masterKey is not _UNSET
        has_kdf = self.kdfSalt is not _UNSET
        has_iter = self.kdfIterations is not _UNSET
        has_pass = self.password is not _UNSET

        if has_master and (has_kdf or has_iter or has_pass):
            raise ValueError(
                'masterKey excludes kdfSalt, kdfIterations and password')
        if has_kdf or has_iter or has_pass:
            if not (has_kdf and has_iter and has_pass):
                raise ValueError(
                    'kdfSalt, kdfIterations and password must all be specified together')
            if self.kdfIterations < 1000:
                raise ValueError('kdfIterations must be >= 1000')
        if has_pass and len(self.password) < 8:
            raise ValueError('password must be at least 8 characters long')
        return self


class TransformAes256GcmEccConfig(_BenjiBaseModel):
    """benji.transform.aes_256_gcm_ecc"""
    eccKey: str
    eccCurve: str = Field(default='NIST P-384')

    @field_validator('eccCurve')
    @classmethod
    def _check_curve(cls, v):
        allowed = {'NIST P-256', 'NIST P-384', 'NIST P-521'}
        if v not in allowed:
            raise ValueError(f'eccCurve must be one of {allowed}')
        return v


# ── IO schemas ────────────────────────────────────────────────────────────

class IoFileConfig(_BenjiBaseModel):
    """benji.io.file"""
    simultaneousWrites: int = Field(default=3, ge=1)
    simultaneousReads: int = Field(default=3, ge=1)


class IoRbdConfig(_BenjiBaseModel):
    """benji.io.rbd"""
    simultaneousWrites: int = Field(default=3, ge=1)
    simultaneousReads: int = Field(default=3, ge=1)
    cephConfigFile: str = Field(default='/etc/ceph/ceph.conf')
    clientIdentifier: str = Field(default='admin')
    newImageFeatures: List[str] = Field(default=['RBD_FEATURE_LAYERING'])

    @field_validator('newImageFeatures')
    @classmethod
    def _check_features(cls, v):
        for item in v:
            if not item.startswith('RBD_FEATURE_'):
                raise ValueError(
                    f'newImageFeatures entries must match ^RBD_FEATURE_.*: {item!r}')
        return v


class IoRbdaioConfig(IoRbdConfig):
    """benji.io.rbdaio — inherits from benji.io.rbd."""
    pass


class IoIscsiConfig(_BenjiBaseModel):
    """benji.io.iscsi — optional, all fields optional with dependencies."""
    model_config = ConfigDict(extra='forbid')

    username: Optional[str] = Field(default=_UNSET)
    password: Optional[str] = Field(default=_UNSET)
    targetUsername: Optional[str] = Field(default=_UNSET)
    targetPassword: Optional[str] = Field(default=_UNSET)
    headerDigest: str = Field(default='NONE_CRC32C')
    initiatorName: str = Field(default='iqn.2019-04.me.benji-backup:benji')
    timeout: int = Field(default=0)

    @field_validator('headerDigest')
    @classmethod
    def _check_digest(cls, v):
        allowed = {'NONE', 'NONE_CRC32C', 'CRC32C_NONE', 'CRC32C'}
        if v not in allowed:
            raise ValueError(f'headerDigest must be one of {allowed}')
        return v

    @model_validator(mode='after')
    def _check_dependencies(self):
        has_user = self.username is not _UNSET
        has_pass = self.password is not _UNSET
        has_tuser = self.targetUsername is not _UNSET
        has_tpass = self.targetPassword is not _UNSET

        if has_user and not has_pass:
            raise ValueError('username requires password')
        if has_pass and not has_user:
            raise ValueError('password requires username')
        if has_tuser and not has_tpass:
            raise ValueError('targetUsername requires targetPassword')
        if has_tpass and not has_tuser:
            raise ValueError('targetPassword requires targetUsername')
        if (has_tuser or has_tpass) and not has_user:
            raise ValueError(
                'targetUsername/targetPassword require username')
        return self


# ── Storage schemas ───────────────────────────────────────────────────────

class StorageBaseConfig(_BenjiBaseModel):
    """benji.storage.base"""
    activeTransforms: Optional[List[str]] = Field(default=_UNSET)
    simultaneousWrites: int = Field(default=3, ge=1)
    simultaneousReads: int = Field(default=3, ge=1)
    simultaneousRemovals: int = Field(default=5, ge=1)
    bandwidthRead: int = Field(default=0, ge=0)
    bandwidthWrite: int = Field(default=0, ge=0)
    consistencyCheckWrites: bool = Field(default=False)
    hmac: Optional[Dict[str, Any]] = Field(default=_UNSET)


class StorageReadCacheConfig(StorageBaseConfig):
    """benji.storage.base.ReadCache — inherits from StorageBaseConfig."""
    readCache: Optional[Dict[str, Any]] = Field(default=_UNSET)

    @model_validator(mode='after')
    def _check_read_cache(self):
        if self.readCache is not _UNSET:
            rc = self.readCache
            required_keys = {'directory', 'maximumSize', 'shards'}
            missing = required_keys - set(rc.keys())
            if missing:
                raise ValueError(f'readCache requires: {missing}')
            if not isinstance(rc.get('directory'), str) or not rc['directory']:
                raise ValueError('readCache.directory must be a non-empty string')
            if not isinstance(rc.get('maximumSize'), int) or rc['maximumSize'] < 1:
                raise ValueError('readCache.maximumSize must be >= 1')
            if not isinstance(rc.get('shards'), int) or rc['shards'] < 1:
                raise ValueError('readCache.shards must be >= 1')
        return self


class StorageFileConfig(StorageBaseConfig):
    """benji.storage.file — inherits from StorageBaseConfig."""
    path: str


class StorageS3Config(StorageReadCacheConfig):
    """benji.storage.s3 — inherits from ReadCacheConfig."""

    awsAccessKeyId: Optional[str] = Field(default=_UNSET)
    awsAccessKeyIdFile: Optional[str] = Field(default=_UNSET)
    awsSecretAccessKey: Optional[str] = Field(default=_UNSET)
    awsSecretAccessKeyFile: Optional[str] = Field(default=_UNSET)
    regionName: Optional[str] = Field(default=_UNSET)
    endpointUrl: Optional[str] = Field(default=_UNSET)
    useSsl: bool = Field(default=True)
    addressingStyle: Optional[str] = Field(default=_UNSET)
    signatureVersion: Optional[str] = Field(default=_UNSET)
    bucketName: str
    storageClass: Optional[str] = Field(default=_UNSET)
    disableEncodingType: bool = Field(default=False)
    connectTimeout: float = Field(default=60.0, ge=0.0)
    readTimeout: float = Field(default=60.0, ge=0.0)
    maxAttempts: int = Field(default=5, ge=1)

    @model_validator(mode='after')
    def _check_excludes(self):
        if self.awsAccessKeyId is not _UNSET and self.awsAccessKeyIdFile is not _UNSET:
            raise ValueError('awsAccessKeyId excludes awsAccessKeyIdFile')
        if self.awsSecretAccessKey is not _UNSET and self.awsSecretAccessKeyFile is not _UNSET:
            raise ValueError('awsSecretAccessKey excludes awsSecretAccessKeyFile')
        return self


class StorageB2Config(StorageReadCacheConfig):
    """benji.storage.b2 — inherits from ReadCacheConfig."""

    accountId: Optional[str] = Field(default=_UNSET)
    accountIdFile: Optional[str] = Field(default=_UNSET)
    applicationKey: Optional[str] = Field(default=_UNSET)
    applicationKeyFile: Optional[str] = Field(default=_UNSET)
    bucketName: str
    accountInfoFile: Optional[str] = Field(default=_UNSET)
    uploadAttempts: int = Field(default=5, ge=1)
    writeObjectAttempts: int = Field(default=3, ge=1)
    readObjectAttempts: int = Field(default=3, ge=1)

    @model_validator(mode='after')
    def _check_excludes(self):
        if self.accountId is not _UNSET and self.accountIdFile is not _UNSET:
            raise ValueError('accountId excludes accountIdFile')
        if self.applicationKey is not _UNSET and self.applicationKeyFile is not _UNSET:
            raise ValueError('applicationKey excludes applicationKeyFile')
        return self


# ── Top-level config schema ───────────────────────────────────────────────

_VALUE_REGEX = r'^(?!-)[-a-zA-Z0-9_.:/@]+(?<!-)$'


class _NamedModuleConfig(_BenjiBaseModel):
    """Base for storages/transforms/ios list entries."""
    name: str
    module: str

    @field_validator('name')
    @classmethod
    def _check_name(cls, v):
        if not re.match(_VALUE_REGEX, v):
            raise ValueError(f'name must match {_VALUE_REGEX!r}')
        return v


class _StorageEntry(_NamedModuleConfig):
    """A storage entry in the top-level config."""
    storageId: Optional[int] = Field(default=_UNSET, ge=1)
    configuration: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra='forbid')


class _TransformEntry(_NamedModuleConfig):
    """A transform entry in the top-level config."""
    configuration: Optional[Dict[str, Any]] = Field(default=_UNSET)

    model_config = ConfigDict(extra='forbid')


class _IoEntry(_NamedModuleConfig):
    """An IO entry in the top-level config."""
    configuration: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra='forbid')


class _NbdBlockCacheConfig(_BenjiBaseModel):
    directory: str = Field(default='/tmp/benji/nbd/block-cache')
    maximumSize: int = Field(default=2126512128)


class _NbdCowStoreConfig(_BenjiBaseModel):
    directory: str = Field(default='/tmp/benji/nbd/cow-store')


class _NbdConfig(_BenjiBaseModel):
    blockCache: _NbdBlockCacheConfig = Field(default_factory=_NbdBlockCacheConfig)
    cowStore: _NbdCowStoreConfig = Field(default_factory=_NbdCowStoreConfig)


class BenjiConfig(_BenjiBaseModel):
    """benji.config — the top-level configuration schema."""

    configurationVersion: str = Field(default='1')
    logFile: Optional[str] = Field(default=None)
    blockSize: int = Field(default=4194304, ge=512, le=33554432)
    hashFunction: str = Field(default='BLAKE2b,digest_bits=256', min_length=1)
    processName: str = Field(default='benji', min_length=1)
    disallowRemoveWhenYounger: int = Field(default=6, ge=0)
    databaseEngine: str = Field(min_length=1)
    defaultStorage: str = Field(min_length=1)
    nbd: _NbdConfig = Field(default_factory=_NbdConfig)
    storages: List[_StorageEntry] = Field(min_length=1)
    transforms: Optional[List[_TransformEntry]] = Field(default=_UNSET)
    ios: List[_IoEntry] = Field(min_length=1)

    @field_validator('configurationVersion', mode='before')
    @classmethod
    def _coerce_to_string(cls, v):
        return str(v)

    @field_validator('configurationVersion')
    @classmethod
    def _check_version(cls, v):
        if v != '1':
            raise ValueError('configurationVersion must be "1"')
        return v

    @field_validator('nbd', mode='before')
    @classmethod
    def _null_nbd_to_dict(cls, v):
        """YAML 'nbd:' parses as None; Cerberus applied default {}."""
        if v is None:
            return {}
        return v


# ── Model registry ────────────────────────────────────────────────────────

# Maps module name → Pydantic model class, replacing the YAML schema registry.
# The key format is "{module}-v{major}" to match the Cerberus _schema_name.
_MODEL_REGISTRY: Dict[str, type[_BenjiBaseModel]] = {
    'benji.config-v1': BenjiConfig,
    'benji.io.file-v1': IoFileConfig,
    'benji.io.iscsi-v1': IoIscsiConfig,
    'benji.io.rbd-v1': IoRbdConfig,
    'benji.io.rbdaio-v1': IoRbdaioConfig,
    'benji.storage.base-v1': StorageBaseConfig,
    'benji.storage.base.ReadCache-v1': StorageReadCacheConfig,
    'benji.storage.file-v1': StorageFileConfig,
    'benji.storage.s3-v1': StorageS3Config,
    'benji.storage.b2-v1': StorageB2Config,
    'benji.transform.base-v1': TransformBaseConfig,
    'benji.transform.zstd-v1': TransformZstdConfig,
    'benji.transform.aes_256_gcm-v1': TransformAes256GcmConfig,
    'benji.transform.aes_256_gcm_ecc-v1': TransformAes256GcmEccConfig,
}


def get_model_for_module(module: str, version_major: int = 1) -> type[_BenjiBaseModel]:
    """Look up the Pydantic model for a given module and schema version."""
    name = f'{module}-v{version_major}'
    try:
        return _MODEL_REGISTRY[name]
    except KeyError:
        raise KeyError(f'No Pydantic model registered for module {name}')
