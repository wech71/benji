#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-3.0-only
# AI-assisted development notice: authored with AI assistance (opencode/glm-5.2).
#
# create-crypto-vectors.sh
#   Generates and verifies crypto envelope test vectors (Phase B3) for the
#   AES-256-GCM transform. Proves that the ported benji (Python 3.13) can
#   decrypt what the old benji (Python 3.11) encrypted and vice versa.
#
# Usage:
#   ./create-crypto-vectors.sh [--help]
#
# Prerequisites:
#   - Python 3.11 at $BENJI_PYTHON (default: python3.11) with old benji installed
#   - Python 3.13 at .venv/bin/python with ported benji installed
#   - No containers needed — this tests the crypto transform directly.
#
# Environment variables:
#   OLD_BENJI_VENV   path for the old benji venv (default: ./venv.old)
#   BENJI_PYTHON     Python interpreter for the old venv (default: python3.11)
#   VECTOR_DIR       output directory (default: ./tests/fixtures/golden/)

set -euo pipefail

OLD_BENJI_VENV="${OLD_BENJI_VENV:-./venv.old}"
BENJI_PYTHON="${BENJI_PYTHON:-python3.11}"
VECTOR_DIR="${VECTOR_DIR:-./tests/fixtures/golden}"
PORT_PYTHON=".venv/bin/python"

# Fixed master key (deterministic, 32 bytes, base64-encoded)
# 0x00 0x01 0x02 ... 0x1f — NOT a real key, only for test vectors
MASTER_KEY_B64="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="

# Known plaintext (128 bytes of deterministic data)
PLAINTEXT_HEX="deadbeefcafebabe"  # repeated to fill 128 bytes

log() {
    echo "[B3] $*"
}

# --------------------------------------------------------------------------
# Check prerequisites
# --------------------------------------------------------------------------
check_prereqs() {
    if [[ ! -x "${PORT_PYTHON}" ]]; then
        log "ERROR: ${PORT_PYTHON} not found. Set up the port venv first (.venv/)."
        exit 1
    fi
    if [[ ! -x "${OLD_BENJI_VENV}/bin/python" ]]; then
        log "ERROR: ${OLD_BENJI_VENV}/bin/python not found. Run create-golden-master.sh first."
        exit 1
    fi
    mkdir -p "${VECTOR_DIR}"
}

# --------------------------------------------------------------------------
# Generate test vectors: encrypt with old benji, decrypt with ported benji
# --------------------------------------------------------------------------
generate_vectors() {
    log "Generating crypto test vectors..."
    log "  Master key (base64): ${MASTER_KEY_B64}"
    log "  Old benji:  ${OLD_BENJI_VENV}/bin/python ($(${OLD_BENJI_VENV}/bin/python --version 2>&1))"
    log "  Port benji:  ${PORT_PYTHON} ($(${PORT_PYTHON} --version 2>&1))"

    # The Python script does the actual crypto work using benji's transform
    # module directly. It runs in two phases:
    #   Phase 1 (old benji): encapsulate known plaintext → save ciphertext + materials
    #   Phase 2 (ported benji): decapsulate → verify plaintext matches
    #   Phase 3 (ported benji): encapsulate known plaintext → save ciphertext + materials
    #   Phase 4 (old benji): decapsulate → verify plaintext matches

    local script="${VECTOR_DIR}/_vector_runner.py"
    cat > "${script}" << 'PYEOF'
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
PYEOF

    # Phase 0: AES keywrap roundtrip on both Pythons
    log "Phase 0a: AES keywrap roundtrip (old benji / Py3.11)..."
    "${OLD_BENJI_VENV}/bin/python" "${script}" aes_keywrap_test ""
    log "Phase 0b: AES keywrap roundtrip (ported benji / Py3.13)..."
    "${PORT_PYTHON}" "${script}" aes_keywrap_test ""

    # Phase 1: Old benji encapsulates (encrypts)
    local v1="${VECTOR_DIR}/vector_old_encapsulate.json"
    log "Phase 1: Old benji (Py3.11) encapsulating known plaintext..."
    "${OLD_BENJI_VENV}/bin/python" "${script}" encapsulate "${v1}" "old_encapsulate"

    # Phase 2: Ported benji decapsulates (decrypts) what old benji encrypted
    log "Phase 2: Ported benji (Py3.13) decapsulating old benji's ciphertext..."
    "${PORT_PYTHON}" "${script}" decapsulate "${v1}" "ported_decapsulate"

    # Phase 3: Ported benji encapsulates (encrypts)
    local v2="${VECTOR_DIR}/vector_ported_encapsulate.json"
    log "Phase 3: Ported benji (Py3.13) encapsulating known plaintext..."
    "${PORT_PYTHON}" "${script}" encapsulate "${v2}" "ported_encapsulate"

    # Phase 4: Old benji decapsulates (decrypts) what ported benji encrypted
    log "Phase 4: Old benji (Py3.11) decapsulating ported benji's ciphertext..."
    "${OLD_BENJI_VENV}/bin/python" "${script}" decapsulate "${v2}" "old_decapsulate"

    # Summary
    log ""
    log "=== B3 Crypto Test Vector Summary ==="
    log "  Master key (base64): ${MASTER_KEY_B64}"
    log "  Plaintext: 128 bytes (deterministic, deadbeefcafebabe * 16)"
    log ""
    log "  Cross-version compatibility:"
    local v1_result v2_result
    v1_result=$("${PORT_PYTHON}" -c "import json; d=json.load(open('${v1}')); print(d.get('decapsulation_result',{}).get('verify','MISSING'))")
    v2_result=$("${OLD_BENJI_VENV}/bin/python" -c "import json; d=json.load(open('${v2}')); print(d.get('decapsulation_result',{}).get('verify','MISSING'))")
    log "    Old→Ported (old encrypts, ported decrypts): ${v1_result}"
    log "    Ported→Old (ported encrypts, old decrypts): ${v2_result}"
    log ""
    log "  Vector files:"
    log "    ${v1}"
    log "    ${v2}"
    log ""
    if [[ "${v1_result}" == "PASS" && "${v2_result}" == "PASS" ]]; then
        log "  ✅ ALL CRYPTO TESTS PASSED — byte-identical cross-version parity confirmed."
    else
        log "  ❌ SOME CRYPTO TESTS FAILED — see vector files for details."
        exit 1
    fi
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
check_prereqs
generate_vectors
