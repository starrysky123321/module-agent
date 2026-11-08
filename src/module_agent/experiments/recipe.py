"""Reviewed M5 inputs. Web clients cannot choose URLs, commands or images."""

import hashlib
import json

COMMIT = "a21bd677f62fcdee77c82419b898d421682e3fd2"
TITLE = "An Ensemble of Simple Convolutional Neural Network Models for MNIST Digit Recognition"
BASE_IMAGE = "pytorch/pytorch@sha256:c16f4c749e2d9e96878875cdf6cc45cddda1d1a36fddd371dd6f2360f1b6e2a2"
DOCKERFILE = f"""FROM {BASE_IMAGE}
RUN python -m pip install --no-cache-dir --disable-pip-version-check numpy==1.26.4 Pillow==11.3.0 torchsummary==1.5.1 && python -m pip check
ENV PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2
"""
SOURCES = {
    "code/train.py": "91ac18536557d141ad1f43a0d613bbc273455c467332360dbcc4092a848b79ae",
    "code/test.py": "7bf33f95826aa0556cc526cb895c7638c93b96720c702ada7558266ff69dce85",
    "code/datasets.py": "8292e92092e6e41fe6b5bdc8e1d82d4d194e706c470e11aa95686bd8fbd6f2b1",
    "code/ema.py": "456091f1143bc848b100a789ac33a8fc27a6dacd8a78de3e18382df395ce8bdf",
    "code/transforms.py": "0f0b046436337bcbb91f3099c1608d80940e041e635523fda67d0b443ee58894",
    "code/models/modelM3.py": "7d3a8cde7abd45d731cecd3d4c323cddbaf2e26e3d001b3e828e5f2e50d3aac0",
    "code/models/modelM5.py": "05e024b45a9b8df09d061a85c1cf6e7a0424f1cf0d1f8b10299a1c18ab5d7027",
    "code/models/modelM7.py": "ffee765540984f9c9abcec33f34f974baa6e15afd425e92699d41b0e8311775c",
}
PATCHED_DATASET = "fe0916fcfd5cc8c4d5671e756cb9e1eebc0b872aad547d2d08ff2af51cd29506"
DATA = {
    "train-images-idx3-ubyte": "440fcabf73cc546fa21475e81ea370265605f56be210a4024d2ca8f203523609",
    "train-labels-idx1-ubyte": "3552534a0a558bbed6aed32b30c495cca23d567ec52cac8be1a0730e8010255c",
    "t10k-images-idx3-ubyte": "8d422c7b0a1c1c79245a5bcf07fe86e33eeafee792b84584aec276f5a2dbc4e6",
    "t10k-labels-idx1-ubyte": "f7ae60f92e00ec6debd23a6088c31dbd2371eca3ffa0defaefb259924204aec6",
}
RECIPE_SHA256 = hashlib.sha256(json.dumps({
    "sources": SOURCES, "patched_dataset": PATCHED_DATASET,
    "data_gzip": DATA, "dockerfile": DOCKERFILE,
}, sort_keys=True).encode()).hexdigest()


def verify_curated_sources(files: dict[str, bytes]) -> bool:
    expected = {**SOURCES, "code/datasets.py": PATCHED_DATASET}
    return files.keys() == expected.keys() and all(
        hashlib.sha256(files[name]).hexdigest() == digest
        for name, digest in expected.items()
    )
