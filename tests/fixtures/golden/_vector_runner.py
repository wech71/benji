# SPDX-License-Identifier: LGPL-3.0-only
# SPDX-FileCopyrightText: 2025 elemental-lf
#
# AI-assisted development notice: authored with AI assistance (opencode/glm-5.2).
import base64
import json
import os
import sys

MASTER_KEY_B64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="

def make_plaintext():
    """128 bytes of deterministic data."""
    pattern = bytes.fromhex("deadbeefcafebabe")
    return (pattern * 16)[:128]

def run_encapsulate(phase_name):
    """Encrypt the known plaintext with the current benji's aes_256_gcm transform."""
    from benji.config import Config, ConfigDict
    from benji.transform.aes_256_gcm import Transform

    # Build a minimal config dict for the transform
    module_configuration = ConfigDict({'masterKey': MASTER_KEY_B64})
    # Config needs a configurationVersion to be valid
    config = Config(ad_hoc_config="""
configurationVersion: '1'
processName: benji-crypto-vector
logFile: /dev/stderr
hashFunction: BLAKE2b,digest_bits=256
blockSize: 65536
defaultStorage: dummy
databaseEngine: sqlite:///tmp/dummy_crypto_vector.sqlite
ios:
- name: file
  module: file
  configuration:
    simultaneousReads: 1
storages:
- name: dummy
  storageId: 1
  module: file
  configuration:
    path: /tmp/dummy_crypto_vector
""")

    transform = Transform(config=config, name='aes_256_gcm',
                          module_configuration=module_configuration)

    plaintext = make_plaintext()
    ciphertext, materials = transform.encapsulate(data=plaintext)

    result = {
        'phase': phase_name,
        'python': sys.version.split()[0],
        'plaintext_hex': plaintext.hex(),
        'ciphertext_hex': ciphertext.hex(),
        'ciphertext_len': len(ciphertext),
        'materials': materials,
        'materials_json': json.dumps(materials, sort_keys=True),
    }
    return result

def run_decapsulate(phase_name, ciphertext_hex, materials):
    """Decrypt the ciphertext with the current benji's aes_256_gcm transform."""
    from benji.config import Config, ConfigDict
    from benji.transform.aes_256_gcm import Transform

    module_configuration = ConfigDict({'masterKey': MASTER_KEY_B64})
    config = Config(ad_hoc_config="""
configurationVersion: '1'
processName: benji-crypto-vector
logFile: /dev/stderr
hashFunction: BLAKE2b,digest_bits=256
blockSize: 65536
defaultStorage: dummy
databaseEngine: sqlite:///tmp/dummy_crypto_vector.sqlite
ios:
- name: file
  module: file
  configuration:
    simultaneousReads: 1
storages:
- name: dummy
  storageId: 1
  module: file
  configuration:
    path: /tmp/dummy_crypto_vector
""")

    transform = Transform(config=config, name='aes_256_gcm',
                          module_configuration=module_configuration)

    ciphertext = bytes.fromhex(ciphertext_hex)
    plaintext = transform.decapsulate(data=ciphertext, materials=materials)

    result = {
        'phase': phase_name,
        'python': sys.version.split()[0],
        'decrypted_hex': plaintext.hex(),
        'decrypted_len': len(plaintext),
    }
    return result

if __name__ == '__main__':
    mode = sys.argv[1]
    vector_file = sys.argv[2]

    if mode == 'encapsulate':
        phase = sys.argv[3]
        result = run_encapsulate(phase)
        with open(vector_file, 'w') as f:
            json.dump(result, f, indent=2, sort_keys=True)
        print(f"encapsulate({phase}): wrote {vector_file}")
        print(f"  ciphertext_len={result['ciphertext_len']}, materials={result['materials_json']}")

    elif mode == 'decapsulate':
        phase = sys.argv[3]
        with open(vector_file, 'r') as f:
            vector = json.load(f)
        result = run_decapsulate(phase, vector['ciphertext_hex'], vector['materials'])
        # Verify
        expected = vector['plaintext_hex']
        actual = result['decrypted_hex']
        if expected == actual:
            print(f"decapsulate({phase}): PASS — decrypted plaintext matches original")
            result['verify'] = 'PASS'
            result['expected_hex'] = expected
        else:
            print(f"decapsulate({phase}): FAIL — decrypted={actual[:32]}... expected={expected[:32]}...")
            result['verify'] = 'FAIL'
            result['expected_hex'] = expected
        # Append result to the vector file
        vector['decapsulation_result'] = result
        with open(vector_file, 'w') as f:
            json.dump(vector, f, indent=2, sort_keys=True)

    elif mode == 'aes_keywrap_test':
        # Direct AES keywrap roundtrip test (no GCM, just the key wrapping)
        from benji.aes_keywrap import aes_wrap_key, aes_unwrap_key
        from Crypto.Random import get_random_bytes

        kek = base64.b64decode(MASTER_KEY_B64)
        envelope_key = get_random_bytes(32)
        wrapped = aes_wrap_key(kek, envelope_key)
        unwrapped = aes_unwrap_key(kek, wrapped)

        if unwrapped == envelope_key:
            print(f"aes_keywrap_test({sys.version.split()[0]}): PASS — wrap/unwrap roundtrip OK")
        else:
            print(f"aes_keywrap_test({sys.version.split()[0]}): FAIL — unwrapped != original")
            sys.exit(1)
